# Qlib 在 A 股上的学习计划（12 周）

## 一、学习目标

用 12 周，从"装好 qlib、跑通官方示例"进阶到"用自有 A 股数据训练选股模型、完成滚动回测、产出可用研究报告"。

三个里程碑：

1. **M1（第 1~3 周）跑通官方流程**：QLib 安装、`cn_data` 数据集、Alpha158 + LightGBM/XGBoost 全流程复现。
2. **M2（第 4~9 周）吃透四大组件**：Data（表达式引擎/复权/Dump）、Forecast（模型/特征/标签）、Portfolio（组合/成交/成本）、Report（IC/Rank IC/回撤/年化），并接入自有 A 股数据。
3. **M3（第 10~12 周）毕业项目**：构建自定义 A 股选股因子集 + 模型训练 + 滚动交叉验证 + 参数化回测，形成可复现的 `workflow` 与报告。

**收益观念**：IC / Rank IC 看的是横截面排序能力；年化收益和回撤看的是策略落地能力。没有持续的 IC，回测赚钱大概率是过拟合。

建议节奏：每周 5~8 小时，"读官方文档 → 改 workflow yaml → 跑通 → 换数据/换模型 → 写小结"五步走。

---

## 二、必读资料（按周推进）

- 官方中文文档：<https://qlib.readthedocs.io/en/latest/>（英文版内容更全，两者对照）
- qlib 论文：*Qlib: An AI-oriented Quantitative Investment Platform* (arXiv:2009.11189)
- 仓库 `examples/` 目录：官方权威示例，遇到问题先搜 issues，再搜中文社区文章
- 数据源：**Qlib 自带 `cn_data`**（即官方 China Market 数据）；第 6~9 周再考虑 akshare/tushare（若涉及请注意 API 配额与合规）

---

## 三、12 周路线

### 第 1 周：环境安装与 QLib 快速体验

**目标**：独立安装 qlib，跑通内置数据与示例。

**学习内容**：

- 安装方式对比：`pip install pyqlib` 与源码 `pip install .` 的区别，Python 3.8+/3.10 适配坑
- `qlib.init(provider_uri=..., region="cn")` 的作用（provider_uri 是数据目录）
- 官方文档 Quick Start、`examples/tutorial`（workflow_by_code.ipynb）

**实践**：

1. `conda create -n qlib python=3.10` + 安装 pyqlib，记录并解决所有报错
2. 下载官方 A 股数据：`python scripts/get_data.py qlib_data --target_dir ~/.qlib/qlib_data/cn_data --region cn`
3. 跑通 `examples/tutorial` 中的 notebook（含数据获取 → 特征 → 训练 → 回测全流程）

**验收**：

- notebook 全流程无报错跑完；能口头解释 provider_uri、region、handler、dataset、strategy 各是什么
- 写一篇《安装踩坑记录》

**常用命令**：

```bash
python scripts/get_data.py qlib_data --target_dir ~/.qlib/qlib_data/cn_data --region cn
jupyter notebook examples/tutorial/workflow_by_code.ipynb
```

### 第 2 周：Data Handler 与 Alpha158 深入

**目标**：理解 qlib 的数据抽象，能自定义特征列。

**学习内容**：

- `Alpha158` / `Alpha360` 的来源（微软论文里的 158/360 个因子）、构造方式
- `DataHandlerLP`：infer/learn 两种数据处理链路
- 常用 Processor：`RobustZScoreNorm`、`Fillna`、`DropnaLabel`、`CSRankNorm`
- `QlibDataLoader` 与表达式引擎（`$close/Ref($close,1)-1`、`Mean($close, 20)` 等）

**实践**：

1. 用 `QlibDataLoader` 打印 Alpha158 的部分特征，理解每列含义
2. 手写 `DataHandlerLP` 子类，在 Alpha158 基础上追加自定义特征
3. 用 `D.features()` 直接取数，验证表达式引擎计算结果与手写 pandas 的一致性

**验收**：能不看文档默写一个最小可用的 DataHandlerLP 子类，并解释 `learn` / `infer` 链路差异

### 第 3 周：Model 训练与预测

