"""飞书自定义机器人推送。

用户在飞书群里 → 群设置 → 添加机器人 → 自定义机器人 → 拿 webhook URL。
免费无上限，锁屏能响铃提示。
"""
from __future__ import annotations

import json
import subprocess


def push(webhook: str, title: str, body: str, timeout: int = 8) -> None:
    """发送 markdown 富文本消息到飞书 webhook。

    格式使用 msg_type=interactive（卡片），支持 markdown + 高亮 header。
    """
    if not webhook:
        return

    # 卡片消息（比 text 更醒目）
    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"content": title, "tag": "plain_text"},
                "template": "red",  # 红色 header 醒目
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": body,
                },
            ],
        },
    }

    subprocess.run(
        [
            "curl", "-s", "-X", "POST", webhook,
            "-H", "Content-Type: application/json",
            "-d", json.dumps(payload, ensure_ascii=False),
        ],
        capture_output=True, timeout=timeout + 5,
    )


def push_text(webhook: str, text: str, timeout: int = 8) -> None:
    """纯文本消息（fallback）。"""
    if not webhook:
        return
    payload = {"msg_type": "text", "content": {"text": text}}
    subprocess.run(
        [
            "curl", "-s", "-X", "POST", webhook,
            "-H", "Content-Type: application/json",
            "-d", json.dumps(payload, ensure_ascii=False),
        ],
        capture_output=True, timeout=timeout + 5,
    )
