import json

import pandas as pd
from rich.console import Console
from rich.progress import Progress

from astock.config import AppConfig
from astock.data.http import SINA_HEADERS, curl_get
from astock.data.provider import get_all_spot, get_hist
from astock.render.tables import print_scan_results
from astock.screen.indicators import (
    calc_volume_ratio,
    detect_boll_lower_bounce,
    detect_kdj_golden_cross,
    detect_ma_breakthrough,
    detect_macd_golden_cross,
    detect_rsi_oversold_reversal,
)


def _get_all_stocks_sina() -> pd.DataFrame:
    console = Console()
    console.print("[dim]正在获取全市场股票列表...[/dim]")

    all_records = []
    for page in range(1, 60):
        url = (
            f"https://vip.stock.finance.sina.com.cn/quotes_service/api/"
            f"json_v2.php/Market_Center.getHQNodeData?"
            f"page={page}&num=80&sort=changepercent&asc=0&node=hs_a&symbol=&_s_r_a=page"
        )
        try:
            raw = curl_get(url, SINA_HEADERS, timeout=10)
            if not raw or raw.strip() == "null" or raw.strip() == "[]":
                break
            data = json.loads(raw)
            if not data:
                break
            for item in data:
                code = item.get("code", "")
                name = item.get("name", "")
                if not code or not name:
                    continue
                all_records.append({
                    "代码": code,
                    "名称": name,
                    "最新价": float(item.get("trade", 0) or 0),
                    "涨跌幅": float(item.get("changepercent", 0) or 0),
                    "成交量": int(float(item.get("volume", 0) or 0)),
                    "成交额": float(item.get("amount", 0) or 0),
                    "总市值": float(item.get("mktcap", 0) or 0),
                    "量比": float(item.get("volumeratio", 0) or 0),
                })
        except Exception:
            break

    console.print(f"[dim]获取到 {len(all_records)} 只股票[/dim]")
    return pd.DataFrame(all_records)


def _filter_basic(df: pd.DataFrame, config: AppConfig) -> pd.DataFrame:
    scan = config.scan
    filtered = df[df["最新价"] > 0].copy()

    if scan.exclude_st:
        filtered = filtered[~filtered["名称"].str.contains("ST|退市", na=False)]

    # 新浪市值单位是万元, min_market_cap 单位是亿元
    if scan.min_market_cap > 0:
        filtered = filtered[filtered["总市值"] >= scan.min_market_cap * 10000]

    if scan.exclude_limit_up:
        filtered = filtered[filtered["涨跌幅"] < 9.8]

    return filtered


def _scan_stock(code: str, config: AppConfig) -> tuple[list[str], float]:
    signals = []
    vol_ratio = 0.0
    try:
        hist = get_hist(code, 120)
        if hist.empty or len(hist) < 30:
            return signals, vol_ratio

        closes = hist["收盘"].astype(float)
        highs = hist["最高"].astype(float)
        lows = hist["最低"].astype(float)
        volumes = hist["成交量"].astype(float)

        if config.scan.macd_golden_cross and detect_macd_golden_cross(closes):
            signals.append("MACD金叉")

        for period in config.scan.ma_breakthrough:
            if detect_ma_breakthrough(closes, period):
                signals.append(f"突破{period}日线")

        if config.scan.rsi_oversold_reversal and detect_rsi_oversold_reversal(closes):
            signals.append("RSI超卖反弹")

        if config.scan.kdj_golden_cross and detect_kdj_golden_cross(highs, lows, closes):
            signals.append("KDJ金叉")

        if config.scan.boll_lower_bounce and detect_boll_lower_bounce(closes):
            signals.append("BOLL下轨反弹")

        vol_ratio = calc_volume_ratio(volumes)
        if vol_ratio >= config.scan.volume_ratio_min:
            signals.append(f"量比{vol_ratio:.1f}")

    except Exception:
        pass
    return signals, vol_ratio


