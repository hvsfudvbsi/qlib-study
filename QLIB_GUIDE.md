# Qlib 使用指南（基于 fork hvsfudvbsi/qlib @ main be725493）

> 本指南面向本机环境（`/root/mywork/qlib` + `qlib-study/.venv`），所有命令均已在本机验证或与 week01/selfdata 实测一致。踩坑细节见 [`notes/week01.md`](notes/week01.md)。

## 1. 项目是什么：工作作用

Qlib 是微软开源的 **AI 导向量化投研平台**（⭐48.6k），解决量化研究的完整链路问题：

```
数据管理 → 特征工程 → 模型训练 → 组合构建 → 回测评估 → 实验管理
   Data      Handler     Model     Strategy    Backtest    Recorder(mlflow)
```

**它不做什么**：不做实盘交易对接、不做数据源（自带数据集截止 2020-09，需自建更新，见 §4）。

**核心价值**（为什么选它而不是自己写 pandas）：
- **表达式引擎**：`$close/Ref($close,1)-1` 这类因子公式直接在二进制数据上高效计算，不用手写滚动窗口
- **防未来函数的工程约束**：标签模板、时间切分、复权口径内建于框架
- **模型 Zoo**：LightGBM/Transformer/HIST/TRA 等十几篇论文模型同接口可比
- **实验可复现**：qrun 配置驱动，一次实验 = 一份 yaml + 一组 mlflow 工件

**四层架构**：

| 层 | 关键类 | 职责 |
|---|---|---|
| Infra（数据） | `D`（Client）、`Cache`、`.bin` 存储 | 交易日历/股票池/特征二进制读取，表达式计算 |
| Workflow（学习） | `DataHandlerLP`、`DatasetH`、`Model`、`Record` | 特征定义→数据集切分→训练→预测记录 |
| Interface（回测） | `Exchange`、`PortAnaRecord`、`TopkDropoutStrategy` | 账户/成交模拟/涨跌停停牌约束/绩效分析 |
| Application | `qlib.contrib.*`、RD-Agent | 高频、RL、在线服务、LLM 自动因子挖掘 |

## 2. 本地副本现状（三条路径的分工）

| 路径 | 是什么 | 什么时候用 |
|---|---|---|
| `/root/mywork/qlib` | **fork 完整仓库**（origin=hvsfudvbsi/qlib，upstream=microsoft/qlib） | 改源码/跑实验脚本/提 PR 的主工作区 |
| `/root/mywork/qlib-src` | 旧浅克隆（week01 建的） | 仅历史文档引用，可删 |
| `qlib-study/.venv` 里的 `pyqlib 0.9.7` | pip 安装的发行包 | import qlib 的运行环境（与 fork 源码独立） |

> **重要**：venv 里装的是 PyPI 版 0.9.7。要让 `import qlib` 用上 fork 源码：`.venv/bin/pip install -e /root/mywork/qlib --no-deps`（**不要带依赖重装**，会破坏 week01 钉好的 numpy/pandas/plotly 矩阵）。不改源码则无需安装，直接用仓库里的 scripts/examples 即可。

## 3. 环境速查

```bash
# 运行环境（已就绪，见 notes/week01.md 的依赖矩阵）
source /root/mywork/qlib-study/.venv/bin/activate   # 或直接用绝对路径 .venv/bin/python

# 运行 qlib 实验的固定环境变量（新版 mlflow 必需）
export MLFLOW_ALLOW_FILE_STORE=true

# fork 日常操作
cd /root/mywork/qlib
git fetch upstream && git merge upstream/main   # 同步微软上游
git push origin main                            # 推到自己的 fork（需凭据 URL）
```

## 4. 数据三板斧（scripts/ 核心工具）

### 4.1 官方数据集（入门/对照用，截止 2020-09-25）

```bash
P=/root/mywork/qlib-study/.venv/bin/python
$P /root/mywork/qlib/scripts/get_data.py qlib_data \
    --target_dir ~/.qlib/qlib_data/cn_data --region cn    # 521M，1999~2020-09
```

### 4.2 自建数据转 .bin（当前主用路径）

```bash
# CSV 规范：每股票一个文件（如 SH600000.csv），列 date,symbol,open,close,high,low,volume,factor
$P /root/mywork/qlib/scripts/dump_bin.py dump_all \
    --data_path /root/mywork/qlib-study/data/csv_selfdata \
    --qlib_dir ~/.qlib/qlib_data/my_cn_data \
    --include_fields open,close,high,low,volume,factor \
    --date_field_name date --symbol_field_name symbol

# 健康检查（缺失值/价格大跳变/factor 完整性）
$P /root/mywork/qlib/scripts/check_data_health.py check_data \
    --qlib_dir ~/.qlib/qlib_data/my_cn_data

# 增量更新已有数据（追加新交易日，--mode update）
$P /root/mywork/qlib/scripts/dump_bin.py dump_update --help
```