**目标**：跑通 `R + Dataset + Model` 训练范式。

**学习内容**：

- `Dataset`（`TSDatasetH`）、`Model` 基类，`init` → `fit` → `predict` 生命周期
- 内置模型：LightGBM/XGBoost/Linear（推荐从 LGBM 起步，样本内外表现稳健）
- `SignalRecord` / `SigAnaRecord` / `PortAnaRecord`：记录与评估三件套
- **标签定义**：`Ref($close, -2) / Ref($close, -1) - 1` 的含义（T 日收盘信号 → T+1 开盘附近成交 → T+2 收盘评估，防未来函数）

**实践**：

1. 用 `qrun` 跑通 LightGBM 模型全流程（yaml 配置驱动）
2. 把模型换成 XGBoost、Linear，对比 IC / Rank IC / 年化 / 回撤
3. 改标签窗口（-2/-1 → -5/-1 等），观察 IC 与换手率变化

**验收**：能说清楚"为什么 qlib 默认标签是 `Ref($close,-2)/Ref($close,-1)-1`"；四种指标各自反映什么

**最小 `qrun` 配置骨架**（详见 `examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml`）：

```yaml
qlib_init:
    provider_uri: "~/.qlib/qlib_data/cn_data"
    region: cn
market: &market csi300
benchmark: &benchmark SH000300
data_handler_config: &data_handler_config
    start_time: 2010-01-01
    end_time: 2023-12-31
    fit_start_time: 2018-01-01
    fit_end_time: 2020-12-31
    instruments: *market
    infer_processors: [...]
    learn_processors: [...]
port_analysis_config: &port_analysis_config
    executor:
        class: SimulatorExecutor
        module_path: qlib.backtest.executor
        kwargs:
            time_per_step: day
            generate_portfolio_metrics: True
    backtest:
        start_time: 2017-01-01
        end_time: 2020-12-31
        benchmark: *benchmark
        account: 100000000
        exchange_kwargs:
            trade_unit: 100          # A股一手 100 股
            limit_threshold: 0.099   # A股涨跌停 ±10%（近似）
            deal_price: close
    strategy:
        class: TopkDropoutStrategy
        module_path: qlib.contrib.strategy
        kwargs:
            topk: 30
            n_drop: 3
task:
    model:
        class: LGBMModel
        module_path: qlib.contrib.model.gbdt
    dataset:
        class: DatasetH
        module_path: qlib.data.dataset
        kwargs:
            handler:
                class: Alpha158
                module_path: qlib.contrib.data.handler
                kwargs: *data_handler_config
            segments:
                train: [2010-01-01, 2017-12-31]
                valid: [2018-01-01, 2020-12-31]
                test:  [2021-01-01, 2023-12-01]
```

### 第 4 周：回测系统与绩效评估

**目标**：吃透 qlib 回测配置，能独立调参与解读报告。

**学习内容**：

- `port_analysis_config`：executor / backtest / strategy 三段式
- 交易成本与约束：`trade_unit=100`、`limit_threshold=0.099`、`deal_price`
- 绩效指标：年化收益、最大回撤、IR、换手率、超额收益
- `TopkDropoutStrategy`：topk/n_drop 的含义与调参手感

**实践**：

1. 修改 topk（10/30/50）、n_drop（1/3/5）做网格观察
2. 对比 CSI300 / CSI500 股票池下的回测差异
3. 解读并复述每张报告图的含义

**验收**：能用一页纸说清"从模型预测分数到最终回测报告"的完整链路；理解涨跌停/停牌如何被 qlib 处理

### 第 5 周：滚动训练与交叉验证

**目标**：让模型适应市场风格切换，掌握严谨的时间序列评估。

**学习内容**：

- `ROLL` / `ROLL_EXPANDING` 调仓日历；`Mask` / `Processor` 与切分的关系
- `QLearning...`（可选）之外的实用做法：`RollingGen`、`nested decision`（嵌套决策框架）
- 交叉验证的正确姿势：**时间序列 CV**（绝不能随机打乱），概念漂移问题

**实践**：

