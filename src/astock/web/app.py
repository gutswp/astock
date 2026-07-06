from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from astock.ai.client import load_env
from astock.config import load_config
from astock.screen import daemon as alert_daemon

load_env()  # 让 NO_PROXY / http_proxy 等在导入其它模块前生效
from astock.web.routes import (
    ai as ai_routes,
    alerts as alerts_routes,
    api as api_routes,
    dashboard as dashboard_routes,
    export as export_routes,
    journal as journal_routes,
    scan as scan_routes,
    tools as tools_routes,
    trade as trade_routes,
    tscore as tscore_routes,
)

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

@asynccontextmanager
async def _lifespan(app: FastAPI):
    from astock.web.routes.scan import restore_jobs
    restore_jobs()
    started = alert_daemon.start()
    app.state.alert_daemon = started
    yield
    if started:
        alert_daemon.stop()


app = FastAPI(title="AStock", docs_url=None, redoc_url=None, lifespan=_lifespan)
app.state.config = load_config()

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.state.templates = templates

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(dashboard_routes.router)
app.include_router(ai_routes.router)
app.include_router(trade_routes.router)
app.include_router(journal_routes.router)
app.include_router(scan_routes.router)
app.include_router(alerts_routes.router)
app.include_router(api_routes.router)
app.include_router(export_routes.router)
app.include_router(tools_routes.router)
app.include_router(tscore_routes.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
