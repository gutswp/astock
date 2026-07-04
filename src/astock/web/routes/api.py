from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from astock.data.provider import get_hist, get_spot
from astock.screen.indicators import calc_bollinger, calc_sar

router = APIRouter(prefix="/api")


@router.get("/lookup")
async def lookup(code: str = Query("")):
    """返回 HTML 片段：股票名称 + 现价（HTMX 片段用）"""
    code = code.strip()
    if not code:
        return HTMLResponse("")
    if not code.isdigit() or len(code) != 6:
        return HTMLResponse(
            '<span class="text-gray-500">需 6 位数字代码</span>'
        )
    try:
        df = await run_in_threadpool(get_spot, [code])
    except Exception:
        return HTMLResponse(
            '<span class="text-up">查询失败</span>'
        )
    if df.empty:
        return HTMLResponse(
            f'<span class="text-yellow-400">未找到 {code}</span>'
        )
    row = df.iloc[0]
    change_pct = float(row.get("涨跌幅") or 0)
    color = "pos" if change_pct > 0 else ("neg" if change_pct < 0 else "text-gray-400")
    return HTMLResponse(
        f'<span class="text-white font-semibold">{row["名称"]}</span> '
        f'· 现价 <span class="num text-gray-300">{float(row["最新价"]):.2f}</span> '
        f'· <span class="num {color}">{change_pct:+.2f}%</span>'
    )


def _ma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(values)):
        if i + 1 < period:
            out.append(None)
        else:
            window = values[i + 1 - period : i + 1]
            out.append(round(sum(window) / period, 3))
    return out


@router.get("/kline/{code}")
async def kline(code: str, days: int = 120):
    """返回 ECharts 蜡烛图所需的 JSON 数据."""
    code = code.zfill(6)
    try:
        df = await run_in_threadpool(get_hist, code, days)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    if df.empty:
        return JSONResponse({"error": "no data"}, status_code=404)

    dates = df["日期"].astype(str).tolist()
    # ECharts candlestick 格式：[open, close, low, high]
    ohlc = [
        [float(o), float(c), float(l), float(h)]
        for o, c, l, h in zip(df["开盘"], df["收盘"], df["最低"], df["最高"])
    ]
    volumes = [int(v) for v in df["成交量"].tolist()]
    closes = [float(c) for c in df["收盘"].tolist()]

    import pandas as pd
    closes_s = pd.Series(closes)
    highs_s = pd.Series([float(h) for h in df["最高"].tolist()])
    lows_s = pd.Series([float(l) for l in df["最低"].tolist()])

    upper, mid, lower = calc_bollinger(closes_s, period=20)
    sar_s, trend_s = calc_sar(highs_s, lows_s)

    def _clean(series):
        return [None if pd.isna(v) else round(float(v), 3) for v in series]

    def _sar_split(sar_series, trend_series):
        """把 SAR 拆成"多头下方"和"空头上方"两组，便于用不同符号绘制."""
        up_pts: list = []
        down_pts: list = []
        for v, t in zip(sar_series, trend_series):
            if pd.isna(v) or t == 0:
                up_pts.append(None)
                down_pts.append(None)
            elif t == 1:  # 多头，SAR 在下方
                up_pts.append(round(float(v), 3))
                down_pts.append(None)
            else:  # 空头，SAR 在上方
                up_pts.append(None)
                down_pts.append(round(float(v), 3))
        return up_pts, down_pts

    sar_up, sar_down = _sar_split(sar_s, trend_s)

    return JSONResponse({
        "code": code,
        "dates": dates,
        "ohlc": ohlc,
        "volumes": volumes,
        "ma5": _ma(closes, 5),
        "ma10": _ma(closes, 10),
        "ma20": _ma(closes, 20),
        "ma60": _ma(closes, 60),
        "boll_upper": _clean(upper),
        "boll_mid": _clean(mid),
        "boll_lower": _clean(lower),
        "sar_up": sar_up,      # 多头形态：SAR 在 K 线下方
        "sar_down": sar_down,  # 空头形态：SAR 在 K 线上方
    })
