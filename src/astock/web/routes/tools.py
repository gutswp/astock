from fastapi import APIRouter, Form, Query, Request
from starlette.concurrency import run_in_threadpool

from astock.data.provider import get_spot
from astock.tools import backtest as bt
from astock.tools.sizing import KellyInput, SizingInput, compute, compute_kelly
from astock.web.deps import render

router = APIRouter(prefix="/tools")


@router.get("/sizing")
async def sizing_page(
    request: Request,
    mode: str = "risk",
    code: str | None = None,
    win_rate: float | None = None,
    avg_win: float | None = None,
    avg_loss: float | None = None,
):
    # 从批量回测跳过来时会带 win_rate/avg_win/avg_loss，自动切到 kelly
    if win_rate is not None and avg_win is not None:
        mode = "kelly"
    return render(
        request, "sizing.html",
        active="tools", title="仓位建议器",
        mode=mode,
        code=code or "",
        prefill_win_rate=win_rate,
        prefill_avg_win=avg_win,
        prefill_avg_loss=avg_loss,
        result=None,
        kelly_result=None,
    )


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
        mode="risk",
        result=result, inp=inp, name=name, code=code or "",
    )


@router.post("/sizing/kelly")
async def sizing_kelly_run(
    request: Request,
    capital: float = Form(...),
    entry_price: float = Form(...),
    win_rate: float = Form(...),
    avg_win: float = Form(...),
    avg_loss: float = Form(...),
    fraction: float = Form(0.25),
    code: str | None = Form(None),
):
    inp = KellyInput(
        capital=capital, entry_price=entry_price,
        win_rate=win_rate, avg_win=avg_win, avg_loss=avg_loss, fraction=fraction,
    )
    kelly_result = compute_kelly(inp)
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
        active="tools", title="仓位建议器 · 凯利",
        mode="kelly",
        kelly_result=kelly_result,
        kelly_inp=inp,
        prefill_win_rate=win_rate,
        prefill_avg_win=avg_win,
        prefill_avg_loss=avg_loss,
        name=name, code=code or "",
    )


@router.get("/backtest")
async def backtest_page(request: Request):
    return render(
        request, "backtest.html",
        active="tools", title="信号回测",
        strategies=bt.STRATEGIES,
        result=None,
    )


@router.get("/backtest/batch")
async def backtest_batch_page(request: Request):
    config = request.app.state.config
    holdings = []
    seen = set()
    for acct in config.accounts:
        for h in acct.holdings:
            if h.code not in seen:
                seen.add(h.code)
                holdings.append({"code": h.code, "name": h.name})
    holdings.sort(key=lambda x: x["code"])
    return render(
        request, "backtest_batch.html",
        active="tools", title="批量回测",
        strategies=bt.STRATEGIES,
        holdings=holdings,
        results=None,
        agg=None,
    )


@router.get("/optimize")
async def optimize_page(request: Request):
    return render(
        request, "optimize.html",
        active="tools", title="策略参数优化",
        families=bt.STRATEGY_FAMILIES,
        result=None,
    )


@router.post("/optimize")
async def optimize_run(
    request: Request,
    code: str = Form(...),
    family: str = Form(...),
    days: int = Form(500),
):
    result = await run_in_threadpool(bt.grid_search, code.zfill(6), family, days)
    name = ""
    try:
        df = await run_in_threadpool(get_spot, [code.zfill(6)])
        if not df.empty:
            name = str(df.iloc[0]["名称"])
    except Exception:
        pass
    return render(
        request, "optimize.html",
        active="tools", title="策略参数优化",
        families=bt.STRATEGY_FAMILIES,
        result=result, code=code, name=name, family=family, days=days,
    )


@router.post("/backtest/batch")
async def backtest_batch_run(request: Request):
    form = await request.form()
    picked = [c for c in form.getlist("codes") if c]
    custom = (form.get("custom") or "").strip()
    if custom:
        for chunk in custom.replace(",", "\n").split("\n"):
            c = chunk.strip()
            if c.isdigit() and len(c) == 6 and c not in picked:
                picked.append(c)
    strategy = form.get("strategy") or "macd_golden_cross"
    hold_days = int(form.get("hold_days") or 5)
    days = int(form.get("days") or 250)
    picked = picked[:30]  # 上限 30 只

    results = await run_in_threadpool(bt.run_batch, picked, strategy, hold_days, days)
    # 拿名称
    name_map: dict[str, str] = {}
    if picked:
        try:
            df = await run_in_threadpool(get_spot, picked)
            if not df.empty:
                for _, r in df.iterrows():
                    name_map[str(r["代码"]).zfill(6)] = str(r["名称"])
        except Exception:
            pass
    for r in results:
        r.name = name_map.get(r.code, r.code)

    agg = bt.aggregate(results)
    config = request.app.state.config
    holdings = []
    seen = set()
    for acct in config.accounts:
        for h in acct.holdings:
            if h.code not in seen:
                seen.add(h.code)
                holdings.append({"code": h.code, "name": h.name})
    holdings.sort(key=lambda x: x["code"])
    return render(
        request, "backtest_batch.html",
        active="tools", title="批量回测",
        strategies=bt.STRATEGIES,
        holdings=holdings,
        results=results,
        agg=agg,
        picked_codes=picked,
        strategy=strategy,
        hold_days=hold_days,
        days=days,
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
    curve = None
    if result and result.trades:
        curve = bt.equity_curve(result)
    return render(
        request, "backtest.html",
        active="tools", title="信号回测",
        strategies=bt.STRATEGIES,
        result=result, code=code, name=name,
        hold_days=hold_days, days=days, strategy=strategy,
        curve=curve,
    )
