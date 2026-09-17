# 第 1 周踩坑笔记：环境搭建与 workflow_by_code 全流程

> 执行日期：2026-09-17 ｜ 环境：Ubuntu VM / 4 核 / 3.8G 内存 / 系统Python 3.12.3
> 结果：✅ notebook 全流程跑通（0 个 Traceback），IC≈0.05，含成本年化超额 +17.4%

## 结论先行

**pyqlib 0.9.7 可以在 Python 3.12 上直接用**，不需要 conda。但 pip 默认解析出的新版本依赖（pandas 3.x、plotly 7.x）必炸，必须手动钉版本。完整可用组合：

```
pyqlib==0.9.7
numpy==2.0.2        # 不能 1.x（见坑 3），不能最新 2.5（见坑 2 推断）
pandas==2.2.3       # 不能 3.x（见坑 2）
plotly==5.24.1      # 不能 7.x（见坑 5）
statsmodels         # pyqlib 没声明依赖，报告模块需要（见坑 6）
mlflow（随 pyqlib 安装，需环境变量，见坑 4）
```

## 坑 1：pyqlib 版本与 wheel 支持

- PyPI 最新 0.9.7（0.9.3~0.9.7 均可装），官方 classifiers 写支持 3.8–3.12
- 实测存在 `pyqlib-0.9.7-cp312-cp312-manylinux2014_x86_64` wheel，Linux + 3.12 直接 `pip install` 成功
- 查询方法：`curl -s https://pypi.org/pypi/pyqlib/json | jq ...` 看 `urls[].filename`

## 坑 2：pandas 3.x 直接不兼容（最大的坑）

裸 `pip install pyqlib` 会拉到 **pandas 3.0.5**。qlib 0.9.7 发布早于 pandas 3.0，API 不兼容。症状未细查——因为我先冒烟测试就发现版本不对，直接降级处理。

**解法**：`pip install "pandas==2.2.3"`

## 坑 3：numpy 不能盲目降 1.x

习惯性想钉 `numpy==1.26.4`（很多老教程推荐），结果环境里 pip 预装的 scipy 1.18 / contourpy 1.4 / cvxpy 1.9 都要求 `numpy>=2.0`，导致：

```
AttributeError: module 'numpy' has no attribute 'long'
```

**教训**：降级一个包之前，先看环境里其他包的约束。**解法**：`numpy==2.0.2`（满足 scipy>=2.0 要求，又比 2.5 老得多，兼容 qlib）。

## 坑 4：新版 mlflow 拒绝文件存储后端

qlib 的实验跟踪 `R`（Recorder）默认用文件后端 `./mlruns`，但新版 mlflow 会抛：

```
MlflowException: The filesystem tracking backend ... is in maintenance mode ...
set `MLFLOW_ALLOW_FILE_STORE=true` to opt out
```

**解法**：运行时加环境变量 `MLFLOW_ALLOW_FILE_STORE=true`。

**副产品坑**：mlflow 7.x 把相对路径解析出 `runs/week01/root/mywork/...` 嵌套目录（当前工作目录被按字面拼进 artifact_uri）。发现后 `rm -rf` 清掉即可，不影响运行。

## 坑 5：plotly 7.x 移除了 create_distplot

qlib 0.9.7 的报告模块 `qlib/contrib/report/graph.py` 里 `from plotly.figure_factory import create_distplot`，而 plotly 7.x 已删除该函数：

```
ImportError: cannot import name 'create_distplot' from 'plotly.figure_factory'
```

**解法**：`pip install "plotly==5.24.1"`。

## 坑 6：pyqlib 依赖声明不全

官方入门 notebook 还需要手动补装：`plotly`、`statsmodels`（以及画图后端相关的包）。否则训练回测都能过，死在最后的报告 cell。

**预防措施**：正式跑之前，先本地验证一遍全链路 import：

```bash
python -c "
import qlib.contrib.report.analysis_model
import qlib.contrib.report.analysis_position
import qlib.contrib.strategy.signal_strategy
import qlib.contrib.model.gbdt
import qlib.contrib.evaluate
"
```

