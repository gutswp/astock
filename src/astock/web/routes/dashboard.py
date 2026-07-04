from fastapi import APIRouter, Request

from astock.data.provider import get_indices
from astock.portfolio.journal import load_trades
from astock.portfolio.manager import build_portfolio
from astock.web.deps import render

router = APIRouter()


def _dashboard_context(config) -> dict:
    summary = build_portfolio(config)
    indices = get_indices()
    recent_trades = load_trades()[-5:][::-1]

    # 今日盈亏 = Σ market_value * daily_change / 100
    today_pnl = sum(
        p.market_value * (p.daily_change / 100)
        for p in summary.positions
    )

    industry_map: dict[str, float] = {}
    for p in summary.positions:
        ind = p.industry or "未知"
        industry_map[ind] = industry_map.get(ind, 0) + p.market_value
    industry_rows = sorted(industry_map.items(), key=lambda x: -x[1])
    total = summary.total_market_value or 1
    industry_rows = [
        {"name": name, "value": val, "pct": val / total * 100}
        for name, val in industry_rows
    ]

    indices_rows: list[dict] = []
    if not indices.empty:
        for _, r in indices.iterrows():
            indices_rows.append({
                "name": r["名称"],
                "code": r["代码"],
                "price": float(r["最新价"]),
                "change_pct": float(r["涨跌幅"]),
            })

    return {
        "summary": summary,
        "positions": summary.positions,
        "indices": indices_rows,
        "industry_rows": industry_rows,
        "today_pnl": today_pnl,
        "recent_trades": recent_trades,
    }


@router.get("/")
async def dashboard(request: Request):
    ctx = _dashboard_context(request.app.state.config)
    return render(request, "dashboard.html", active="dashboard", **ctx)


@router.get("/partials/portfolio")
async def portfolio_partial(request: Request):
    ctx = _dashboard_context(request.app.state.config)
    return render(request, "partials/portfolio_table.html", **ctx)


@router.get("/partials/kpi")
async def kpi_partial(request: Request):
    ctx = _dashboard_context(request.app.state.config)
    return render(request, "partials/kpi_row.html", **ctx)