CSV 生成：`qlib-study/data/export_akshare_csv.py`（akshare 腾讯源，含停牌补齐+instruments 生成；tushare 标准因子方案见 `notes/tushare_pro_research.md`）。

### 4.3 数据目录结构（dump 后）

```
~/.qlib/qlib_data/my_cn_data/
├── calendars/day.txt          交易日历（一行一天）
├── instruments/{all,stocks}.txt   股票池：SYM\t开始\t结束
└── features/<代码>/{close,open,high,low,volume,factor}.day.bin
```

## 5. 三种用法

### 5.1 qrun：配置驱动（推荐的标准工作流）

```bash
qrun /root/mywork/qlib/examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml
# 或（等价，qrun 本质就是它）
$P /root/mywork/qlib/qlib/workflow/cli.py examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml
```

yaml 四大块（完整骨架见 `STUDY_PLAN.md` 第 3 周）：
```yaml
qlib_init:      # provider_uri 数据目录 + region cn
market: csi300  # 股票池（instruments 文件名）
task:           # model + dataset（handler 特征/标签 + segments 时间切分）
port_analysis_config:   # executor + strategy + backtest（含成本/涨跌停/账户）
```

官方配置模板库：`examples/benchmarks/*/workflow_config_*.yaml`（每个模型都有 Alpha158/Alpha360 × csi300/csi500 组合）。

### 5.2 Python API：代码驱动（可编程实验）

参考 `runs/selfdata/run_e2e.py`，核心骨架：

```python
import qlib
qlib.init(provider_uri="~/.qlib/qlib_data/my_cn_data", region="cn")

from qlib.utils import init_instance_by_config
from qlib.workflow import R
from qlib.workflow.record_temp import SignalRecord, PortAnaRecord

task = {
    "model":   {"class": "LGBModel", "module_path": "qlib.contrib.model.gbdt"},
    "dataset": {
        "class": "DatasetH", "module_path": "qlib.data.dataset",
        "kwargs": {
            "handler": {"class": "Alpha158", "module_path": "qlib.contrib.data.handler",
                        "kwargs": {"start_time": "2024-01-02", "end_time": "2025-09-17",
                                   "fit_start_time": "2024-01-02", "fit_end_time": "2024-06-30",
                                   "instruments": "stocks"}},
            "segments": {"train": ("2024-01-02", "2024-06-30"),
                         "valid": ("2024-07-01", "2024-12-31"),
                         "test":  ("2025-01-01", "2025-09-17")},
        },
    },
}
with R.start(experiment_name="my_exp"):
    model = init_instance_by_config(task["model"])
    dataset = init_instance_by_config(task["dataset"])
    model.fit(dataset)
    R.save_objects(trained_model=model)
    recorder = R.get_recorder()
    SignalRecord(model, dataset, recorder).generate()          # 预测
    PortAnaRecord(recorder, port_analysis_config, "day").generate()  # 回测（strategy.kwargs 需传 model/dataset）
```

### 5.3 数据层直用：表达式引擎（研究因子时最常用）

```python
from qlib.data import D
df = D.features(
    ["SH600000", "SH600519"],                      # 或 D.instruments("stocks")
    ["$close/$factor",                             # 真实价（复权还原）
     "Ref($close,1)/$close",                       # 引用昨日
     "Mean($volume,20)/($volume+1e-12)",           # 20日均量比
     "Corr($close, $volume, 10)"],                 # 10日价量相关性
    start_time="2025-09-01", end_time="2025-09-17",
)
```

常用操作符（`qlib.data.ops`）：`Ref Mean Sum Std Var Max Min Med Rank Delta Slope Rsquare Resi EMA Corr Cov Quantile IdxMax IdxMin Count`。价格字段：`$open $close $high $low $volume $factor`（自建扩展字段如 `$pe` 在 dump 时 include 即可引用）。

其他高频 API：`D.calendar()` 交易日历、`D.list_instruments(D.instruments("stocks"), as_list=True)` 池成员、`D.features(..., universe=D.instruments("csi300"))`。

## 6. 模型 Zoo（qlib.contrib.model）

| 类 | 说明 | 依赖 |
|---|---|---|
| `LGBModel` | LightGBM，**首选 baseline**（快、稳、可解释） | 已装 ✓ |
| `XGBModel` | XGBoost | 需 pip install xgboost |
| `CatBoostModel` | CatBoost | 需 pip install catboost |
| `LinearModel` | 岭回归/Lasso 等线性家族 | 已装 ✓ |
| `DNNModelPytorch` | PyTorch MLP | 需 pip install torch |
| `Transformer/Localformer/TRA/ADARNN/HIST/DoubleEnsemble/TCN/TCTS/Tabnet/ADD/KRNN/Sandwich` | 论文模型（examples/benchmarks 各有目录与配置） | torch 系 |

