#!/usr/bin/env python3
"""akshare A 股日线导出 → qlib dump_bin 规范 CSV + instruments 股票池文件。

输出规范（对应 scripts/dump_bin.py dump_all 的要求，见 qlib 官方文档 Data Preparation）：
- 每只股票一个 CSV，文件名即证券代码（如 SH600000.csv），小写列名
- 列：date, symbol, open, close, high, low, volume, factor
- open/close/high/low/volume 为**前复权价**，factor = qfq/raw，使 $close/$factor == 真实价
- **停牌日补齐**：交易日历上股票缺的行补 NaN（qlib 约定：停牌日 OHLCV/factor 全 NaN），
  范围为该股票首个~最后一个有数据日之间；同时保证小批量导出时 dump 日历完整
- **instruments 文件**：输出 <out-dir>/instruments/all.txt 及自定义池
  （qlib 格式：`SH600000\\t2024-01-02\\t2025-09-17`，起止为股票自身有数据的日期）

数据源（--source）：
- tx（默认）腾讯 stock_zh_a_hist_tx：限流宽松；qfq 为等差复权，
  factor=qfq/raw 逐日微漂，qlib 代数关系仍成立，但段内收益率有微小失真
- em 东财 stock_zh_a_hist：等比复权、factor 分段恒定（更标准），但限流严格；
  在被限流的 IP 上会 ConnectionError/超时，可改用 tx 或稍后再试

交易日历：固定取腾讯上证指数（sh000001）日线（与 --source 无关）；
接口失败时降级为「已导出股票的日期并集」（整批同日停牌的极小概率场景会漏日）。

用法：
    # 导出并生成自定义股票池 mypool（可多次 --pool 定义多个池）
    python export_akshare_csv.py --symbols sh600000 sz000001 sh600519 \\
        --start 20240101 --end 20250917 --out-dir csv_cn \\
        --pool mypool=sh600000,sh600519

    # 导出后转 qlib .bin，并拷贝股票池文件（详见 data/README.md）
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
INDEX_SYMBOL = "sh000001"  # 腾讯源上证指数，用作交易日历


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


def fetch_calendar_tx(start: str, end: str) -> list[str] | None:
    """腾讯上证指数日线作为交易日历（YYYY-MM-DD 字符串列表）；失败返回 None。"""
    try:
        import akshare as ak

        df = ak.stock_zh_a_hist_tx(symbol=INDEX_SYMBOL, start_date=start, end_date=end, adjust="")
        days = sorted(df["date"].astype(str).tolist())
        print(f"交易日历（腾讯{INDEX_SYMBOL}）: {len(days)} 天, {days[0]} ~ {days[-1]}")
        return days
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 指数日历获取失败（{type(e).__name__}: {str(e)[:60]}），降级为股票日期并集")
        return None


def build_csv(raw: pd.DataFrame, qfq: pd.DataFrame, symbol: str, source: str) -> pd.DataFrame:
    """合并不复权与 qfq 数据，产出 dump_bin 规范 DataFrame（不含停牌补齐）。"""
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
    df["date"] = df["date"].astype(str)
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
    return df[COLS_OUT].sort_values("date").reset_index(drop=True)


def backfill_suspend_days(df: pd.DataFrame, calendar: list[str], symbol: str) -> pd.DataFrame:
    """按交易日历补齐股票缺行（停牌日）：范围内缺失日补一行，OHLCV/factor 全 NaN。

    qlib 约定停牌日数据为 NaN（官方 yahoo collector 同样置 NaN）；
    dump_bin 虽会按日历 reindex，但显式补行可保证小批量导出时日历 union 完整。
    """
    dates = set(df["date"])
    first, last = df["date"].min(), df["date"].max()
    missing = [d for d in calendar if first <= d <= last and d not in dates]
    if not missing:
        return df
    nan_rows = pd.DataFrame({"date": missing, "symbol": symbol, **{c: float("nan") for c in COLS_OUT[2:]}})
    out = pd.concat([df, nan_rows], ignore_index=True).sort_values("date").reset_index(drop=True)
    print(f"  [suspend] {symbol} 补齐停牌/缺行 {len(missing)} 天: {missing[0]}~{missing[-1]}")
    return out


def write_instruments(out_dir: Path, ranges: dict[str, tuple[str, str]], pools: dict[str, list[str]]) -> None:
    """生成 qlib instruments 文件：SYM<TAB>START<TAB>END（无表头）。

    all.txt 恒生成（全部成功导出的股票）；pools 中每个自定义池生成同名文件。
    起止日期取股票自身有数据的日期范围（不含补齐的 NaN 行）。
    """
    inst_dir = out_dir / "instruments"
    inst_dir.mkdir(parents=True, exist_ok=True)
    all_syms = sorted(ranges)
    (inst_dir / "all.txt").write_text(
        "\n".join(f"{s}\t{ranges[s][0]}\t{ranges[s][1]}" for s in all_syms) + "\n", encoding="utf-8"
    )
    print(f"instruments: {inst_dir / 'all.txt'} ({len(all_syms)} 只)")
    for pool, raw_syms in pools.items():
        syms = [norm_symbol(s)[0] for s in raw_syms]  # 兼容直接调用时未大写化的代码
        unknown = [s for s in syms if s not in ranges]
        if unknown:
            print(f"[warn] 股票池 {pool} 含未导出成功/未声明的代码: {unknown}，已跳过")
        valid = [s for s in syms if s in ranges]
        if not valid:
            continue
        (inst_dir / f"{pool}.txt").write_text(
            "\n".join(f"{s}\t{ranges[s][0]}\t{ranges[s][1]}" for s in sorted(valid)) + "\n", encoding="utf-8"
        )
        print(f"instruments: {inst_dir / (pool + '.txt')} ({len(valid)} 只)")


def parse_pools(pairs: list[str] | None) -> dict[str, list[str]]:
    """解析 --pool mypool=sh600000,sh600519 为 {'mypool': ['SH600000', 'SH600519']}。"""
    pools: dict[str, list[str]] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise ValueError(f"--pool 格式应为 名称=代码1,代码2，得到: {pair!r}")
        name, syms = pair.split("=", 1)
        name = name.strip()
        if not name or not syms.strip():
            raise ValueError(f"--pool 名称或代码为空: {pair!r}")
        if name in pools:
            raise ValueError(f"--pool 名称重复: {name}")
        pools[name] = [norm_symbol(s)[0] for s in syms.split(",") if s.strip()]
    return pools


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
    ap.add_argument("--pool", action="append", default=[], metavar="NAME=SYM,SYM",
                    help="自定义股票池，可重复：--pool mypool=sh600000,sh600519")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pools = parse_pools(args.pool)

    # 1) 逐只拉取并构建
    frames: dict[str, pd.DataFrame] = {}
    failed: list[str] = []
    for i, raw_sym in enumerate(args.symbols):
        symbol, code = norm_symbol(raw_sym)
        print(f"[{i + 1}/{len(args.symbols)}] {symbol} ({args.source} 源, {args.start}~{args.end})")
        try:
            raw_df, qfq_df = fetch_with_retry(code, args.start, args.end, args.source)
            frames[symbol] = build_csv(raw_df, qfq_df, symbol, args.source)
        except Exception as e:  # noqa: BLE001 单只失败不中断整批
            print(f"  [FAIL] {symbol}: {type(e).__name__}: {str(e)[:100]}")
            failed.append(symbol)
        if i < len(args.symbols) - 1:
            time.sleep(args.sleep)

    if not frames:
        print("无任何股票导出成功")
        return 1

    # 2) 交易日历 + 停牌补齐 + 写 CSV
    calendar = fetch_calendar_tx(args.start, args.end)
    if calendar is None:  # 降级：已导出股票日期并集
        calendar = sorted(set().union(*[set(f["date"]) for f in frames.values()]))
        print(f"交易日历（并集降级）: {len(calendar)} 天")

    ranges: dict[str, tuple[str, str]] = {}
    for symbol, df in frames.items():
        df = backfill_suspend_days(df, calendar, symbol)
        ranges[symbol] = (df["date"].min(), df["date"].max())
        path = out_dir / f"{symbol}.csv"
        df.to_csv(path, index=False)
        print(f"  -> {path}  rows={len(df)}  {ranges[symbol][0]}~{ranges[symbol][1]}  "
              f"factor末值={df['factor'].iloc[-1]:.4f}")

    # 3) instruments 文件
    write_instruments(out_dir, ranges, pools)

    print(f"\n完成: {len(frames)} 成功, {len(failed)} 失败" + (f": {failed}" if failed else ""))
    print("下一步（转 qlib .bin 并挂载股票池）:")
    print(f"  python <qlib仓库>/scripts/dump_bin.py dump_all --data_path {out_dir} "
          f"--qlib_dir ~/.qlib/qlib_data/my_cn_data "
          f"--include_fields open,close,high,low,volume,factor "
          f"--date_field_name date --symbol_field_name symbol")
    print(f"  cp {out_dir}/instruments/*.txt ~/.qlib/qlib_data/my_cn_data/instruments/")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
