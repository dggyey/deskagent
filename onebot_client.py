#!/usr/bin/env python3
"""
OneBot HTTP 客户端（同步版，供监听器/Worker 线程使用）

mock 后端和真实 LLOneBot 共用同一组 API。
"""
from __future__ import annotations

import uuid

import httpx

import config


def _url(path: str) -> str:
    return config.ONEBOT_HTTP_URL.rstrip("/") + path


def _post(path: str, payload: dict) -> dict:
    resp = httpx.post(_url(path), json=payload, timeout=10.0)
    resp.raise_for_status()
    return resp.json()


def _get(path: str) -> dict:
    resp = httpx.get(_url(path), timeout=10.0)
    resp.raise_for_status()
    return resp.json()


def send_private_msg(user_id: str, content: str) -> str:
    """发送私聊消息，返回 message_id。"""
    data = _post("/send_private_msg", {"user_id": user_id, "message": content})
    mid = (data.get("data") or {}).get("message_id")
    return mid or f"sent-{uuid.uuid4().hex[:8]}"


def send_group_msg(group_id: str, content: str, at_members: list[str] | None = None) -> str:
    """发送群消息，返回 message_id。"""
    message = content
    for member in at_members or []:
        message = f"[CQ:at,qq={member}] " + message
    data = _post("/send_group_msg", {"group_id": group_id, "message": message})
    mid = (data.get("data") or {}).get("message_id")
    return mid or f"sent-{uuid.uuid4().hex[:8]}"


def get_friend_list() -> list[dict]:
    data = _get("/get_friend_list")
    return data.get("data") or []


def get_group_list() -> list[dict]:
    data = _get("/get_group_list")
    return data.get("data") or []


def get_status() -> dict:
    return _get("/get_version_info")
