import subprocess
import time
from functools import wraps

SINA_HEADERS = {"Referer": "https://finance.sina.com.cn"}


def curl_get(url: str, headers: dict | None = None, timeout: int = 15, encoding: str = "utf-8") -> str:
    cmd = ["curl", "-s", "--connect-timeout", str(timeout), url]
    if headers:
        for k, v in headers.items():
            cmd.extend(["-H", f"{k}: {v}"])
    result = subprocess.run(cmd, capture_output=True, timeout=timeout + 5)
    if result.returncode != 0:
        raise ConnectionError(f"curl failed: {result.stderr.decode(errors='replace')}")
    return result.stdout.decode(encoding, errors="replace")


def retry(fn=None, *, retries: int = 3, delay: int = 2):
    """Retry decorator. Usable as `@retry` or `@retry(retries=5)`."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            last_err = None
            for i in range(retries):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    last_err = e
                    if i < retries - 1:
                        time.sleep(delay * (i + 1))
            raise last_err
        return wrapper
    return decorator if fn is None else decorator(fn)
