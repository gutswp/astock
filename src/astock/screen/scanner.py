import json
import subprocess

import pandas as pd
from rich.console import Console
from rich.progress import Progress

from astock.config import AppConfig
from astock.data.provider import get_hist, SINA_HEADERS
from astock.render.tables import print_scan_results
from astock.screen.indicators import (
    calc_volume_ratio,
    detect_ma_breakthrough,
    detect_macd_golden_cross,
)


def _curl_get(url: str, headers: dict | None = None, timeout: int = 15, encoding: str = "utf-8") -> str:
    cmd = ["curl", "-s", "--connect-timeout", str(timeout), url]
    if headers:
        for k, v in headers.items():
            cmd.extend(["-H", f"{k}: {v}"])
    result = subprocess.run(cmd, capture_output=True, timeout=timeout + 5)
    if result.returncode != 0:
        raise ConnectionError(f"curl failed: {result.stderr.decode(errors='replace')}")
    return result.stdout.decode(encoding, errors="replace")


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
            raw = _curl_get(url, SINA_HEADERS, timeout=10)
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
        volumes = hist["成交量"].astype(float)

        if config.scan.macd_golden_cross and detect_macd_golden_cross(closes):
            signals.append("MACD金叉")

        for period in config.scan.ma_breakthrough:
            if detect_ma_breakthrough(closes, period):
                signals.append(f"突破{period}日线")

        vol_ratio = calc_volume_ratio(volumes)
        if vol_ratio >= config.scan.volume_ratio_min:
            signals.append(f"量比{vol_ratio:.1f}")

    except Exception:
        pass
    return signals, vol_ratio


def run_scan(config: AppConfig) -> None:
    console = Console()
    df = _get_all_stocks_sina()
    if df.empty:
        console.print("[red]获取市场数据失败[/red]")
        return

    filtered = _filter_basic(df, config)
    console.print(f"[dim]基础筛选后剩余 {len(filtered)} 只[/dim]")

    # 按涨幅和成交额初筛：涨幅1-8%且有一定成交额的活跃股
    candidates = filtered[
        (filtered["涨跌幅"] >= 1.0) &
        (filtered["涨跌幅"] <= 8.0) &
        (filtered["成交额"] > 1e8)
    ].head(150)
    console.print(f"[dim]涨幅1-8%+成交额>1亿 候选 {len(candidates)} 只，开始技术面分析...[/dim]")

    results = []
    with Progress(console=console) as progress:
        task = progress.add_task("扫描中...", total=len(candidates))
        for _, row in candidates.iterrows():
            code = row["代码"]
            signals, vol_ratio = _scan_stock(code, config)
            if signals:
                score = len(signals) * 25
                if any("MACD" in s for s in signals):
                    score += 15
                if any("60日" in s for s in signals):
                    score += 10
                score = min(score, 100)
                results.append({
                    "code": code,
                    "name": row["名称"],
                    "price": row["最新价"],
                    "change_pct": row["涨跌幅"],
                    "volume_ratio": vol_ratio,
                    "signals": signals,
                    "score": score,
                })
            progress.advance(task)

    results.sort(key=lambda x: x["score"], reverse=True)
    results = results[:config.scan.max_results]

    print_scan_results(results)
