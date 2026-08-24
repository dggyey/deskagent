#!/usr/bin/env python3
"""
DeskAgent 消息监听器

连接 OneBot（LLOneBot 或 mock）的正向 WebSocket：
  - message 事件：他人或本人的消息，入库（message_id 去重）
  - message_sent 事件：自己发出的消息回执，同样入库

断线自动重连。以守护线程方式运行，随主进程退出。
"""
from __future__ import annotations

import json
import logging
import threading
import time

from websocket import WebSocketApp, WebSocketConnectionClosedException

import config
import storage

logger = logging.getLogger("listener")


def _handle_message_event(event: dict, is_self_hint: bool = False) -> None:
    """把 OneBot message 事件标准化后写入数据库。"""
    message_id = str(event.get("message_id") or f"evt-{time.time_ns()}")
    message_type = event.get("message_type") or "private"

    if message_type == "group":
        source_id = str(event.get("group_id") or "")
    else:
        source_id = str(event.get("user_id") or "")

    sender = event.get("sender") or {}
    sender_id = str(event.get("user_id") or "")
    sender_name = sender.get("nickname") or sender.get("card") or sender_id

    # OneBot 消息段数组 -> 纯文本
    content = _content_to_text(event.get("message") or event.get("raw_message") or "")

    # message_sent 事件本身就是机器人自己的消息，直接认定为 is_self
    is_self = is_self_hint or bool(event.get("is_self"))
    if not is_self and config.OWNER_ID:
        # 真实 LLOneBot 不推 is_self，按发送者判断
        is_self = sender_id == config.OWNER_ID

    is_new = storage.save_message(
        message_id=message_id,
        message_type=message_type,
        source_id=source_id,
        sender_id=sender_id,
        sender_name=sender_name,
        content=content,
        is_self=is_self,
    )
    if is_new and not is_self:
        logger.info("收到消息 [%s] %s(%s): %s", message_type, sender_name, source_id, content[:50])


def _content_to_text(message) -> str:
    """兼容纯文本和 OneBot 消息段数组两种格式。"""
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        parts = []
        for seg in message:
            if isinstance(seg, dict) and seg.get("type") == "text":
                parts.append((seg.get("data") or {}).get("text", ""))
        return "".join(parts)
    return str(message)


class OneBotListener:
    def __init__(self, ws_url: str | None = None) -> None:
        self.ws_url = ws_url or config.ONEBOT_WS_URL
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="onebot-listener", daemon=True)
        self._thread.start()
        logger.info("消息监听器已启动: %s", self.ws_url)

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                app = WebSocketApp(
                    self.ws_url,
                    on_message=self._on_message,
                    on_open=lambda _ws: logger.info("WebSocket 已连接"),
                    on_error=lambda _ws, err: logger.warning("WebSocket 出错: %s", err),
                )
                app.run_forever(ping_interval=30, ping_timeout=10)
            except WebSocketConnectionClosedException:
                pass
            except Exception as exc:
                logger.warning("WebSocket 连接失败: %s", exc)
            if not self._stop_event.is_set():
                logger.info("3 秒后重连...")
                self._stop_event.wait(3)

    def _on_message(self, ws, raw: str) -> None:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return

        post_type = event.get("post_type")
        if post_type == "message":
            _handle_message_event(event)
        elif post_type == "message_sent":
            # 自己发出的消息回执，强制标记为 is_self，防止自动回复把自己的消息当成新消息刷屏
            _handle_message_event(event, is_self_hint=True)


# 全局单例
listener = OneBotListener()
