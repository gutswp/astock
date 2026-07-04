import subprocess
from urllib.parse import quote

SC_URL = "https://sctapi.ftqq.com/{key}.send"


def push(sendkey: str, title: str, desp: str, timeout: int = 8) -> None:
    """Server 酱推送。sendkey 从 https://sct.ftqq.com 获取。"""
    if not sendkey:
        return
    url = SC_URL.format(key=sendkey)
    payload = f"title={quote(title)}&desp={quote(desp)}"
    subprocess.run(
        ["curl", "-s", "-X", "POST", url,
         "-H", "Content-Type: application/x-www-form-urlencoded",
         "-d", payload],
        capture_output=True, timeout=timeout + 5,
    )