批量跑分：`examples/run_all_model.py`（跑 benchmarks 里全部模型同口径对比）。训练注意：小内存机器加 `OMP_NUM_THREADS=1`。

## 7. 回测与绩效解读

- **A 股约束**：`trade_unit: 100`（一手）、`limit_threshold: 0.095`（涨跌停）、`open_cost: 0.0005 / close_cost: 0.0015 / min_cost: 5`
- **策略**：`TopkDropoutStrategy`（topk 持有数 / n_drop 每期最多换掉数）——大池子用 topk=30/n_drop=3；**结束日距日历末尾 ≥2 个交易日**（否则 IndexError，见 runs/selfdata/README.md）
- **risk_analysis 表怎么读**（含成本行才是真实业绩）：
  - `annualized_return` 年化、`max_drawdown` 最大回撤
  - `information_ratio` 超额 IR（>1 良好，>2 优秀）
  - `mean/std` 日均超额/日波动
- **模型质量先看 IC**：SigAna 的 IC/Rank IC（日度横截面预测值与实际收益的相关性），IC<0.03 基本无信号，回测赚钱也可能是过拟合

## 8. 实验管理（R / Recorder / mlflow）

- `R.start(experiment_name=...)` → `R.get_recorder()` → 工件落在 `./mlruns/<exp_id>/<run_id>/`
- 关键工件：`pred.pkl`（预测）、`label.pkl`、`portfolio_analysis/port_analysis_1day.pkl`（风险表）、`portfolio_analysis/report_normal_1day.pkl`（每日持仓报告）
- 读取：`recorder.load_object("pred.pkl")`；或直接 `pd.read_pickle(mlruns/...)`
- 旧实验回溯：`R.get_recorder(experiment_name=..., recorder_id=...)`；`R.list_experiments()`
- 坑：mlflow 相对路径会把 CWD 拼进工件路径（曾生成 `root/mywork/...` 嵌套目录），**固定在一个目录里跑**（如 runs/selfdata/）

## 9. 进阶入口（examples/ 目录）

| 目录 | 内容 | 对应学习计划 |
|---|---|---|
| `examples/workflow_by_code.ipynb` | 入门 notebook（week01 已跑通） | 第 1 周 |
| `examples/benchmarks/` | 全模型配置与跑分 | 第 3、11 周 |
| `examples/model_rolling/` `rolling_process_data/` | 滚动训练 | 第 5 周 |
| `examples/online_srv/` | 在线服务/自动滚动 | M3 |
| `examples/highfreq/` | 1 分钟高频数据与因子 | 第 10 周 |
| `examples/nested_decision_execution/` | 日级策略+分钟级执行 | 第 10 周 |
| `examples/rl/` | 强化学习框架 | 选修 |
| microsoft/RD-Agent | LLM 自动因子挖掘（独立仓库，对接 qlib） | 第 9 周选做 |

## 10. Fork 维护与贡献

```bash
# 同步上游（微软持续活跃，建议每周一次）
cd /root/mywork/qlib
git fetch upstream
git merge upstream/main          # 或 rebase
git push origin main             # 凭据 URL 方式，token 不入 config

# 提 PR 流程
git checkout -b feat/my-source-ts
# ...改动...
git push origin feat/my-source-ts   # 推到自己的 fork
# GitHub 上从 hvsfudvbsi:feat/my-source-ts → microsoft:main 发起 PR
```

适合回馈上游的点（我们在自建数据管线中实测发现的）：dump_bin 对停牌日 NaN 补齐的文档补充、benchmark/limit_threshold 对 20cm 板块的说明、workflow_by_code 的依赖矩阵说明。

## 11. 路径与命令速查

```text
fork 仓库          /root/mywork/qlib          （origin=fork, upstream=microsoft）
venv             /root/mywork/qlib-study/.venv   （pyqlib 0.9.7 + 钉版依赖矩阵）
官方数据          ~/.qlib/qlib_data/cn_data      （~2020-09）
自建数据          ~/.qlib/qlib_data/my_cn_data   （3 股+指数，2024~2025-09）
CSV 导出脚本      qlib-study/data/export_akshare_csv.py
端到端示例       qlib-study/runs/selfdata/run_e2e.py
踩坑记录         qlib-study/notes/week01.md ｜ tushare 方案 notes/tushare_pro_research.md
```

```bash
# 最常用三条
$P /root/mywork/qlib/scripts/dump_bin.py dump_all --help          # 自建数据入库
qrun <yaml>                                                       # 标准实验
$P -c "import qlib; qlib.init(provider_uri='~/.qlib/qlib_data/my_cn_data', region='cn'); \
     from qlib.data import D; print(D.features(['SH600000'], ['\$close/\$factor'], \
     start_time='2025-09-16', end_time='2025-09-17'))"            # 数据抽查
```
