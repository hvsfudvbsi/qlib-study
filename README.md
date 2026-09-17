# Qlib Study（A 股方向）

一个以微软 [Qlib](https://github.com/microsoft/qlib) 为核心、面向 **A 股 AI 选股** 的学习项目。目标不是调 API，而是吃透"数据 → 特征 → 模型 → 组合 → 回测 → 报告"每个环节的设计动机，最终沉淀一套可复现的个人研究脚手架。

## 学习路径

| 阶段 | 周次 | 重点 |
|---|---|---|
| M1 跑通官方流程 | 第 1~3 周 | 安装、`cn_data`、Alpha158 + LightGBM、`qrun` 全流程 |
| M2 吃透四大组件 | 第 4~9 周 | 回测与指标、滚动训练、自有 A 股数据接入、组合策略 |
| M3 毕业项目 | 第 10~12 周 | 完整选股系统、高频/深度模型选修、方法论沉淀 |

完整的周计划、练习、验收标准与 A 股常见坑见 [`STUDY_PLAN.md`](STUDY_PLAN.md)。

## 环境要求

- Python 3.10（conda 建议独立环境 `qlib`）
- pyqlib（`pip install pyqlib`；版本敏感，报错先查官方 issues）
- Qlib 官方 A 股数据（约 400MB，`scripts/get_data.py` 下载）

## 快速开始

```bash
# 1. 环境
conda create -n qlib python=3.10 -y
conda activate qlib
pip install pyqlib jupyter

# 2. 下载官方 A 股数据（cn_data）
python scripts/get_data.py qlib_data --target_dir ~/.qlib/qlib_data/cn_data --region cn

# 3. 跑通官方入门 notebook（第 1 周任务）
jupyter notebook examples/tutorial/workflow_by_code.ipynb

# 4. qrun 配置驱动全流程（第 3 周任务）
qrun examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml
```

## 目录结构

```
qlib-study/
├── STUDY_PLAN.md        12 周完整学习计划（含验收标准与常见坑）
├── notes/               每周小结与踩坑记录（学习中逐步补充）
├── notebooks/           练习用 notebook（学习中逐步补充）
├── workflows/           自定义 qrun yaml 配置（学习中逐步补充）
└── data/                自备 CSV 数据与转换脚本（学习中逐步补充）
```

## 学习规则

1. 每周产出一次可运行的成果（notebook / qrun 结果 / 转换脚本），不复述文档。
2. 所有实验记录数据版本与随机种子，保证可复现。
3. 指标优先看 IC / Rank IC 的稳定性，其次才是回测收益。
4. 遵守"标签无未来函数、特征无未来数据"的硬约束。
5. 每完成一周，更新 `STUDY_PLAN.md` 的进度表并做一次提交。
