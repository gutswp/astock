from fastapi import APIRouter, Form, Query, Request
from starlette.concurrency import run_in_threadpool

from astock.data.provider import get_spot
from astock.tools import backtest as bt
from astock.tools.sizing import SizingInput, compute
from astock.web.deps import render

router = APIRouter(prefix="/tools")


@router.get("/sizing")
async def sizing_page(request: Request):
    return render(request, "sizing.html", active="tools", title="仓位建议器", result=None)


@router.post("/sizing")
async def sizing_run(
    request: Request,
    capital: float = Form(...),
    risk_pct: float = Form(...),
    entry_price: float = Form(...),
    stop_price: float = Form(...),
    target_price: float | None = Form(None),
    code: str | None = Form(None),
):
    inp = SizingInput(
        capital=capital, risk_pct=risk_pct,
        entry_price=entry_price, stop_price=stop_price,
        target_price=target_price if (target_price and target_price > 0) else None,
    )
    result = compute(inp)
    name = ""
    if code:
        try:
            df = await run_in_threadpool(get_spot, [code])
            if not df.empty:
                name = str(df.iloc[0]["名称"])
        except Exception:
            pass
    return render(
        request, "sizing.html",
        active="tools", title="仓位建议器",
        result=result, inp=inp, name=name, code=code or "",
    )


@router.get("/backtest")
async def backtest_page(request: Request):
    return render(
        request, "backtest.html",
        active="tools", title="信号回测",
        strategies=bt.STRATEGIES,
        result=None,
    )


@router.post("/backtest")
async def backtest_run(
    request: Request,
    code: str = Form(...),
    strategy: str = Form(...),
    hold_days: int = Form(5),
    days: int = Form(250),
):
    result = await run_in_threadpool(bt.run, code.zfill(6), strategy, hold_days, days)
    name = ""
    try:
        df = await run_in_threadpool(get_spot, [code.zfill(6)])
        if not df.empty:
            name = str(df.iloc[0]["名称"])
    except Exception:
        pass
    return render(
        request, "backtest.html",
        active="tools", title="信号回测",
        strategies=bt.STRATEGIES,
        result=result, code=code, name=name,
        hold_days=hold_days, days=days, strategy=strategy,
    )