1. 用 `RollingGen` 实现滚动训练 + 验证 + 预测
2. 对比"一次性训练" vs "滚动训练"的样本外 IC
3. 观察不同市场阶段（牛市/熊市/震荡）的模型表现差异

**验收**：能独立搭建滚动训练 pipeline，并解释"为什么金融数据不能用普通 K-Fold"

### 第 6 周：接入自有 A 股数据（上）—— dump_bin.py

**目标**：把任何 CSV/Parquet 数据转成 qlib 的 `.bin` 格式。

**学习内容**：

- qlib `.bin` 目录结构：`calendars/day.txt`、`instruments/all.txt`、`features/<code>/<field>.bin`
- `scripts/dump_bin.py dump_all`：`--date_field_name`、`--symbol_field_name`、`--include_fields`
- 数据约定：`factor` 列（复权因子）必带；停牌日 OHLCV 置 NaN；列名小写

**实践**：

1. 用官方 `scripts/data_collector/yahoo/collector.py` 抓数并 dump，熟悉 CSV 格式约定
2. 准备一份自己的 A 股日线 CSV（来源不限：tushare/akshare/自建数据库），按规范 dump 到 `~/.qlib/my_cn_data`
3. `qlib.init` 指向新数据目录，跑通 Alpha158 + LightGBM

**验收**：`check_data_health.py` 通过；能解释 `$close`（已复权）与 `$close/$factor`（真实价）的区别

**数据转换命令**：

```bash
python scripts/dump_bin.py dump_all \
  --data_path ~/.qlib/csv_data/my_cn \
  --qlib_dir ~/.qlib/qlib_data/my_cn_data \
  --include_fields open,close,high,low,volume,factor \
  --date_field_name date --symbol_field_name symbol
# 健康检查
python scripts/check_data_health.py check_data --qlib_dir ~/.qlib/qlib_data/my_cn_data
```

### 第 7 周：接入自有 A 股数据（下）—— 自定义特征与标签

**目标**：把基本面/资金面等 OHLCV 之外的数据纳入模型。

**学习内容**：

- 在 CSV 中追加 `pe`、`pb`、`turnover`、`money` 等字段一起 dump，再经表达式引擎引用（`$pe`、`$turnover`）
- 自定义 DataHandler：继承 `Alpha158` 添加字段、或从零写 `DataHandlerLP`
- `instruments` 自定义股票池（`instruments/all.txt` + 指数成分文件），换仓日历

**实践**：

1. dump 一份含 PE/PB/换手率的 A 股数据，构造"估值+动量"混合因子集
2. 自定义 handler 中用表达式生成新因子（如 `Mean($turnover,20)`）
3. 定义自己的股票池（如中证 800 或自选池），完成一次全流程

**验收**：能完整复述"新数据 → CSV → dump_bin → 表达式引用 → 因子 → 模型"的扩展路径

### 第 8 周：组合构建与策略定制

**目标**：从"模型给分"到"组合落地"，控制风格暴露。

**学习内容**：

- 内置策略族：`TopkDropoutStrategy`、`WeightStrategyBase`（配 `optimizer` 做权重优化）
- 风险模型：`RiskModel`（结构化风险模型/统计风险模型），组合优化器
- 行业/市值中性化的常见做法（Processor 或因子预处理阶段实现）

**实践**：

1. 同一模型分数，分别用 TopkDropout 与 WeightStrategy 回测，对比差异
2. 加入风险模型跑组合优化版回测
3. 对因子做行业中性化前后对比

**验收**：能说清"分数 → 组合权重 → 订单 → 成交"的完整链路；能解释中性化对 IC 与回撤的影响

### 第 9 周：项目实战——完整选股系统

**目标**：综合前 8 周内容，搭一个完整的 A 股选股研究系统。

**实践（建议分支做）**：

1. **选股框架**：自有数据 → Alpha158+自定义因子 → LGBM 训练 → 滚动预测 → TopkDropout 回测
2. **研究扩展（选做）**：rdAgent 自动因子挖掘（微软官方 LLM 方案）；或复现一篇 qlib benchmark 中的论文模型（如 HIST、DoubleEnsemble）
3. **工程化（选做）**：把 workflow 写成参数化脚本（python -m 或 yaml 参数覆盖），支持一键复现

