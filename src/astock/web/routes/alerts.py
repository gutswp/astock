from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from astock.screen.alerts import (
    ALERT_TYPES,
    add_watch_alert,
    check_watch,
    load_watchlist,
    remove_watch,
)
from astock.web.deps import render

router = APIRouter()


@router.get("/alerts")
async def alerts_page(request: Request, msg: str | None = None, err: str | None = None):
    return render(
        request, "alerts.html",
        active="alerts",
        title="预警管理",
        watches=load_watchlist(),
        alert_types=sorted(ALERT_TYPES),
        msg=msg,
        err=err,
    )


@router.post("/alerts/add")
async def alerts_add(
    request: Request,
    code: str = Form(...),
    alert_type: str = Form(..., alias="type"),
    value: float | None = Form(None),
    period: int | None = Form(None),
):
    try:
        w = add_watch_alert(code, alert_type, value, period)
    except ValueError as e:
        return RedirectResponse(url=f"/alerts?err={e}", status_code=303)
    return RedirectResponse(
        url=f"/alerts?msg=已添加 {w.code} {w.name} 的 {alert_type} 规则",
        status_code=303,
    )


@router.post("/alerts/rm/{code}")
async def alerts_rm_watch(request: Request, code: str):
    try:
        remove_watch(code)
    except ValueError as e:
        return RedirectResponse(url=f"/alerts?err={e}", status_code=303)
    return RedirectResponse(url=f"/alerts?msg=已移除 {code}", status_code=303)


@router.post("/alerts/rm/{code}/{index}")
async def alerts_rm_rule(request: Request, code: str, index: int):
    try:
        remove_watch(code, index=index)
    except ValueError as e:
        return RedirectResponse(url=f"/alerts?err={e}", status_code=303)
    return RedirectResponse(url=f"/alerts?msg=已移除 {code} 规则 #{index}", status_code=303)


@router.post("/alerts/check")
async def alerts_check(request: Request):
    watches = load_watchlist()
    all_hits = []
    for w in watches:
        try:
            hits = await run_in_threadpool(check_watch, w)
        except Exception:
            hits = []
        all_hits.extend(hits)
    return render(request, "partials/alerts_hits.html", hits=all_hits)
