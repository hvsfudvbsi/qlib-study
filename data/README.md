# data：自建 A 股数据（akshare → qlib）

本目录提供「akshare 拉取 A 股日线 → qlib dump_bin 规范 CSV → 转 .bin」的完整链路（对应 STUDY_PLAN 第 6~7 周任务的提前落地，已在 2026-09-17 全流程实测通过）。

## 文件

- `export_akshare_csv.py`：导出脚本（每股票一个 CSV，文件名即代码，列：date, symbol, open, close, high, low, volume, factor）
- `csv_cn/`：导出的 CSV（已 gitignore，不入库）

## 快速开始

```bash
# 0. 依赖（关键：--no-deps，避免 akshare 把第 1 周钉好的 numpy/pandas 升级掉）
.venv/bin/pip install --no-deps akshare py-mini-racer tabulate xlrd curl_cffi

# 1. 导出 CSV（默认腾讯源；3 只股票约 40 秒）
cd data
../.venv/bin/python export_akshare_csv.py --symbols sh600000 sz000001 sh600519 \
    --start 20240101 --end 20250917 --out-dir csv_cn --source tx

# 2. 转 qlib .bin（dump_bin 在官方仓库，路径见 README 快速开始）
../.venv/bin/python /root/mywork/qlib-src/scripts/dump_bin.py dump_all \
    --data_path csv_cn --qlib_dir ~/.qlib/qlib_data/my_cn_data \
    --include_fields open,close,high,low,volume,factor \
    --date_field_name date --symbol_field_name symbol

# 3. 健康检查
../.venv/bin/python /root/mywork/qlib-src/scripts/check_data_health.py check_data \
    --qlib_dir ~/.qlib/qlib_data/my_cn_data

# 4. qlib 读取冒烟
../.venv/bin/python -c "
import qlib; qlib.init(provider_uri='~/.qlib/qlib_data/my_cn_data', region='cn')
from qlib.data import D
print(D.features(['SH600000'], ['\$close','\$factor','\$close/\$factor'], start_time='2025-09-16', end_time='2025-09-17'))
"
```

## 数据源选择（实测结论）

| 源 | 接口 | 复权方式 | factor 质量 | 限流 |
|---|---|---|---|---|
| tx（默认） | `stock_zh_a_hist_tx` | **等差**（qfq=现价-累计分红送转） | factor=qfq/raw 逐日微漂，qlib 代数关系仍成立，段内收益率有微小失真 | 宽松 |
| em | `stock_zh_a_hist` | **等比**（qfq=现价×累计因子） | 分段恒定，标准 | **极严**（本 VM 上持续 ConnectionError，需换 IP 或冷却后用） |

生产环境建议 tushare pro（`pro_bar(adj="qf")`，等比复权且提供 `adj_factor` 原始字段）或券商数据。

## 复权口径说明（重要）

qlib 约定：`$close/$factor` = 真实价，`factor = 复权价/真实价`。本脚本直接存 qfq 价并令 `factor = qfq/raw` 满足该代数关系。

- **tx 等差复权的失真**：等差下 `qfq/raw` 不是常数，跨除权日计算的收益率与真实复权收益率存在微小偏差（分红比例越大偏差越大）
- **已知缺陷**：本脚本未处理停牌日补齐（停牌日直接缺行）；后续做滚动训练前应补齐交易日历并置 NaN（qlib dump 约定）
- **已知缺陷**：未含退市股（幸存者偏差），构建严肃回测时需专门处理

## 实测记录（2026-09-17）

- 3 只股票（浦发/平安/茅台）各 416 行，2024-01-02 ~ 2025-09-17
- dump_bin → `features/{sh600000,sh600519,sz000001}/{close,open,high,low,volume,factor}.day.bin`
- `check_data_health` 仅 1 条提示：SZ000001 在 2024-02-21 成交量跳变 3.5 倍（真实行情事件，非数据错误）
- qlib 冒烟：`$close/$factor` 精确还原真实价（浦发 12.96 / 茅台 1493.00），日历 416 天，`instruments/all.txt` 格式正确
