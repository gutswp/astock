"""开盘15分钟强弱判定 + 做T策略建议."""
from __future__ import annotations

import json
from collections import defaultdict

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from astock.config import AppConfig
from astock.data.http import curl_get
from astock.data.provider import _em_secid, get_spot
from astock.screen.t_signals import detect_signals


def _parse_trend_bar(row: str) -> dict | None:
    fields = row.split(",")
    if len(fields) < 8:
        return None

    close = float(fields[2] or 0)
    open_price = float(fields[1] or 0)
    if open_price <= 0:
        open_price = close

    vwap = float(fields[7] or 0)
    if vwap <= 0:
        vwap = close

    return {
        "time": fields[0],
        "open": open_price,
        "close": close,
        "high": float(fields[3] or close),
        "low": float(fields[4] or close),
        "volume": int(float(fields[5] or 0)),
        "amount": float(fields[6] or 0),
        "vwap": vwap,
    }


def get_intraday(code: str, ndays: int = 1) -> tuple[list[dict], float]:
    """拉取分时数据（eastmoney trends2）."""
    secid = _em_secid(code)
    days = max(1, min(ndays, 5))
    hosts = ["push2delay.eastmoney.com"] if days == 1 else ["push2his.eastmoney.com", "push2delay.eastmoney.com"]

    last_error: Exception | None = None
    for host in hosts:
        url = (
            f"https://{host}/api/qt/stock/trends2/get?"
            f"secid={secid}&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13"
            f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58&iscr=0&ndays={days}"
        )
        try:
            raw = curl_get(url, timeout=10)
            data = json.loads(raw)
            info = data.get("data") or {}
            preclose = float(info.get("preClose") or 0)
            trends = info.get("trends") or []

            bars: list[dict] = []
            for row in trends:
                bar = _parse_trend_bar(row)
                if bar:
                    bars.append(bar)
            if bars:
                return bars, preclose
        except Exception as exc:
            last_error = exc

    if last_error:
        raise last_error
    return [], 0.0


def get_intraday_sessions(code: str, ndays: int = 20) -> list[dict]:
    """按交易日切分分时数据，供训练/回放使用."""
    bars, _ = get_intraday(code, ndays=ndays)
    if not bars:
        return []

    grouped: dict[str, list[dict]] = defaultdict(list)
    order: list[str] = []
    for bar in bars:
        day = bar["time"][:10]
        if day not in grouped:
            order.append(day)
        grouped[day].append(bar)

    sessions: list[dict] = []
    prev_close = 0.0
    for day in order:
        day_bars = grouped[day]
        preclose = prev_close or day_bars[0]["open"] or day_bars[0]["close"]
        sessions.append({"date": day, "bars": day_bars, "preclose": preclose})
        prev_close = day_bars[-1]["close"]

    return sessions


