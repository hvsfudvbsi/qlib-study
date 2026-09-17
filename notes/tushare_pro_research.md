# 调研：用 tushare pro 的 adj_factor 构建标准 qlib 数据源

> 调研日期：2026-09-17 ｜ 结论先行：**值得做**。`adj_factor` 是标准等比复权因子，与 qlib `factor` 语义精确同构（已从 tushare 源码核验）；全市场 5 年日线+因子约 500 次请求可 1 分钟内拉完。唯一门槛是 **2000 积分**（约 ¥200/年 或社区贡献获得）。

## 一、为什么换源（三源对比）

| 维度 | tx 腾讯（现默认） | em 东财 | **ts tushare pro** |
|---|---|---|---|
| 复权方式 | **等差** qfq（factor=qfq/raw 逐日漂） | 等比 qfq | **官方 adj_factor，等比，分段恒定** |
| factor 质量 | 近似（段内收益率微失真） | 较好（需 qfq/raw 自算） | **标准，无需任何计算** |
| 限流 | 宽松 | **极严（本 VM 实测不可用）** | 明确可控（按分钟计次，可编程退避） |
| 停牌日 | 无数据行 | 无数据行 | **同无数据（需补齐，方案见 §5）** |
| 退市股 | 无 | 无 | **有（stock_basic list_status='D'）→ 可消除幸存者偏差** |
| 扩展字段 | turnover/amount | turnover/amount | **pe/pb/dv_ratio/total_mv 等每日指标** |
| 门槛 | 无 | 无 | 2000 积分 + token |

## 二、接口清单（官方文档已逐个核验）

| 接口 | 用途 | 关键限制 |
|---|---|---|
| `daily`（doc_id=27） | 不复权日线 OHLCV | 500 次/分钟×6000 行/次；**官方建议按 trade_date 循环拉全市场，不要按股票循环**；`pre_close` 是除权价；**停牌日无数据** |
| `adj_factor`（doc_id=28） | 等比复权因子 | **2000 积分起，5000 以上可高频**；盘前 9:15~20 更新当日；单股全史或单日全市场均可 |
| `trade_cal`（doc_id=26） | 交易日历 | 2000 积分；`is_open='1'` 过滤交易日 |
| `stock_basic`（doc_id=25） | 股票列表 | 一次 6000 行；**`list_status='D'` 可拉退市股**；50 次/分钟 |
| `index_daily`（doc_id=95） | 指数日线（benchmark） | 2000 积分；沪深300=000300.SH |
| `daily_basic`（doc_id=32） | 每日指标 | 2000 积分；**pe/pb/换手率/总市值** 等，正好对接 qlib 表达式引擎扩展字段（STUDY_PLAN 第 7 周） |
| `pro_bar`（doc_id=109） | 通用行情（qfq/hfq 现算） | **集成接口，不能 HTTP 调用，需 SDK**；另：本 VM 实测 `pip install tushare` 后 import 即挂（curl_cffi 构建失败），且 pro_bar 内部也要调 adj_factor，**不如直接用 daily + adj_factor 自组合** |

**拉数成本估算**（全市场 5 年日频）：daily 按日循环 ≈1220 次 + adj_factor 按日循环 ≈1220 次（或按股循环 5400 次，不划算）→ 约 5 分钟（含限流退避）。单次实验取 3~5 年、300~500 只股票池：**daily/adj_factor 各按日循环 ≈250~500 次，1 分钟内完成**。

## 三、复权语义核验（从 tushare 源码 `tushare/pro/data_pro.py` 的 pro_bar 实现提取）

```python
PRICE_COLS = ['open', 'close', 'high', 'low', 'pre_close']
fcts = api.adj_factor(...)[['trade_date', 'adj_factor']]
data = df.merge(fcts, ...)          # daily 与 adj_factor 按 trade_date 对齐
data['adj_factor'] = data['adj_factor'].fillna(method='bfill')
for col in PRICE_COLS:
    if adj == 'hfq':
        data[col] = data[col] * data['adj_factor']                      # 后复权
    else:  # qfq
        data[col] = data[col] * data['adj_factor'] / float(fcts['adj_factor'][0])  # 除以请求区间首日因子
```

**推导**：
- `hfq_price = raw_price × adj_factor` ⟹ **`adj_factor ≡ hfq_price / raw_price`**
- qlib 约定（官方文档 Data Preparation）：`factor = adjusted_price / original_price`，存储后复权价时 `factor = adj_factor`

⟹ **两者定义精确同构**。映射方案（标准等比、零近似）：

```text
qlib CSV 列      = tushare 来源
close/open/...   = daily.raw_price × adj_factor          （= hfq 价）
factor           = adj_factor                            （原值直用）
$close/$factor   = daily.raw_price                        （真实价 ✓）
volume           = daily.vol × 100                        （tushare 单位是手 → 股）
跨日收益率       = hfq 比价 = adj_factor(t)/adj_factor(t-1) × raw 比价 → 标准等比复权收益 ✓
```

