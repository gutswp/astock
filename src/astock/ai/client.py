import os

import anthropic

from astock import PROJECT_ROOT

_LOADED = False


def load_env() -> None:
    """把 .env 文件读进 os.environ（含 NO_PROXY / http_proxy 等），幂等。"""
    global _LOADED
    if _LOADED:
        return
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        with env_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    _LOADED = True


def make_client() -> anthropic.Anthropic:
    load_env()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    kwargs: dict = {}
    if api_key:
        kwargs["api_key"] = api_key
    if auth_token:
        kwargs["auth_token"] = auth_token
    if base_url:
        kwargs["base_url"] = base_url
    return anthropic.Anthropic(**kwargs)
