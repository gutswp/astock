from datetime import datetime

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from astock.config import AppConfig


def get_config(request: Request) -> AppConfig:
    return request.app.state.config


def get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def render(request: Request, template: str, **ctx) -> HTMLResponse:
    """Wrapper around Jinja2Templates.TemplateResponse using the new starlette
    signature (request-first). Also injects a `now` timestamp for the nav bar."""
    ctx.setdefault("now", datetime.now().strftime("%Y-%m-%d %H:%M"))
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(request, template, ctx)
