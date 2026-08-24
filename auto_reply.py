#!/usr/bin/env python3
"""
DeskAgent 自动回复引擎

AutoReplyWorker 后台线程轮询 messages 表中未处理的消息：
  1. 按配置过滤：是否开启、范围、白名单、黑名单、仅被 @ 时回复
  2. 冷却时间内同一会话的新消息直接跳过（避免刷屏）
  3. 调 LLM 生成回复（可能决定不回复）
  4. 发送并落库，标记已处理
"""
from __future__ import annotations

import logging
import threading
import time

import config
import llm
import onebot_client
import safety
import storage

logger = logging.getLogger("auto_reply")


class AutoReplyWorker:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        # 每个会话（source_id）上次自动回复的时间，用于冷却
        self._last_reply: dict[str, float] = {}

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="auto-reply-worker", daemon=True)
        self._thread.start()
        logger.info("自动回复 Worker 已启动")

    def stop(self) -> None:
        self._stop_event.set()
        logger.info("自动回复 Worker 已停止")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as exc:  # 任何异常都不能杀死 Worker
                logger.exception("自动回复轮询出错: %s", exc)
            self._stop_event.wait(config.WORKER_POLL_SECONDS)

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    def _poll_once(self) -> None:
        cfg = storage.get_auto_reply_config()
        if not cfg["enabled"]:
            return

        rows = storage.get_unhandled_messages(limit=50)
        for row in rows:
            msg = {
                "id": row["id"],
                "type": row["message_type"],
                "source_id": row["source_id"],
                "sender_id": row["sender_id"],
                "sender_name": row["sender_name"],
                "content": row["content"],
                "at_self": f"[CQ:at,qq={config.OWNER_ID}]" in (row["content"] or ""),
            }
            should_reply = self._should_reply(cfg, msg)

            if should_reply:
                # 入站拦截：对方消息索要敏感信息时，绝不自动回复，转人工提醒
                inbound_reason = safety.check_inbound(msg["content"])
                if inbound_reason:
                    storage.add_alert(
                        row["message_id"], msg["source_id"], msg["sender_name"],
                        msg["content"], inbound_reason,
                    )
                    storage.mark_handled(row["id"], None)
                    logger.warning(
                        "⚠️  敏感内容拦截：%s(%s) %s —— 已转人工提醒，不自动回复",
                        msg["sender_name"], msg["source_id"], inbound_reason,
                    )
                    continue

                context = storage.get_memory_context(msg["source_id"])
                reply = llm.generate_auto_reply(msg, cfg["persona"], context)

                # 出站拦截：LLM 生成的回复含敏感信息时丢弃
                outbound_reason = safety.check_outbound(reply or "")
                if outbound_reason:
                    storage.add_alert(
                        row["message_id"], msg["source_id"], msg["sender_name"],
                        msg["content"], f"出站拦截：{outbound_reason}",
                    )
                    storage.mark_handled(row["id"], None)
                    logger.warning("⚠️  出站拦截：%s —— 回复未发送", outbound_reason)
                    continue

                if reply and not self._in_cooldown(msg["source_id"]):
                    self._send(msg, reply)
                    storage.mark_handled(row["id"], reply, is_auto_reply=True)
                    self._last_reply[msg["source_id"]] = time.time()
                    logger.info("自动回复 -> %s(%s): %s", msg["sender_name"], msg["source_id"], reply[:50])
                else:
                    # LLM 决定不回 / 冷却中：静默跳过
                    storage.mark_handled(row["id"], None)
                    if reply:
                        logger.info("冷却中，跳过回复 %s", msg["source_id"])
            else:
                storage.mark_handled(row["id"], None)

    # ------------------------------------------------------------------
    # 过滤规则
    # ------------------------------------------------------------------

    def _should_reply(self, cfg: dict, msg: dict) -> bool:
        # 范围：私聊 / 群聊
        if cfg["scope"] == "private" and msg["type"] != "private":
            return False
        if cfg["scope"] == "group" and msg["type"] != "group":
            return False

        source = msg["source_id"]

        # 黑名单：私聊按会话、群聊按群号或发言人
        blacklist = set(cfg["blacklist"])
        if msg["type"] == "private":
            if source in blacklist or msg["sender_name"] in blacklist:
                return False
        else:
            if source in blacklist or msg["sender_id"] in blacklist:
                return False

        # 白名单：非空时只回复列表内的会话
        whitelist = set(cfg["whitelist"])
        if whitelist:
            match = source in whitelist or msg["sender_name"] in whitelist or msg["sender_id"] in whitelist
            if not match:
                return False

        # 仅被 @ 时回复（只对群聊生效）
        if cfg["only_when_at"] and msg["type"] == "group" and not msg["at_self"]:
            return False

        return True

    def _in_cooldown(self, source_id: str) -> bool:
        last = self._last_reply.get(source_id)
        if last is None:
            return False
        return time.time() - last < config.REPLY_COOLDOWN_SECONDS

    # ------------------------------------------------------------------
    # 发送
    # ------------------------------------------------------------------

    def _send(self, msg: dict, reply: str) -> None:
        if msg["type"] == "private":
            onebot_client.send_private_msg(msg["source_id"], reply)
            # 自己发出的也入库，避免下次把"自己的回复"当成新消息（真实 OneBot 的 message_sent 事件也会入库去重）
            storage.save_message(
                message_id=f"auto-{msg['source_id']}-{time.time_ns()}",
                message_type="private",
                source_id=msg["source_id"],
                sender_id=config.OWNER_ID,
                sender_name="我",
                content=reply,
                is_self=True,
                is_auto_reply=True,
            )
        else:
            onebot_client.send_group_msg(msg["source_id"], reply)
            storage.save_message(
                message_id=f"auto-{msg['source_id']}-{time.time_ns()}",
                message_type="group",
                source_id=msg["source_id"],
                sender_id=config.OWNER_ID,
                sender_name="我",
                content=reply,
                is_self=True,
                is_auto_reply=True,
            )


# 全局单例
worker = AutoReplyWorker()
