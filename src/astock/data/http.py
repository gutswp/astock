import subprocess
import threading
import time
from functools import wraps
from urllib.parse import urlparse

SINA_HEADERS = {"Referer": "https://finance.sina.com.cn"}

# 节流：每个 host 最小间隔（秒）。锁是全局的，会串行化跨线程调用同一 host。
# 所以数值要保守，让并发扫描能真跑起来。eastmoney 稍严；sina 宽松。
_MIN_INTERVAL = {
    "push2delay.eastmoney.com": 0.08,
    "push2his.eastmoney.com": 0.08,
    "push2.eastmoney.com": 0.08,
    "search-api-web.eastmoney.com": 0.15,
    "hq.sinajs.cn": 0.01,
    "money.finance.sina.com.cn": 0.01,
    "vip.stock.finance.sina.com.cn": 0.02,
}
_DEFAULT_INTERVAL = 0.02
_last_call: dict[str, float] = {}
_lock = threading.Lock()


def _throttle(host: str) -> None:
    interval = _MIN_INTERVAL.get(host, _DEFAULT_INTERVAL)
    with _lock:
        last = _last_call.get(host, 0.0)
        now = time.monotonic()
        wait = last + interval - now
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.monotonic()


def curl_get(url: str, headers: dict | None = None, timeout: int = 15, encoding: str = "utf-8") -> str:
    host = urlparse(url).hostname or ""
    if host:
        _throttle(host)
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