另注意 `data['adj_factor'].fillna(method='bfill')`——tushare 自己也在处理因子尾部缺失，我们的导出脚本对 factor 缺失必须显式报错（现有 build_csv 已做 `(df['factor']<=0) or isna` 校验，保留）。

## 四、积分获取

- **门槛**：`adj_factor`/`trade_cal`/`stock_basic`/`index_daily`/`daily_basic` 均 2000 积分起（`daily` 本身 120 分即可，但没有 adj_factor 无法构建标准复权）
- **获取**：官网充值（约 ¥200/年 档）或社区贡献方式（学生认证、开源贡献等，以官网积分页为准）
- **策略**：先按 §7 PoC 流程注册→充值→token 进环境变量 `TUSHARE_TOKEN`→跑通 → 提交正式 PR

## 五、与现有 export_akshare_csv.py 的集成设计

新增 `--source ts`，复用现有 build_csv 的后半段（排序、校验、NaN 补齐、instruments 生成全部不动）：

```python
def fetch_ts(symbol: str, code: str, start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """tushare pro：返回 (raw_df, hfq_df)，hfq = raw × adj_factor。
    代码映射：SH600000 -> 600000.SH；指数 SH000001 -> 000001.SH（复用现有指数路径，
    benchmark 直接走 index_daily，天然不复权、factor=1）。"""
    raw = pro.daily(ts_code=ts_code, start_date=start, end_date=end)
    fct = pro.adj_factor(ts_code=ts_code, start_date=start, end_date=end)
    # 手数→股、因子缺失校验，然后 hfq = raw × adj_factor
    ...
```

**设计要点**：
1. **保持 `fetch_with_retry` 的返回契约不变**（raw/qfq 双 DataFrame），ts 源返回 (raw, raw×factor)——build_csv 里 `factor = close_qfq/close_raw` 会自然等于 adj_factor，代数自洽
2. **volume 单位**：tushare `vol` 是手，×100 转股（与 em 源同路径）
3. **限流退避**：tushare 超限返回具体错误码，`fetch_with_retry` 的指数退避天然适配；按日循环拉全市场时把 sleep 控制在 60000ms/500次 ≈ 120ms/次
4. **停牌日**：tushare 无数据行 → 现有 `backfill_suspend_days` 直接兜住（用 trade_cal 或日期并集），**无需新代码**
5. **退市股**（可选增强）：`stock_basic(list_status='D')` 拿到 ts_code/list_date/delist_date，导出时对退市后区间不补 NaN，instruments 的 END 用退市日——**消除幸存者偏差的关键**（现有 tx/em 源做不到）
6. **扩展字段**（第 7 周衔接）：daily_basic 的 pe/pb/turnover_rate/dv_ratio 加进 `--include_fields` 一起 dump，表达式引擎直接 `$pe`/`$pb` 引用
7. **代码映射坑**：qlib 风格 `SH600000` ↔ tushare `600000.SH`；上证指数 `SH000001` ↔ `000001.SH`（`stock_basic` 里没有指数，`index_basic` 另有接口）；北交所 `BJ` ↔ tushare 无 `.BJ` 后缀（用 `.NQ`？——**待 PoC 核验**，先行 issue 标注）
8. **凭据纪律**：token 走 `TUSHARE_TOKEN` 环境变量或 `~/.tushare.token`（gitignore），绝不入库

## 六、风险与未尽事项

| 风险 | 等级 | 缓解 |
|---|---|---|
| 本 VM 无法 pip install tushare（curl_cffi 编译失败，week01 已实测） | 中 | PoC 时 `pip install tushare --no-deps` + 手工补依赖，或直接 `pro.query('daily', ...)` 走 requests HTTP（tushare pro 的本质是 HTTP API，token 即可，不依赖 SDK） |
| adj_factor 尾部/停牌日缺失 | 低 | 校验 + bfill 对齐（tushare 官方同款做法） |
| 2000 积分未获得前一切阻塞 | — | 唯一硬门槛；充值或社区贡献 |
| 北交所代码后缀映射未核验 | 低 | PoC 时验证，失败先排除 BJ 股票 |

## 七、PoC 验收清单（拿到 token 后 30 分钟内可完成）

1. `pip install tushare --no-deps`，import 通过；或 requests 直连 `http://api.tushare.pro`
2. `pro.adj_factor(ts_code='000001.SZ')` 拉全史 → 验证因子分段恒定、除权日跳变次数与东财一致
3. 3 只测试股（浦发/平安/茅台）走 `--source ts` 全流程 → dump → `check_data_health` → 与 tx 源导出比对 `$close/$factor` 真实价、跨日收益率（偏差应 <1e-6）
4. 上证指数 `000001.SH` index_daily → benchmark 导出（factor=1.0）
5. qlib `D.features` 抽查 + `runs/selfdata/run_e2e.py` 重跑（替换 provider_uri 即可）
6. 全部通过 → 提交 `--source ts` PR，data/README.md 更新三源对比表
