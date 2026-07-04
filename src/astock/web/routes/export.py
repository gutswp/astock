import csv
import io
from datetime import datetime

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from astock.portfolio.journal import load_trades
from astock.portfolio.manager import build_portfolio

router = APIRouter(prefix="/export")


def _csv_response(rows: list[list], filename: str) -> Response:
    buf = io.StringIO()
    buf.write("﻿")  # BOM，方便 Excel 打开中文
    writer = csv.writer(buf)
    writer.writerows(rows)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/portfolio.csv")
async def portfolio_csv(request: Request):
    config = request.app.state.config
    summary = await run_in_threadpool(build_portfolio, config)
    total = summary.total_market_value or 1
    rows = [[
        "代码", "名称", "行业", "账户", "持股", "成本", "现价",
        "市值", "占比%", "盈亏", "盈亏%", "今日%",
    ]]
    for p in summary.positions:
        rows.append([
            p.code, p.name, p.industry, " ".join(p.accounts),
            p.total_shares, f"{p.avg_cost:.3f}", f"{p.current_price:.3f}",
            f"{p.market_value:.2f}", f"{p.market_value / total * 100:.2f}",
            f"{p.profit:.2f}", f"{p.profit_pct:.2f}", f"{p.daily_change:.2f}",
        ])
    fn = f"portfolio-{datetime.now():%Y%m%d}.csv"
    return _csv_response(rows, fn)


@router.get("/trades.csv")
async def trades_csv(
    code: str | None = Query(None),
    account: str | None = Query(None),
    days: int | None = Query(None),
):
    trades = load_trades(code=code or None, account=account or None, days=days)
    rows = [[
        "时间", "账户", "方向", "代码", "名称", "量", "价", "金额",
        "变动前持股", "变动前成本", "变动后持股", "变动后成本", "备注",
    ]]
    for t in trades:
        rows.append([
            t.get("ts", ""), t.get("account", ""), t.get("action", ""),
            t.get("code", ""), t.get("name", ""),
            t.get("shares", ""), t.get("price", ""),
            f"{t.get('shares', 0) * t.get('price', 0):.2f}",
            t.get("prev_shares", ""), t.get("prev_cost", ""),
            t.get("new_shares", ""), t.get("new_cost", ""),
            t.get("note", "") or "",
        ])
    fn = f"trades-{datetime.now():%Y%m%d}.csv"
    return _csv_response(rows, fn)


@router.get("/scan/{job_id}.csv")
async def scan_csv(job_id: str):
    from astock.web.routes.scan import _JOBS
    job = _JOBS.get(job_id)
    if job is None:
        return Response("job not found", status_code=404)
    rows = [["得分", "代码", "名称", "现价", "涨跌%", "量比", "信号"]]
    for r in job.results:
        rows.append([
            r["score"], r["code"], r["name"],
            f"{r['price']:.3f}", f"{r['change_pct']:.2f}",
            f"{r['volume_ratio']:.2f}", " / ".join(r["signals"]),
        ])
    fn = f"scan-{job_id}.csv"
    return _csv_response(rows, fn)
