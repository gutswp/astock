from fastapi import APIRouter, Query, Request

from astock.portfolio.journal import load_trades
from astock.web.deps import render

router = APIRouter()


@router.get("/journal")
async def journal_page(
    request: Request,
    code: str | None = Query(None),
    account: str | None = Query(None),
    days: int | None = Query(None),
):
    trades = load_trades(code=code or None, account=account or None, days=days)
    trades = list(reversed(trades))  # 最新的在前
    config = request.app.state.config
    accounts = [a.name for a in config.accounts]
    return render(
        request, "journal.html",
        active="journal",
        title="交易日志",
        trades=trades,
        accounts=accounts,
        f_code=code or "",
        f_account=account or "",
        f_days=days or "",
    )
