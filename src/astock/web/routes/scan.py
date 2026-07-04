import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from astock.screen.scanner import scan
from astock.web.deps import render

router = APIRouter()


@dataclass
class ScanJob:
    id: str
    started_at: datetime
    stage: str = "启动中"
    current: int = 0
    total: int = 0
    status: str = "running"  # running / done / failed
    finished_at: datetime | None = None
    results: list = field(default_factory=list)
    error: str | None = None


_JOBS: dict[str, ScanJob] = {}
_LATEST: dict[str, str] = {"job_id": ""}  # 记住最近一次任务


def _run_scan_job(job: ScanJob, config) -> None:
    def cb(stage: str, current: int, total: int) -> None:
        job.stage = stage
        job.current = current
        job.total = total

    try:
        results = scan(config, silent=True, progress_cb=cb)
        job.results = results
        job.status = "done"
    except Exception as e:
        job.status = "failed"
        job.error = str(e)
    finally:
        job.finished_at = datetime.now()


@router.get("/scan")
async def scan_page(request: Request):
    latest_id = _LATEST["job_id"]
    latest_job = _JOBS.get(latest_id) if latest_id else None
    return render(
        request, "scan.html",
        active="scan",
        title="机会扫描",
        latest_job=latest_job,
    )


@router.post("/scan/start")
async def scan_start(request: Request):
    config = request.app.state.config
    job = ScanJob(id=str(uuid.uuid4())[:8], started_at=datetime.now())
    _JOBS[job.id] = job
    _LATEST["job_id"] = job.id
    threading.Thread(target=_run_scan_job, args=(job, config), daemon=True).start()
    return render(request, "partials/scan_status.html", job=job)


@router.get("/scan/status/{job_id}")
async def scan_status(request: Request, job_id: str):
    job = _JOBS.get(job_id)
    if job is None:
        return HTMLResponse('<div class="text-gray-500">任务不存在</div>')
    return render(request, "partials/scan_status.html", job=job)