def score_opening(bars: list[dict], preclose: float) -> dict:
    """对开盘前15分钟打分，返回分类和分数明细."""
    if len(bars) < 10:
        current = bars[-1]["close"] if bars else 0.0
        vwap = bars[-1]["vwap"] if bars else current
        change_pct = (current - preclose) / preclose * 100 if preclose else 0.0
        return {
            "score": 0,
            "label": "数据不足",
            "details": [],
            "strategy": "",
            "vwap": vwap,
            "current": current,
            "preclose": preclose,
            "change_pct": change_pct,
            "bar_count": len(bars),
            "first_wave": 0.0,
            "vwap_ratio": 0.0,
            "first_15": [],
        }

    first_15 = [b for b in bars if b["time"][11:16] <= "09:45"]
    if len(first_15) < 5:
        first_15 = bars[:15]

    if not first_15:
        return {"score": 0, "label": "数据不足", "details": [], "strategy": "", "first_15": []}

    details = []
    score = 0

    last_bar = first_15[-1]
    vwap = last_bar["vwap"]
    current = last_bar["close"]
    above_vwap_count = sum(1 for b in first_15 if b["close"] > b["vwap"])
    vwap_ratio = above_vwap_count / len(first_15)

    if vwap_ratio >= 0.7:
        score += 2
        details.append(("价格vs均价线", "+2", f"70%+时间在均价线上方({above_vwap_count}/{len(first_15)})"))
    elif vwap_ratio <= 0.3:
        score -= 2
        details.append(("价格vs均价线", "-2", f"70%+时间在均价线下方({len(first_15)-above_vwap_count}/{len(first_15)})"))
    else:
        details.append(("价格vs均价线", "0", f"均价线上下穿越({above_vwap_count}/{len(first_15)}在上方)"))

    mid = len(first_15) // 2
    first_half = first_15[:mid]
    second_half = first_15[mid:]

    if first_half and second_half:
        first_high = max(b["high"] for b in first_half)
        second_high = max(b["high"] for b in second_half)
        first_low = min(b["low"] for b in first_half)
        second_low = min(b["low"] for b in second_half)

        highs_rising = second_high > first_high
        lows_rising = second_low > first_low

        if highs_rising and lows_rising:
            score += 2
            details.append(("高低点趋势", "+2", f"高点抬高({first_high:.2f}→{second_high:.2f}) 低点也抬高"))
        elif not highs_rising and not lows_rising:
            score -= 2
            details.append(("高低点趋势", "-2", f"高点降低({first_high:.2f}→{second_high:.2f}) 低点也降低"))
        else:
            details.append(("高低点趋势", "0", "高低点无明确方向"))

    if first_half and second_half:
        first_vol = sum(b["volume"] for b in first_half)
        second_vol = sum(b["volume"] for b in second_half)
        price_up = second_half[-1]["close"] > first_half[0]["open"]

        if second_vol > first_vol * 1.2 and price_up:
            score += 2
            details.append(("成交量", "+2", f"放量上涨(后半段量{second_vol:,} > 前半段{first_vol:,})"))
        elif second_vol > first_vol * 1.2 and not price_up:
            score -= 2
            details.append(("成交量", "-2", f"放量下跌(后半段量{second_vol:,} > 前半段{first_vol:,})"))
        else:
            vol_label = "缩量" if second_vol < first_vol * 0.8 else "平量"
            details.append(("成交量", "0", f"{vol_label}波动(后半段{second_vol:,} vs 前半段{first_vol:,})"))

    change_pct = (current - preclose) / preclose * 100 if preclose else 0
    if change_pct > 0.5:
        score += 1
        details.append(("vs昨收", "+1", f"高于昨收 {change_pct:+.2f}%"))
    elif change_pct < -0.5:
        score -= 1
        details.append(("vs昨收", "-1", f"低于昨收 {change_pct:+.2f}%"))
    else:
        details.append(("vs昨收", "0", f"接近昨收 {change_pct:+.2f}%"))

    first_5 = first_15[:5]
    first_wave = 0.0
    if first_5:
        open_price = first_5[0]["open"] or first_5[0]["close"]
        close_5min = first_5[-1]["close"]
        first_wave = (close_5min - open_price) / open_price * 100 if open_price else 0
        if first_wave > 0.3:
            score += 1
            details.append(("首波方向", "+1", f"前5分钟上攻 {first_wave:+.2f}%"))
        elif first_wave < -0.3:
            score -= 1
            details.append(("首波方向", "-1", f"前5分钟下探 {first_wave:+.2f}%"))
        else:
            details.append(("首波方向", "0", f"前5分钟平稳 {first_wave:+.2f}%"))

    if score >= 4:
        label = "强势"
        strategy = "只做倒T（先卖后买）或持仓不动，不追高不正T"
    elif score <= -4:
        label = "弱势"
        strategy = "只做正T（先买后卖）或不做T，不追涨不倒T"
    elif score >= 2:
        label = "偏强"
        strategy = "优先倒T，回踩均价线可小仓位正T"
    elif score <= -2:
        label = "偏弱"
        strategy = "等止跌信号再正T，不抄底不倒T"
    else:
        label = "震荡"
        strategy = "双向做T：均价线下方买，均价线上方卖，高频小T(0.1~0.2元)"

    return {
        "score": score,
        "label": label,
        "details": details,
        "strategy": strategy,
        "vwap": vwap,
        "current": current,
        "preclose": preclose,
        "change_pct": change_pct,
        "bar_count": len(first_15),
        "first_wave": first_wave,
        "vwap_ratio": vwap_ratio,
        "first_15": first_15,
    }


