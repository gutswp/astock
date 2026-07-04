from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from astock.config import load_config
from astock.web.routes import (
    ai as ai_routes,
    alerts as alerts_routes,
    api as api_routes,
    dashboard as dashboard_routes,
    journal as journal_routes,
    scan as scan_routes,
    trade as trade_routes,
)

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

app = FastAPI(title="AStock", docs_url=None, redoc_url=None)
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


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
