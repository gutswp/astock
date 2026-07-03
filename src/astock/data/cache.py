import hashlib
import json
import time
from pathlib import Path

from astock import DATA_DIR

CACHE_DIR = DATA_DIR / "cache"


def _cache_path(key: str) -> Path:
    h = hashlib.md5(key.encode()).hexdigest()[:12]
    return CACHE_DIR / f"{h}.json"


def get(key: str, ttl: int) -> dict | list | None:
    p = _cache_path(key)
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    if time.time() - data["ts"] > ttl:
        p.unlink(missing_ok=True)
        return None
    return data["val"]


def put(key: str, val: dict | list) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = _cache_path(key)
    p.write_text(json.dumps({"ts": time.time(), "val": val}, ensure_ascii=False), encoding="utf-8")


def clear() -> None:
    if CACHE_DIR.exists():
        for f in CACHE_DIR.glob("*.json"):
            f.unlink()