**验收**：产出一份研究报告（模型、因子、IC、回测、结论），代码可一键复现

### 第 10 周：高频数据入门（选修）

**目标**：了解 qlib 高频能力，为后续深入打基础。

**学习内容**：

- qlib 高频数据格式与 `1min` 数据下载；高频因子（如 `EPS`、VP 系列）
- nested decision execution（嵌套决策：日级策略 + 分钟级执行）
- 高频回测的性能与缓存问题

**实践**：

1. 下载 1min 数据，跑通 `examples/highfreq` 示例
2. 计算一个简单高频因子并可视化

**验收**：能说清高频与低频 qlib 用法的异同

### 第 11 周：模型进阶（选修）

**目标**：接触 qlib 中更前沿的模型范式。

**学习内容**：

- 时序深度模型：TFT、TCN、Transformer/Localformer、ADARNN、TRA 等
- 概念漂移应对：DDG-DA（meta-learning 框架）
- 强化学习框架（qlib RL 部分）

**实践**：

1. 任选 1~2 个深度模型在 A 股数据上复现 benchmark 结果
2. 与 LightGBM baseline 对比，写对比小结（很多深度模型提升有限，能解释原因更重要）

**验收**：形成自己的"模型选型心得"笔记

### 第 12 周：总结与下一步

**目标**：沉淀方法论，规划后续方向。

**实践**：

1. 整理 12 周全部代码与笔记，形成个人 qlib 脚手架
2. 输出总结文档：《A 股 AI 选股研究流程规范（基于 qlib）》
3. 规划下一步：实盘模拟对接、因子库持续积累、RD-Agent 自动化研究

**完成标准**：

- 能独立完成"数据接入 → 特征工程 → 模型训练 → 滚动回测 → 报告产出"全流程
- 能解释每个环节的设计动机与常见坑（未来函数、幸存者偏差、复权处理、风格漂移）
- 拥有一套可复现、可迭代的研究脚手架

---

## 四、常见坑清单（A 股特有）

1. **未来函数**：标签必须用 T+1 之后的价格；特征只能用 T 日及以前数据
2. **复权与真实价**：qlib 默认存的是复权价，`$close/$factor` 才是真实价；做涨跌停判断、价格约束时务必注意
3. **停牌与涨跌停**：qlib 以 NaN 处理停牌；`limit_threshold=0.099` 模拟 ±10% 涨跌停（注意 20cm 创业板/科创板需另行处理）
4. **幸存者偏差**：退市股缺失会让回测虚高，自建数据时尽量包含退市股
5. **Yahoo 数据源质量**：官方 collector 依赖 Yahoo，国内网络不稳，A 股数据质量一般——第 6 周后强烈建议换 akshare/tushare 自建
6. **qlib 数据更新**：官方数据集有截止日期，别直接拿"过期数据 + 未滚动训练"的模型做实盘决策
7. **版本兼容**：pyqlib 对 numpy/pandas 版本敏感，报错先查 issues，固定依赖版本

---

## 五、每周小结模板

```markdown
## 第 N 周小结
- 本周目标：
- 实际完成：
- 代码/数据产出：
- 踩坑与解决：
- 下周计划：
```

## 六、进度追踪

| 周 | 主题 | 状态 |
|---|---|---|
| 1 | 环境安装与快速体验 | ⬜ 未开始 |
| 2 | Data Handler 与 Alpha158 | ⬜ 未开始 |
| 3 | 模型训练与预测 | ⬜ 未开始 |
| 4 | 回测与绩效评估 | ⬜ 未开始 |
| 5 | 滚动训练与交叉验证 | ⬜ 未开始 |
| 6 | 自有数据接入（dump_bin） | ⬜ 未开始 |
| 7 | 自有数据接入（自定义特征/股票池） | ⬜ 未开始 |
| 8 | 组合构建与策略定制 | ⬜ 未开始 |
| 9 | 项目实战 | ⬜ 未开始 |
| 10 | 高频数据（选修） | ⬜ 未开始 |
| 11 | 模型进阶（选修） | ⬜ 未开始 |
| 12 | 总结沉淀 | ⬜ 未开始 |
