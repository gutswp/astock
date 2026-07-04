from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from astock.data.provider import get_hist, get_spot

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

    return JSONResponse({
        "code": code,
        "dates": dates,
        "ohlc": ohlc,
        "volumes": volumes,
        "ma5": _ma(closes, 5),
        "ma10": _ma(closes, 10),
        "ma20": _ma(closes, 20),
        "ma60": _ma(closes, 60),
    })
