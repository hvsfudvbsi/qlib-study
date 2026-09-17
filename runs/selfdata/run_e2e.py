#!/usr/bin/env python3
"""用自建数据（akshare 导出 → dump_bin）跑通 Alpha158 + LGBM 端到端小规模训练。

数据：~/.qlib/qlib_data/my_cn_data（3 只股票 + 上证指数 benchmark，2024-01-02 ~ 2026-09-17，658 天）
流程：Alpha158 特征 → LGBM 训练（train 2024 全年 / valid 2025 全年）→ test 2026 预测
      → IC 评估（自算，交叉核对 pred/label 两个来源）→ TopkDropout 含成本回测

运行：cd runs/selfdata && MLFLOW_ALLOW_FILE_STORE=true ../../.venv/bin/python run_e2e.py
"""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore")

import pandas as pd

import qlib
from qlib.constant import REG_CN
from qlib.data import D
from qlib.utils import init_instance_by_config
from qlib.workflow import R
from qlib.workflow.record_temp import PortAnaRecord, SignalRecord

PROVIDER_URI = "~/.qlib/qlib_data/my_cn_data"
MARKET = "stocks"  # csv_selfdata/instruments/stocks.txt（3 只股票）
BENCHMARK = "SH000001"  # 上证指数（tx 源导出，factor=1）
TASK_SEGMENTS = {
    "train": ("2024-01-02", "2024-12-31"),   # 全年 2024（~240 个交易日）
    "valid": ("2025-01-01", "2025-12-31"),   # 全年 2025
    "test":  ("2026-01-01", "2026-09-15"),   # 2026 年样本外（回测结束日距日历末尾留 2 个交易日）
}


def main() -> None:
    qlib.init(provider_uri=PROVIDER_URI, region=REG_CN)

    # ---- 0) 数据自检 ----
    instruments = D.list_instruments(instruments=D.instruments(MARKET), as_list=True)
    cal = D.calendar()
    print(f"[check] stocks 池: {sorted(instruments)}")
    print(f"[check] 日历: {len(cal)} 天, {str(cal[0])[:10]} ~ {str(cal[-1])[:10]}")
    assert len(instruments) == 3, "stocks 池应为 3 只"
    assert "SH000001" in D.list_instruments(instruments=D.instruments("all"), as_list=True)

    # ---- 1) 任务定义（Alpha158 + LGBM，小规模） ----
    data_handler_config = {
        "start_time": TASK_SEGMENTS["train"][0],
        "end_time": TASK_SEGMENTS["test"][1],
        "fit_start_time": TASK_SEGMENTS["train"][0],
        "fit_end_time": TASK_SEGMENTS["train"][1],
        "instruments": MARKET,
    }
    task = {
        "model": {"class": "LGBModel", "module_path": "qlib.contrib.model.gbdt"},
        "dataset": {
            "class": "DatasetH",
            "module_path": "qlib.data.dataset",
            "kwargs": {
                "handler": {
                    "class": "Alpha158",
                    "module_path": "qlib.contrib.data.handler",
                    "kwargs": data_handler_config,
                },
                "segments": TASK_SEGMENTS,
            },
        },
    }
    # 3 只股票的小池子：topk=2（持有 2/3 仓位），n_drop=1（每天最多换 1 只）
    port_analysis_config = {
        "executor": {
            "class": "SimulatorExecutor",
            "module_path": "qlib.backtest.executor",
            "kwargs": {"time_per_step": "day", "generate_portfolio_metrics": True},
        },
        "strategy": {
            "class": "TopkDropoutStrategy",
            "module_path": "qlib.contrib.strategy.signal_strategy",
            "kwargs": {"topk": 2, "n_drop": 1},
        },
        "backtest": {
            "start_time": TASK_SEGMENTS["test"][0],
            # 结束日必须距日历末尾富余 ≥2 个交易日：qlib 回测最后一步要取"下一交易日"，
            # 否则 IndexError（自建新鲜数据必踩，官方示例因日历有富余未暴露）
            "end_time": "2026-09-15",
            "account": 1_000_000,
            "benchmark": BENCHMARK,
            "exchange_kwargs": {
                "freq": "day",
                "limit_threshold": 0.095,
                "deal_price": "close",
                "open_cost": 0.0005,
                "close_cost": 0.0015,
                "min_cost": 5,
            },
        },
    }

    # ---- 2) 训练 + 预测 + 回测 ----
    with R.start(experiment_name="selfdata_e2e"):
        model = init_instance_by_config(task["model"])
        dataset = init_instance_by_config(task["dataset"])
        fields, _ = dataset.handler.get_feature_config()
        print(f"[train] Alpha158 特征数: {len(fields)}")
        model.fit(dataset)
        R.save_objects(trained_model=model)

        # 官方 workflow_by_code 同款：TopkDropout 需要 model/dataset 对象来生成交易信号
        port_analysis_config["strategy"]["kwargs"]["model"] = model
        port_analysis_config["strategy"]["kwargs"]["dataset"] = dataset

        recorder = R.get_recorder()
        sr = SignalRecord(model, dataset, recorder)
        sr.generate()

        par = PortAnaRecord(recorder, port_analysis_config, "day")
        par.generate()

    # ---- 3) IC 评估（自算 + 交叉核对两个数据来源） ----
    pred = recorder.load_object("pred.pkl")  # 来源 A：recorder 工件
    label = dataset.prepare("test", col_set="label")  # 来源 B：dataset 直取
    df = pd.concat([label, pred], axis=1, sort=True).reindex(label.index).dropna()
    assert not df.empty, "pred/label 合并后为空，索引对齐失败"
    ic = df.groupby(level="datetime").apply(lambda x: x.iloc[:, 1].corr(x.iloc[:, 0]))
    ric = df.groupby(level="datetime").apply(lambda x: x.iloc[:, 1].corr(x.iloc[:, 0], method="spearman"))
    print(f"\n[result] IC（test {TASK_SEGMENTS['test'][0]} ~ {TASK_SEGMENTS['test'][1]}）")
    print(f"  样本天数  = {len(ic)}")
    print(f"  IC        = {ic.mean():.4f}  (ICIR {ic.mean() / ic.std():.4f})")
    print(f"  Rank IC   = {ric.mean():.4f}  (Rank ICIR {ric.mean() / ric.std():.4f})")

    # ---- 4) 回测风险表 ----
    pa = recorder.load_object("portfolio_analysis/port_analysis_1day.pkl")
    print("\n[result] 回测风险表（risk_analysis）")
    for name, table in pa.items():
        print(f"  -- {name}")
        print(table.round(4).to_string())

    print("\nE2E SELF-DATA VERIFICATION PASSED")


if __name__ == "__main__":
    main()
