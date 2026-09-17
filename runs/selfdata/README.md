# 自建数据端到端训练验证记录（2026-09-17）

> 目标：验证「akshare 导出 CSV → dump_bin → Alpha158 + LGBM 训练 → IC 评估 → 含成本回测」全链路可用。
> 结果：✅ **E2E PASSED**（`runs/selfdata/run_e2e.py`，EXIT=0）

## 数据与配置

| 项 | 值 |
|---|---|
| 数据 | `~/.qlib/qlib_data/my_cn_data`（自建：浦发/平安/茅台 + 上证指数） |
| 区间 | 2024-01-02 ~ 2025-09-17（416 个交易日） |
| 股票池 | `stocks`（3 只）；benchmark `SH000001`（tx 源导出，factor 恒 1.0） |
| 模型 | Alpha158（158 特征）+ LGBM，train 2024H1 / valid 2024H2 / test 2025-01~09 |
| 组合 | TopkDropout topk=2, n_drop=1；账户 100 万；含成本（0.05%+0.15%+最低5元） |

## 结果

| 指标（test 2025-01~09，172 天） | 数值 | 解读 |
|---|---|---|
| IC / ICIR | **-0.0090** / -0.0124 | 无预测力（0 附近） |
| Rank IC / Rank ICIR | 0.0066 / 0.0090 | 同上 |
| 超额年化（含成本） | -10.5% | 交易成本吃掉收益 |
| 超额 IR（含成本） | -0.67 | — |

**数字可信、性能平庸——这正是预期**：3 只股票的横截面仅 3 个样本点，训练数据 ~360 个样本日，模型学不到稳定规律属于正常现象。本次验证的是**管道工程正确性**（数据格式、字段口径、股票池、benchmark、训练/回测链路），不是策略有效性。

## 过程中的坑（3 个，均已修复并写入脚本注释）

1. **`Alpha158` 对象没有 `.features` 属性**：取特征列表要用 `handler.get_feature_config()` 返回的 `(fields, names)`
2. **TopkDropout 策略必须显式传 `model`/`dataset` 对象**（官方 notebook 同款写法）：否则 `create_signal_from` 抛 `NotImplementedError: This type of signal is not supported`
3. **回测结束日必须距日历末尾富余 ≥2 个交易日**：qlib 回测最后一步要取"下一交易日"（`calendar[i+1]`），日历恰好在回测结束日截止时抛 `IndexError: index 416 out of bounds`。官方示例因日历有富余从未暴露此问题——自建"新鲜"数据时必踩。已把结束日提前到 2025-09-15

## 与官方 cn_data 流程的差异（自建数据特有）

- 官方数据有 `factor.day.bin` 缺失问题（见 notes/week01.md），自建数据显式写入了 factor → 回测不再有 adjusted_price 模式警告
- benchmark 需要自己导出指数：腾讯源指数 qfq==raw（factor=1.0），直接可用；东财源不支持指数（脚本已显式拒绝）
- 日历=全量 CSV 日期并集：`SH000001` 也在数据里，日历完整性由它兜底

## 复现

```bash
# 1) 导出（约 1 分钟，tx 源）
cd data && ../.venv/bin/python export_akshare_csv.py \
    --symbols sh600000 sz000001 sh600519 sh000001 \
    --start 20240101 --end 20250917 --out-dir csv_selfdata \
    --source tx --pool stocks=sh600000,sz000001,sh600519

# 2) dump + 挂载股票池
cd .. && .venv/bin/python /root/mywork/qlib-src/scripts/dump_bin.py dump_all \
    --data_path data/csv_selfdata --qlib_dir ~/.qlib/qlib_data/my_cn_data \
    --include_fields open,close,high,low,volume,factor \
    --date_field_name date --symbol_field_name symbol
cp data/csv_selfdata/instruments/*.txt ~/.qlib/qlib_data/my_cn_data/instruments/

# 3) 端到端训练
cd runs/selfdata && MLFLOW_ALLOW_FILE_STORE=true OMP_NUM_THREADS=1 \
    ../../.venv/bin/python run_e2e.py
```

## 下一步建议

- 扩大股票池（≥300 只，覆盖 CSI300 成分）后重跑本脚本，IC 才有统计意义
- 引入扩展字段（turnover/amount → 自定义 handler）与滚动训练（STUDY_PLAN 第 5 周）
- 周更方案：`dump_bin.py --mode update` 增量追加最新交易日（指数 sh000001 继续兜底日历）