def _get_all_stocks_akshare() -> pd.DataFrame:
    """akshare 兜底：字段与新浪对齐（总市值统一为万元）."""
    console = Console()
    console.print("[dim]切到 AKShare 全市场兜底...[/dim]")
    try:
        df = get_all_spot()
    except Exception as e:
        console.print(f"[yellow]AKShare 也失败: {e}[/yellow]")
        return pd.DataFrame()
    if df.empty:
        return df
    keep = ["代码", "名称", "最新价", "涨跌幅", "成交量", "成交额", "总市值", "量比"]
    for col in keep:
        if col not in df.columns:
            df[col] = 0
    df = df[keep].copy()
    # akshare 总市值单位是元；新浪路径已是万元
    df["总市值"] = df["总市值"].astype(float) / 10000
    for col in ["最新价", "涨跌幅", "成交额", "量比"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["成交量"] = pd.to_numeric(df["成交量"], errors="coerce").fillna(0).astype(int)
    console.print(f"[dim]AKShare 兜底拿到 {len(df)} 只[/dim]")
    return df


def _score(signals: list[str]) -> int:
    score = len(signals) * 20
    if any("MACD" in s for s in signals):
        score += 15
    if any("60日" in s for s in signals):
        score += 10
    has_rsi = any("RSI" in s for s in signals)
    has_boll = any("BOLL" in s for s in signals)
    has_kdj = any("KDJ" in s for s in signals)
    if has_rsi and has_boll:
        score += 10  # 反转双确认
    if has_kdj and (has_rsi or has_boll):
        score += 5
    return min(score, 100)


def scan(
    config: AppConfig,
    silent: bool = False,
    progress_cb=None,
    should_stop=None,
) -> list[dict]:
    """核心扫描逻辑。
    silent=True 时不打印进度，供 advise 等其他命令复用。
    progress_cb: callable(stage: str, current: int, total: int) 用于 web 端进度回报。
    should_stop: callable() -> bool，返回 True 时提前中止。
    """
    console = Console(quiet=silent)

    if progress_cb:
        progress_cb("拉取全市场列表", 0, 1)
    df = _get_all_stocks_sina()
    if df.empty:
        if progress_cb:
            progress_cb("AKShare 兜底", 0, 1)
        df = _get_all_stocks_akshare()
    if df.empty:
        if not silent:
            console.print("[red]新浪与 AKShare 双通道均失败[/red]")
        return []

    filtered = _filter_basic(df, config)
    if not silent:
        console.print(f"[dim]基础筛选后剩余 {len(filtered)} 只[/dim]")

    candidates = filtered[
        (filtered["涨跌幅"] >= 1.0) &
        (filtered["涨跌幅"] <= 8.0) &
        (filtered["成交额"] > 1e8)
    ].head(150)
    total = len(candidates)
    if not silent:
        console.print(f"[dim]涨幅1-8%+成交额>1亿 候选 {total} 只，开始技术面分析...[/dim]")
    if progress_cb:
        progress_cb("技术面分析", 0, total)

    results = []

    def _record_hit(row, signals, vol_ratio):
        results.append({
            "code": row["代码"], "name": row["名称"], "price": row["最新价"],
            "change_pct": row["涨跌幅"], "volume_ratio": vol_ratio,
            "signals": signals, "score": _score(signals),
        })

    if silent:
        for i, (_, row) in enumerate(candidates.iterrows(), start=1):
            if should_stop and should_stop():
                break
            signals, vol_ratio = _scan_stock(row["代码"], config)
            if signals:
                _record_hit(row, signals, vol_ratio)
            if progress_cb and i % 5 == 0:
                progress_cb("技术面分析", i, total)
    else:
        with Progress(console=console) as progress:
            task = progress.add_task("扫描中...", total=total)
            for i, (_, row) in enumerate(candidates.iterrows(), start=1):
                if should_stop and should_stop():
                    break
                signals, vol_ratio = _scan_stock(row["代码"], config)
                if signals:
                    _record_hit(row, signals, vol_ratio)
                progress.advance(task)
                if progress_cb and i % 5 == 0:
                    progress_cb("技术面分析", i, total)

    if progress_cb:
        progress_cb("完成", total, total)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:config.scan.max_results]


def run_scan(config: AppConfig) -> None:
    results = scan(config, silent=False)
    print_scan_results(results)
