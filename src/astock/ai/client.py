import os

import anthropic

from astock import PROJECT_ROOT


def _load_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    with env_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def make_client() -> anthropic.Anthropic:
    _load_env()
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
