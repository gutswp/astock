from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from astock.portfolio.manager import record_trade
from astock.web.deps import render

router = APIRouter()


@router.get("/trade")
async def trade_page(request: Request, msg: str | None = None, err: str | None = None):
    config = request.app.state.config
    accounts = [a.name for a in config.accounts]
    return render(
        request, "trade.html",
        active="trade",
        title="记录交易",
        accounts=accounts,
        msg=msg,
        err=err,
    )


@router.post("/trade")
async def trade_submit(
    request: Request,
    action: str = Form(...),
    account: str = Form(...),
    code: str = Form(...),
    shares: int = Form(...),
    price: float = Form(...),
    note: str | None = Form(None),
):
    if action not in {"buy", "sell"}:
        return RedirectResponse(url="/trade?err=action 必须是 buy 或 sell", status_code=303)
    try:
        await run_in_threadpool(
            record_trade, account, code, shares, price, action, note or None,
        )
    except Exception as e:
        return RedirectResponse(url=f"/trade?err={e}", status_code=303)
    # 重新加载 config 里的 holdings（因为 record_trade 改了 yaml）
    from astock.config import load_config
    request.app.state.config = load_config()
    return RedirectResponse(
        url=f"/trade?msg={action.upper()} {code} × {shares} @ {price} 已记入 {account}",
        status_code=303,
    )
