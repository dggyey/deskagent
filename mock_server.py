#!/usr/bin/env python3
"""
OneBot Mock Server

在没有安装 QQ 和 LLOneBot 时用来本地开发测试。
模拟 OneBot 11/12 的部分 API：
  - POST /send_private_msg
  - POST /send_group_msg
  - GET /get_friend_list
  - GET /get_group_list
  - WebSocket 推送收到的消息

运行：python mock_server.py
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import uvicorn
import websockets
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocket as StarletteWebSocket
from starlette.websockets import WebSocketDisconnect

MOCK_PORT = 11451


@dataclass
class MockBackend:
    friends: list[dict] = field(default_factory=lambda: [
        {"user_id": "10001", "nickname": "小李"},
        {"user_id": "10002", "nickname": "王总"},
        {"user_id": "10003", "nickname": "产品经理"},
    ])
    groups: list[dict] = field(default_factory=lambda: [
        {"group_id": "20001", "group_name": "技术交流群"},
        {"group_id": "20002", "group_name": "产品讨论群"},
        {"group_id": "20003", "group_name": "闲聊摸鱼群"},
    ])
    messages: list[dict] = field(default_factory=list)
    ws_clients: list[StarletteWebSocket] = field(default_factory=list)

    def __post_init__(self):
        # 预置几条消息方便测试
        self.messages.extend([
            {
                "post_type": "message",
                "message_type": "private",
                "user_id": "10001",
                "sender": {"nickname": "小李"},
                "message": "在忙吗？晚上一起吃饭？",
                "time": int(time.time()) - 300,
                "is_self": False,
            },
            {
                "post_type": "message",
                "message_type": "group",
                "group_id": "20001",
                "user_id": "10001",
                "sender": {"nickname": "小李"},
                "message": "下午开会别忘了",
                "time": int(time.time()) - 120,
                "is_self": False,
            },
        ])


backend = MockBackend()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[Mock] OneBot mock server running at http://127.0.0.1:{MOCK_PORT}")
    print("[Mock] WebSocket endpoint: ws://127.0.0.1:{MOCK_PORT}/ws")
    print("[Mock] Use Ctrl+C to stop.")
    yield
    print("[Mock] Server stopped.")


app = FastAPI(title="OneBot Mock", lifespan=l lifespan)


@app.get("/")
async def root():
    return {"status": "mock onebot running"}


@app.get("/get_version_info")
async def get_version_info():
    return {
        "status": "ok",
        "retcode": 0,
        "data": {
            "app_name": "LLOneBot-Mock",
            "app_version": "1.0.0",
            "protocol_version": "v11",
        },
        "message": "",
    }


@app.get("/get_friend_list")
async def get_friend_list():
    return {"status": "ok", "retcode": 0, "data": backend.friends, "message": ""}


@app.get("/get_group_list")
async def get_group_list():
    return {"status": "ok", "retcode": 0, "data": backend.groups, "message": ""}


@app.post("/send_private_msg")
async def send_private_msg(req: Request):
    body = await req.json()
    user_id = body.get("user_id", "unknown")
    message = body.get("message", "")
    print(f"[Mock] 发送私聊消息 -> user_id={user_id}: {message[:80]}")
    backend.messages.append({
        "post_type": "message",
        "message_type": "private",
        "user_id": user_id,
        "sender": {"nickname": "Me"},
        "message": message,
        "time": int(time.time()),
        "is_self": True,
    })
    return {
        "status": "ok",
        "retcode": 0,
        "data": {"message_id": f"mock-{random.randint(100000, 999999)}"},
        "message": "",
    }


@app.post("/send_group_msg")
async def send_group_msg(req: Request):
    body = await req.json()
    group_id = body.get("group_id", "unknown")
    message = body.get("message", "")
    print(f"[Mock] 发送群消息 -> group_id={group_id}: {message[:80]}")
    backend.messages.append({
        "post_type": "message",
        "message_type": "group",
        "group_id": group_id,
        "user_id": "self",
        "sender": {"nickname": "Me"},
        "message": message,
        "time": int(time.time()),
        "is_self": True,
    })
    return {
        "status": "ok",
        "retcode": 0,
        "data": {"message_id": f"mock-{random.randint(100000, 999999)}"},
        "message": "",
    }


@app.post("/mock/inject_message")
async def inject_message(req: Request):
    """
    测试用：主动注入一条 pretend-QQ 消息。
    """
    body = await req.json()
    backend.messages.append({
        "post_type": "message",
        "message_type": body.get("message_type", "private"),
        "user_id": body.get("user_id", "10001"),
        "group_id": body.get("group_id"),
        "sender": {"nickname": body.get("nickname", "小李")},
        "message": body.get("message", "测试消息"),
        "time": int(time.time()),
        "is_self": False,
    })
    # 推送给所有 websocket 客户端
    data = {"post_type": "message", **backend.messages[-1]}
    disconnected = []
    for ws in backend.ws_clients:
        try:
            await ws.send_text(json.dumps(data))
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        backend.ws_clients.remove(ws)

    return {"status": "ok", "retcode": 0, "data": None, "message": "injected"}


@app.websocket("/ws")
async def websocket_endpoint(ws: StarletteWebSocket):
    await ws.accept()
    backend.ws_clients.append(ws)
    print("[Mock] WebSocket client connected")
    try:
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg)
                print(f"[Mock] WS received: {data}")
                if data.get("action") == "get_latest_msg":
                    await ws.send_text(json.dumps({
                        "post_type": "meta_event",
                        "data": backend.messages[-10:],
                    }))
            except Exception as exc:
                print(f"[Mock] WS parse error: {exc}")
    except WebSocketDisconnect:
        print("[Mock] WebSocket client disconnected")
        if ws in backend.ws_clients:
            backend.ws_clients.remove(ws)


def run():
    uvicorn.run(app, host="127.0.0.1", port=MOCK_PORT, log_level="warning")


if __name__ == "__main__":
    run()
