#!/usr/bin/env python3
"""akshare A 股日线导出 → qlib dump_bin 规范 CSV。

输出规范（对应 scripts/dump_bin.py dump_all 的要求，见 qlib 官方文档 Data Preparation）：
- 每只股票一个 CSV，文件名即证券代码（如 SH600000.csv），首列 date，小写列名
- 列：date, symbol, open, high, low, close, volume, factor[, amount, turnover]
- open/close/high/low/volume 为**前复权价**，factor = qfq/raw，使 $close/$factor == 真实价

数据源（--source）：
- tx（默认）腾讯 stock_zh_a_hist_tx：限流宽松；qfq 为等差复权，
  factor=qfq/raw 逐日微漂，qlib 代数关系仍成立，但段内收益率有微小失真
- em 东财 stock_zh_a_hist：等比复权、factor 分段恒定（更标准），但限流严格；
  在被限流的 IP 上会 ConnectionError/超时，可改用 tx 或稍后再试

复权口径提示：严格无放漏的复权需送转/分红明细自行构建因子，
生产环境建议 tushare pro（pro_bar adj="qf"）或券商数据，见 data/README.md。

用法：
    python export_akshare_csv.py --symbols sh600000 sz000001 sh600519 \
        --start 20240101 --end 20250917 --out-dir csv_cn
    # 导出后转 qlib .bin（详见 data/README.md）
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

RETRY_ATTEMPTS = 3
RETRY_BACKOFF = (5, 15, 30)  # 秒，指数退避
COLS_OUT = ["date", "symbol", "open", "close", "high", "low", "volume", "factor"]
COLS_OUT_EXTRA = COLS_OUT + ["amount", "turnover"]


def norm_symbol(sym: str) -> tuple[str, str]:
    """sh600000 -> ('SH600000', '600000')；兼容 600000（自动识别交易所）。"""
    sym = sym.strip().lower()
    if sym.isdigit():
        code = sym
        prefix = "sh" if code[0] == "6" else ("bj" if code[0] in ("4", "8") else "sz")
        sym = prefix + code
    exchange, code = sym[:2].upper(), sym[2:]
    if exchange not in ("SH", "SZ", "BJ") or not code.isdigit() or len(code) != 6:
        raise ValueError(f"无法识别的代码: {sym!r}（支持 sh600000 / sz000001 / 600000 形式）")
    return exchange + code, code


def fetch_tx(code: str, start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """腾讯源：返回 (不复权 df, qfq df)，英文列名。volume 单位=股。"""
    import akshare as ak

    sym = ("sh" if code[0] == "6" else "bj" if code[0] in ("48") else "sz") + code
    raw = ak.stock_zh_a_hist_tx(symbol=sym, start_date=start, end_date=end, adjust="")
    time.sleep(2)
    qfq = ak.stock_zh_a_hist_tx(symbol=sym, start_date=start, end_date=end, adjust="qfq")
    return raw, qfq


def fetch_em(code: str, start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """东财源：返回 (不复权 df, qfq df)，中文列名。volume 单位=手。"""
    import akshare as ak

    kw = dict(symbol=code, period="daily", start_date=start, end_date=end)
    raw = ak.stock_zh_a_hist(adjust="", **kw)
    time.sleep(2)
    qfq = ak.stock_zh_a_hist(adjust="qfq", **kw)
    return raw, qfq


def fetch_with_retry(code: str, start: str, end: str, source: str):
    fn = {"tx": fetch_tx, "em": fetch_em}[source]
    last: Exception | None = None
    for attempt, backoff in enumerate(RETRY_BACKOFF, 1):
        try:
            return fn(code, start, end)
        except Exception as e:  # noqa: BLE001 网络类异常统一重试
            last = e
            print(f"  [retry {attempt}/{RETRY_ATTEMPTS}] {code} {type(e).__name__}: {str(e)[:60]}; backoff {backoff}s")
            time.sleep(backoff)
    raise RuntimeError(f"{code} 拉取失败（{source} 源重试 {RETRY_ATTEMPTS} 次）") from last


def build_csv(raw: pd.DataFrame, qfq: pd.DataFrame, symbol: str, source: str) -> pd.DataFrame:
    """合并不复权与 qfq 数据，产出 dump_bin 规范 DataFrame。"""
    is_em = source == "em"
    d, o, c, h, l, v = ("日期", "开盘", "收盘", "最高", "最低", "成交量") if is_em else \
                       ("date", "open", "close", "high", "low", "volume")

    raw = raw[[d, o, c, h, l, v]].copy()
    qfq = qfq[[d, o, c, h, l, v]].copy()
    if len(raw) != len(qfq):
        print(f"  [warn] {symbol} 不复权 {len(raw)} 行 != qfq {len(qfq)} 行，按日期对齐取交集")
    df = raw.merge(qfq, on=d, suffixes=("_raw", "_qfq"), how="inner")
    if df.empty:
        raise RuntimeError(f"{symbol} 合并后无数据")

    df = df.rename(columns={d: "date"})
    # qlib 口径：OHLCV 存前复权价，factor = qfq/raw，$close/$factor == 真实价
    for col in ("open", "close", "high", "low"):
        df[col] = df[f"{col}_qfq"]
    df["volume"] = df[f"{v}_qfq"] if is_em else df["volume_qfq"]
    if is_em:  # 东财 volume 单位是手，转成股
        df["volume"] = df["volume"] * 100.0

    df["factor"] = df["close_qfq"] / df["close_raw"]
    if (df["factor"] <= 0).any() or df["factor"].isna().any():
        raise RuntimeError(f"{symbol} factor 存在非正值/缺失，数据异常")

    if is_em:
        seg = df["factor"].round(6).diff().abs().sum()
        if seg > 1e-3:  # 等比复权下 factor 应分段恒定，漂移大说明有数据问题
            print(f"  [warn] {symbol} em 源 factor 累计漂移 {seg:.4f}（预期仅除权日跳变），请人工检查")
    else:
        print(f"  [info] {symbol} tx 源为等差复权，factor 逐日微漂属预期（累计漂移 {df['factor'].diff().abs().sum():.4f}）")

    df["symbol"] = symbol
    for col in ("open", "close", "high", "low", "volume", "factor"):
        df[col] = pd.to_numeric(df[col], errors="coerce").round(6)
    return df[COLS_OUT]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", nargs="+", required=True,
                    help="证券代码列表：sh600000 sz000001 或 600000 均可")
    ap.add_argument("--start", required=True, help="开始日期 YYYYMMDD")
    ap.add_argument("--end", required=True, help="结束日期 YYYYMMDD")
    ap.add_argument("--out-dir", default="csv_cn", help="CSV 输出目录（默认 csv_cn）")
    ap.add_argument("--source", choices=("tx", "em"), default="tx",
                    help="tx=腾讯（默认，限流宽松/等差复权）；em=东财（等比复权/限流严格）")
    ap.add_argument("--sleep", type=float, default=2.0, help="每只股票之间的间隔秒数")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ok, failed = [], []
    for i, raw_sym in enumerate(args.symbols):
        symbol, code = norm_symbol(raw_sym)
        print(f"[{i + 1}/{len(args.symbols)}] {symbol} ({args.source} 源, {args.start}~{args.end})")
        try:
            raw_df, qfq_df = fetch_with_retry(code, args.start, args.end, args.source)
            df = build_csv(raw_df, qfq_df, symbol, args.source)
        except Exception as e:  # noqa: BLE001 单只失败不中断整批
            print(f"  [FAIL] {symbol}: {type(e).__name__}: {str(e)[:100]}")
            failed.append(symbol)
            continue
        path = out_dir / f"{symbol}.csv"
        df.to_csv(path, index=False)
        ok.append(symbol)
        print(f"  -> {path}  rows={len(df)}  {df['date'].iloc[0]}~{df['date'].iloc[-1]}  "
              f"factor末值={df['factor'].iloc[-1]:.4f}")
        if i < len(args.symbols) - 1:
            time.sleep(args.sleep)

    print(f"\n完成: {len(ok)} 成功, {len(failed)} 失败" + (f": {failed}" if failed else ""))
    if ok:
        print("下一步（转 qlib .bin）:")
        print(f"  python <qlib仓库>/scripts/dump_bin.py dump_all --data_path {out_dir} "
              f"--qlib_dir ~/.qlib/qlib_data/my_cn_data "
              f"--include_fields open,close,high,low,volume,factor "
              f"--date_field_name date --symbol_field_name symbol")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
