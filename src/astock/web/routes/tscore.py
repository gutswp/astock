from fastapi import APIRouter, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse
from starlette.concurrency import run_in_threadpool
import asyncio
import json

from astock.config import load_config
from astock.screen import t_signals_daemon
from astock.screen.t_trading import build_tscore_results, build_training_case
from astock.web.deps import render

router = APIRouter()


@router.get("/tscore")
async def tscore_page(request: Request, codes: str | None = None):
    request.app.state.config = load_config()
    picked = []
    if codes:
        seen = set()
        for chunk in codes.replace(",", " ").split():
            code = chunk.strip().zfill(6)
            if code.isdigit() and len(code) == 6 and code not in seen:
                seen.add(code)
                picked.append(code)

    results = await run_in_threadpool(
        build_tscore_results,
        request.app.state.config,
        picked or None,
    )
    code_value = " ".join(picked)
    return render(
        request,
        "tscore.html",
        active="tscore",
        title="开盘15分钟评分",
        results=results,
        codes=code_value,
    )


@router.get("/tscore/training")
async def tscore_training_page(
    request: Request,
    code: str = Query("000063"),
    day: str | None = None,
):
    code = code.strip().zfill(6)
    case = None
    error = None
    if not (code.isdigit() and len(code) == 6):
        error = "请输入 6 位股票代码"
    else:
        try:
            case = await run_in_threadpool(build_training_case, code, day, 5)
            if not case:
                error = "暂无可用分时训练样本"
        except Exception as exc:
            error = f"加载训练样本失败：{exc}"

    return render(
        request,
        "tscore_training.html",
        active="tscore",
        title="做T训练",
        code=code,
        day=day or "",
        case=case,
        error=error,
        labels=["强势", "偏强", "震荡", "偏弱", "弱势"],
    )


@router.get("/tscore/{code}")
async def tscore_detail_page(request: Request, code: str):
    code = code.strip().zfill(6)
    if not (code.isdigit() and len(code) == 6):
        raise HTTPException(status_code=404, detail="非法股票代码")

    request.app.state.config = load_config()
    results = await run_in_threadpool(
        build_tscore_results,
        request.app.state.config,
        [code],
    )
    result = results[0] if results else None
    dcfg = t_signals_daemon._load_daemon_config()
    return render(
        request,
        "tscore_detail.html",
        active="tscore",
        title=f"{code} · 做T信号",
        code=code,
        result=result,
        daemon_interval=int(dcfg.get("interval_seconds", 5)),
    )


@router.get("/tscore/stream/{code}")
async def tscore_stream(request: Request, code: str):
    """SSE 端点：按 sse_poll_seconds（默认 1s）检查快照签名，有变化立即推。"""
    code = code.strip().zfill(6)
    if not (code.isdigit() and len(code) == 6):
        raise HTTPException(status_code=404, detail="非法股票代码")

    poll_seconds = t_signals_daemon.get_sse_poll_seconds()

    async def event_gen():
        last_signature: str = ""
        first = True
        last_ping = 0.0
        # 首连接：如果快照不存在，即时算一次
        snap = t_signals_daemon.get_snapshot(code)
        if snap is None:
            snap = await run_in_threadpool(t_signals_daemon.compute_now, code)

        while True:
            if await request.is_disconnected():
                break

            snap = t_signals_daemon.get_snapshot(code)
            if snap is None and first:
                snap = await run_in_threadpool(t_signals_daemon.compute_now, code)

            now = asyncio.get_event_loop().time()
            if snap:
                sig = f"{len(snap['signals'])}-{snap['updated_at']}"
                if sig != last_signature or first:
                    last_signature = sig
                    last_ping = now
                    yield {"event": "signals", "data": json.dumps(snap, ensure_ascii=False)}
                    first = False
                elif now - last_ping >= 15:
                    # 保活，防 SSE 连接被代理/浏览器判超时
                    last_ping = now
                    yield {"event": "ping", "data": snap.get("updated_at", "")}
            elif first or now - last_ping >= 15:
                last_ping = now
                yield {"event": "ping", "data": ""}
                first = False
            await asyncio.sleep(poll_seconds)

    return EventSourceResponse(event_gen())
