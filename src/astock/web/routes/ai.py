import asyncio
from datetime import datetime
from pathlib import Path

import anthropic
import markdown as md_lib
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from astock import DATA_DIR
from astock.ai.advisor import generate_advise, stream_advise
from astock.ai.analyst import generate_analysis, load_cached_analysis, stream_analysis
from astock.ai.reviewer import generate_review, stream_review
from astock.data.provider import get_spot
from astock.web.deps import render

router = APIRouter()


def _md(text: str) -> str:
    return md_lib.markdown(text, extensions=["tables", "fenced_code"])


def _list_reports(suffix: str) -> list[dict]:
    reports_dir = DATA_DIR / "reports"
    if not reports_dir.exists():
        return []
    entries = []
    for p in sorted(reports_dir.glob(f"*.{suffix}.md"), reverse=True):
        stem = p.stem.replace(f".{suffix}", "")
        entries.append({"date": stem, "path": p.name, "size": p.stat().st_size})
    return entries


@router.get("/advise")
async def advise_page(request: Request):
    return render(
        request, "advise.html",
        active="advise",
        title="AI 决策报告",
        history=_list_reports("advise"),
    )


@router.post("/advise/run")
async def advise_run(request: Request):
    """点击生成后返回流式外壳（含 EventSource JS）。"""
    return render(
        request, "partials/ai_stream.html",
        title=f"AI 决策报告 · {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        stream_url="/advise/stream",
    )


@router.get("/advise/stream")
async def advise_stream(request: Request):
    config = request.app.state.config
    gen = stream_advise(config)
    async_gen = iterate_in_threadpool(gen)

    async def event_source():
        async for event, data in async_gen:
            if await request.is_disconnected():
                break
            yield {"event": event, "data": data}
    return EventSourceResponse(event_source())


@router.get("/advise/history/{date}")
async def advise_history(request: Request, date: str):
    path = DATA_DIR / "reports" / f"{date}.advise.md"
    if not path.exists():
        return HTMLResponse('<div class="text-gray-500 p-4">报告不存在</div>')
    text = path.read_text(encoding="utf-8")
    return render(
        request, "partials/ai_result.html",
        title=f"AI 决策报告 · {date}",
        html=_md(text),
        saved_path=str(path),
    )


@router.get("/review")
async def review_page(request: Request):
    return render(
        request, "review.html",
        active="review",
        title="AI 复盘",
        history=_list_reports("review"),
    )


@router.post("/review/run")
async def review_run(request: Request, days: int = Form(90)):
    return render(
        request, "partials/ai_stream.html",
        title=f"AI 复盘 · 最近 {days} 天",
        stream_url=f"/review/stream?days={days}",
    )


@router.get("/review/stream")
async def review_stream(request: Request, days: int = 90):
    config = request.app.state.config
    gen = stream_review(config, days)
    async_gen = iterate_in_threadpool(gen)

    async def event_source():
        async for event, data in async_gen:
            if await request.is_disconnected():
                break
            yield {"event": event, "data": data}
    return EventSourceResponse(event_source())


@router.get("/review/history/{date}")
async def review_history(request: Request, date: str):
    path = DATA_DIR / "reports" / f"{date}.review.md"
    if not path.exists():
        return HTMLResponse('<div class="text-gray-500 p-4">复盘不存在</div>')
    text = path.read_text(encoding="utf-8")
    return render(
        request, "partials/ai_result.html",
        title=f"AI 复盘 · {date}",
        html=_md(text),
        saved_path=str(path),
    )


@router.get("/analyze/{code}")
async def analyze_page(request: Request, code: str, force: bool = False):
    code = code.zfill(6)
    # 提前拿一下名字，展示更友好
    name = code
    try:
        spot = await run_in_threadpool(get_spot, [code])
        if not spot.empty:
            name = str(spot.iloc[0]["名称"])
    except Exception:
        pass
    cached_html = None
    if not force:
        cached = load_cached_analysis(code)
        if cached:
            cached_html = _md(cached)
    return render(
        request, "analyze.html",
        code=code, name=name, active="",
        cached_html=cached_html,
    )


@router.post("/analyze/{code}/run")
async def analyze_run(request: Request, code: str):
    return render(
        request, "partials/ai_stream.html",
        title=f"分析 · {code}",
        stream_url=f"/analyze/{code}/stream",
    )


@router.get("/analyze/{code}/stream")
async def analyze_stream(request: Request, code: str):
    config = request.app.state.config
    gen = stream_analysis(code, config)
    async_gen = iterate_in_threadpool(gen)

    async def event_source():
        async for event, data in async_gen:
            if await request.is_disconnected():
                break
            yield {"event": event, "data": data}
    return EventSourceResponse(event_source())
