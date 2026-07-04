from datetime import datetime
from pathlib import Path

import anthropic
import markdown as md_lib
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool

from astock import DATA_DIR
from astock.ai.advisor import generate_advise
from astock.ai.analyst import generate_analysis
from astock.ai.reviewer import generate_review
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
    config = request.app.state.config
    try:
        advice, path = await run_in_threadpool(generate_advise, config)
    except anthropic.AuthenticationError:
        return HTMLResponse('<div class="text-up p-4">API Key 无效或未设置</div>', status_code=200)
    except Exception as e:
        return HTMLResponse(f'<div class="text-up p-4">生成失败: {e}</div>', status_code=200)
    return render(
        request, "partials/ai_result.html",
        title=f"AI 决策报告 · {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        html=_md(advice),
        saved_path=path,
    )


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
    config = request.app.state.config
    try:
        result = await run_in_threadpool(generate_review, config, days)
    except anthropic.AuthenticationError:
        return HTMLResponse('<div class="text-up p-4">API Key 无效或未设置</div>')
    except Exception as e:
        return HTMLResponse(f'<div class="text-up p-4">生成失败: {e}</div>')
    if result is None:
        return HTMLResponse(
            '<div class="card p-6 text-center text-gray-400">'
            '尚无交易记录。等你用 <code class="text-white">astock buy/sell -n "..."</code> '
            '或在交易页记几笔后再回来复盘。</div>'
        )
    review, path = result
    return render(
        request, "partials/ai_result.html",
        title=f"AI 复盘 · 最近 {days} 天",
        html=_md(review),
        saved_path=path,
    )


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
async def analyze_page(request: Request, code: str):
    code = code.zfill(6)
    # 提前拿一下名字，展示更友好
    name = code
    try:
        spot = await run_in_threadpool(get_spot, [code])
        if not spot.empty:
            name = str(spot.iloc[0]["名称"])
    except Exception:
        pass
    return render(request, "analyze.html", code=code, name=name, active="")


@router.post("/analyze/{code}/run")
async def analyze_run(request: Request, code: str):
    config = request.app.state.config
    try:
        result = await run_in_threadpool(generate_analysis, code, config)
    except anthropic.AuthenticationError:
        return HTMLResponse('<div class="text-up p-4">API Key 无效或未设置</div>')
    except Exception as e:
        return HTMLResponse(f'<div class="text-up p-4">分析失败: {e}</div>')
    return render(
        request, "partials/ai_result.html",
        title=f"分析 · {code}",
        html=_md(result),
    )