def build_tscore_results(
    config: AppConfig,
    codes: list[str] | None = None,
    console: Console | None = None,
) -> list[dict]:
    """生成评分结果，供 CLI 和 Web 复用."""
    from astock.portfolio.manager import _collect_holdings

    holdings = _collect_holdings(config)
    holding_name_map: dict[str, str] = {}
    for h in holdings:
        holding_name_map.setdefault(h.code, h.name)

    if not codes:
        codes = []
        seen: set[str] = set()
        for h in holdings:
            if h.code not in seen:
                seen.add(h.code)
                codes.append(h.code)

    name_map = dict(holding_name_map)
    if codes:
        try:
            spot = get_spot(codes)
            if not spot.empty:
                for _, row in spot.iterrows():
                    name_map[str(row["代码"]).zfill(6)] = str(row["名称"])
        except Exception:
            pass

    results: list[dict] = []
    for code in codes:
        try:
            bars, preclose = get_intraday(code)
            result = score_opening(bars, preclose)
            result["code"] = code
            result["name"] = name_map.get(code, code)
            result["full_bars"] = bars
            result["chart_times"] = [b["time"][11:16] for b in bars]
            result["chart_closes"] = [round(b["close"], 2) for b in bars]
            result["chart_vwaps"] = [round(b["vwap"], 2) for b in bars]
            result["signals"] = detect_signals(
                bars, preclose, result.get("label", ""), code=code
            )
            results.append(result)
        except Exception as exc:
            if console:
                console.print(f"[dim]{code}: 获取失败 ({exc})[/dim]")

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def build_training_case(code: str, day: str | None = None, ndays: int = 5) -> dict | None:
    """构造一题训练样本：先观察前15分钟，再猜强弱标签。"""
    sessions = get_intraday_sessions(code, ndays=ndays)
    if not sessions:
        return None

    chosen = sessions[-1]
    if day:
        chosen = next((session for session in sessions if session["date"] == day), chosen)

    scored = score_opening(chosen["bars"], chosen["preclose"])
    first_15 = scored.get("first_15") or []
    full_bars = chosen["bars"]
    reveal_price = first_15[-1]["close"] if first_15 else (full_bars[-1]["close"] if full_bars else 0.0)
    post_bars = [bar for bar in full_bars if not first_15 or bar["time"] > first_15[-1]["time"]]
    post_high = max((bar["high"] for bar in post_bars), default=reveal_price)
    post_low = min((bar["low"] for bar in post_bars), default=reveal_price)
    post_close = post_bars[-1]["close"] if post_bars else reveal_price
    day_close = full_bars[-1]["close"] if full_bars else reveal_price

    post_open_high_pct = (post_high - reveal_price) / reveal_price * 100 if reveal_price else 0.0
    post_open_low_pct = (post_low - reveal_price) / reveal_price * 100 if reveal_price else 0.0
    post_open_close_pct = (post_close - reveal_price) / reveal_price * 100 if reveal_price else 0.0
    day_change_pct = (day_close - chosen["preclose"]) / chosen["preclose"] * 100 if chosen["preclose"] else 0.0

    return {
        **scored,
        "code": code,
        "date": chosen["date"],
        "bars": first_15,
        "available_dates": [session["date"] for session in sessions],
        "time_labels": [bar["time"][11:16] for bar in first_15],
        "close_points": [round(bar["close"], 2) for bar in first_15],
        "vwap_points": [round(bar["vwap"], 2) for bar in first_15],
        "full_time_labels": [bar["time"][11:16] for bar in full_bars],
        "full_close_points": [round(bar["close"], 2) for bar in full_bars],
        "full_vwap_points": [round(bar["vwap"], 2) for bar in full_bars],
        "reveal_price": round(reveal_price, 2),
        "post_open_high_pct": post_open_high_pct,
        "post_open_low_pct": post_open_low_pct,
        "post_open_close_pct": post_open_close_pct,
        "day_change_pct": day_change_pct,
    }


def run_tscore(config: AppConfig, codes: list[str] | None = None) -> None:
    """对持仓股做开盘15分钟评分."""
    console = Console()
    results = build_tscore_results(config, codes=codes, console=console)

    if not results:
        console.print("[yellow]无有效数据[/yellow]")
        return

    console.print()
    table = Table(title="开盘15分钟强弱评分", show_header=True, header_style="bold", expand=True)
    table.add_column("股票", style="bold", ratio=3)
    table.add_column("代码", ratio=2)
    table.add_column("得分", justify="center", ratio=1)
    table.add_column("判定", justify="center", ratio=2)
    table.add_column("现价", justify="right", ratio=2)
    table.add_column("vs昨收", justify="right", ratio=2)
    table.add_column("策略", ratio=6)

    label_colors = {
        "强势": "bold red", "偏强": "red",
        "弱势": "bold green", "偏弱": "green",
        "震荡": "yellow", "数据不足": "dim",
    }

    for r in results:
        color = label_colors.get(r["label"], "white")
        score_str = f"[{color}]{r['score']:+d}[/{color}]"
        label_str = f"[{color}]{r['label']}[/{color}]"
        chg = r.get("change_pct", 0)
        chg_color = "red" if chg > 0 else "green" if chg < 0 else "white"

        table.add_row(
            r["name"], r["code"],
            score_str, label_str,
            f"{r.get('current', 0):.2f}",
            f"[{chg_color}]{chg:+.2f}%[/{chg_color}]",
            r["strategy"],
        )

    console.print(table)
    console.print()

    for r in results:
        if not r.get("details"):
            continue
        detail_table = Table(show_header=True, header_style="dim", expand=False, title_style="bold")
        detail_table.add_column("指标", ratio=3)
        detail_table.add_column("分数", justify="center", ratio=1)
        detail_table.add_column("说明", ratio=8)

        for indicator, pts, desc in r["details"]:
            pts_int = int(pts) if pts.lstrip("+-").isdigit() else 0
            if pts_int > 0:
                pts_str = f"[red]{pts}[/red]"
            elif pts_int < 0:
                pts_str = f"[green]{pts}[/green]"
            else:
                pts_str = f"[dim]{pts}[/dim]"
            detail_table.add_row(indicator, pts_str, desc)

        color = label_colors.get(r["label"], "white")
        panel = Panel(
            detail_table,
            title=f"{r['name']}({r['code']}) → [{color}]{r['label']}[/{color}] (得分 {r['score']:+d})",
            subtitle=r["strategy"],
            border_style=color.replace("bold ", ""),
        )
        console.print(panel)
        console.print()
