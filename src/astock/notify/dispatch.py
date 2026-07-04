"""统一分发到所有配置的通道。"""
from __future__ import annotations

from pathlib import Path

import yaml

from astock import CONFIG_DIR
from astock.notify import mail, serverchan


def _notify_config() -> dict:
    p = CONFIG_DIR / "settings.yaml"
    if not p.exists():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return raw.get("notify") or {}


def should_push_ai(kind: str) -> bool:
    """kind ∈ {'advise', 'review'}."""
    cfg = _notify_config()
    return bool((cfg.get("push_ai_reports") or {}).get(kind))


def notify(title: str, body: str) -> list[str]:
    """按 settings.yaml.notify 配置发送。返回成功的通道名列表."""
    cfg = _notify_config()
    sent: list[str] = []

    sc = cfg.get("serverchan") or {}
    if sc.get("enabled") and sc.get("sendkey"):
        try:
            serverchan.push(sc["sendkey"], title, body)
            sent.append("serverchan")
        except Exception:
            pass

    m = cfg.get("mail") or {}
    if m.get("enabled") and m.get("smtp_host") and m.get("to"):
        try:
            mail.push(
                smtp_host=m["smtp_host"],
                smtp_port=int(m.get("smtp_port", 465)),
                user=m.get("user", ""),
                password=m.get("password", ""),
                to=m["to"],
                title=title,
                body=body,
                use_ssl=bool(m.get("use_ssl", True)),
            )
            sent.append("mail")
        except Exception:
            pass

    return sent
