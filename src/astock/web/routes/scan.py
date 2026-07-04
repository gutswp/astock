import dataclasses
import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from astock import DATA_DIR
from astock.screen.scanner import scan
from astock.web.deps import render

JOBS_PATH = DATA_DIR / "scan_jobs.jsonl"
_MAX_PERSIST = 20

router = APIRouter()


@dataclass
class ScanJob:
    id: str
    started_at: datetime
    stage: str = "启动中"
    current: int = 0
    total: int = 0
    status: str = "running"  # running / done / failed / cancelled
    finished_at: datetime | None = None
    results: list = field(default_factory=list)
    error: str | None = None
    cancel_flag: bool = False


_JOBS: dict[str, ScanJob] = {}
_LATEST: dict[str, str] = {"job_id": ""}  # 记住最近一次任务


def _serialize(job: ScanJob) -> dict:
    d = dataclasses.asdict(job)
    d["started_at"] = job.started_at.isoformat() if job.started_at else None
    d["finished_at"] = job.finished_at.isoformat() if job.finished_at else None
    return d


def _deserialize(d: dict) -> ScanJob:
    job = ScanJob(
        id=d["id"],
        started_at=datetime.fromisoformat(d["started_at"]) if d.get("started_at") else datetime.now(),
        stage=d.get("stage", ""),
        current=d.get("current", 0),
        total=d.get("total", 0),
        status=d.get("status", "done"),
        finished_at=datetime.fromisoformat(d["finished_at"]) if d.get("finished_at") else None,
        results=d.get("results") or [],
        error=d.get("error"),
    )
    return job


def _persist(job: ScanJob) -> None:
    """完成后 append 到 jsonl。仅落已完成状态。"""
    if job.status == "running":
        return
    JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JOBS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(_serialize(job), ensure_ascii=False) + "\n")


def restore_jobs() -> None:
    """启动时从磁盘恢复最近的扫描结果（只装 _MAX_PERSIST 条）."""
    if not JOBS_PATH.exists():
        return
    try:
        lines = JOBS_PATH.read_text(encoding="utf-8").splitlines()[-_MAX_PERSIST:]
    except Exception:
        return
    for line in lines:
        try:
            d = json.loads(line)
        except Exception:
            continue
        job = _deserialize(d)
        _JOBS[job.id] = job
        _LATEST["job_id"] = job.id  # 最后一条覆盖


def _run_scan_job(job: ScanJob, config) -> None:
    def cb(stage: str, current: int, total: int) -> None:
        job.stage = stage
        job.current = current
        job.total = total

    def should_stop() -> bool:
        return job.cancel_flag

    try:
        results = scan(config, silent=True, progress_cb=cb, should_stop=should_stop)
        job.results = results
        job.status = "cancelled" if job.cancel_flag else "done"
    except Exception as e:
        job.status = "failed"
        job.error = str(e)
    finally:
        job.finished_at = datetime.now()
        try:
            _persist(job)
        except Exception:
            pass


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


@router.post("/scan/cancel/{job_id}")
async def scan_cancel(request: Request, job_id: str):
    job = _JOBS.get(job_id)
    if job is None:
        return HTMLResponse('<div class="text-gray-500">任务不存在</div>')
    if job.status == "running":
        job.cancel_flag = True
    return render(request, "partials/scan_status.html", job=job)