import 时会看到 `CatBoostModel/XGBModel/PyTorch models are skipped` 提示，这是可选模型，不影响。

## 坑 7：notebook 位置变了（文档滞后）

`examples/tutorial/` 目录下现在只有 `detailed_workflow.ipynb`；官方 README 里说的 `workflow_by_code.ipynb` 实际在 **`examples/workflow_by_code.ipynb`**。写计划时引用了老路径，执行时发现。

## 坑 8：无头执行 notebook 的三个调整

1. **注释 `import matplotlib`**：qlib 的 report 模块 import matplotlib 后调用 pyplot API，`MPLBACKEND=Agg` 也拦不住个别调用，最稳是注释掉（笔记本交互使用不受影响）
2. **`OMP_NUM_THREADS=1`**：3.8G 内存小机器上限制 LightGBM 线程数，避免内存翻倍
3. **加 swap**：`fallocate -l 5G /swapfile && mkswap && swapon`，回测阶段实测用到了 swap

数据初始化耗时约 60s，LGBM 训练+回测+报告全程约 7 分钟。

## 数据事实

- `scripts/get_data.py qlib_data --region cn` 下载 521M，**日频数据覆盖 1999-11-10 ~ 2020-09-25**（官网 zip 包 `cn_1d_latest` 就到这，并非"最新"）
- notebook 训练窗口 2008–2020、回测窗口 2017–2020.08，与数据范围兼容，可跑
- 下载后记得删掉数据目录里残留的 zip 包
- 目录结构：`calendars/day.txt`（交易日历）、`instruments/csi300.txt`（股票池）、`features/<代码>/<字段>.bin`

## 执行结果

| 指标 | 数值 |
|---|---|
| IC（868 个交易日） | **0.0499** |
| ICIR | 0.4012 |
| Rank IC | 0.0515 |
| Rank ICIR | 0.4196 |
| 超额年化（含成本，TopkDropout topk=50） | **+17.37%** |
| 超额 IR（含成本） | 1.97 |
| 超额最大回撤（含成本） | -5.73% |
| 基准沪深300 年化/回撤 | +11.36% / -37.05% |

感受：IC≈0.05 的 LGBM+Alpha158 就能在 2017–2020 的 CSI300 上做出稳定正超额，IR 接近 2——这就是量化的基本盘。但这是官方清洗过的数据+没有滚动训练，含过拟合水分。

## 运行期警告（留待后续验证）

```
WARNING - $close field data contains nan.
WARNING - factor.day.bin file not exists or factor contains `nan`. Order using adjusted_price.
WARNING - trade unit 100 is not supported in adjusted_price mode.
```

官方 cn_data 竟没有 `factor.day.bin`（或含 NaN），回测退化为"复权价模式"，`trade_unit=100`（一手 100 股）约束失效。对指标影响未知——**计划第 4 周回测专题时验证：检查 features 目录是否有 factor.bin，并评估对成交模拟的影响**。

## 复现命令

```bash
# 环境（qlib-study/.venv 已配好可跳过）
cd /root/mywork/qlib-study
python3 -m venv .venv
.venv/bin/pip install pyqlib nbformat nbclient ipykernel
.venv/bin/pip install "numpy==2.0.2" "pandas==2.2.3" "plotly==5.24.1" statsmodels

# 数据
git clone --depth 1 https://github.com/microsoft/qlib.git /root/mywork/qlib-src
/root/mywork/qlib-study/.venv/bin/python /root/mywork/qlib-src/scripts/get_data.py \
    qlib_data --target_dir ~/.qlib/qlib_data/cn_data --region cn

# 无头执行（runs/week01/run_nb.py 是 notebook 转出的脚本）
cd runs/week01
setsid nohup env MLFLOW_ALLOW_FILE_STORE=true OMP_NUM_THREADS=1 MPLBACKEND=Agg \
    ../../.venv/bin/python run_nb.py > run.log 2>&1 &
```

## 实际可行命令（修正后）

```bash
# notebook 正确路径
jupyter notebook /root/mywork/qlib-src/examples/workflow_by_code.ipynb

# qrun 配置（第 3 周任务）
qrun /root/mywork/qlib-src/examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml
```
