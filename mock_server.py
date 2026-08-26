#!/usr/bin/env python3
"""
OneBot Mock Server

在没有安装 QQ 和 LLOneBot 时用来本地开发测试。
模拟 OneBot v11 的部分 API 与正向 WebSocket 事件：

  HTTP:
    - GET  /get_version_info
    - GET  /get_friend_list
    - GET  /get_group_list
    - POST /send_private_msg        （发送后广播 message_sent 事件）
    - POST /send_group_msg           （发送后广播 message_sent 事件）
    - POST /mock/inject_message      （注入一条模拟收到的消息并广播）
    - POST /mock/toggle_auto_inject  （开关自动注入）

  WebSocket /ws:
    - 推送 OneBot 风格事件（post_type=message / message_sent / meta_event）

可通过环境变量调整行为：
  MOCK_PORT=11451          监听端口
  MOCK_AUTO_INJECT=20      自动注入模拟消息的间隔秒数，0 表示关闭

运行：python mock_server.py
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import uvicorn
from fastapi import FastAPI, Request
from starlette.websockets import WebSocket as StarletteWebSocket
from starlette.websockets import WebSocketDisconnect

MOCK_PORT = int(os.environ.get("MOCK_PORT", "11451"))
AUTO_INJECT_SECONDS = float(os.environ.get("MOCK_AUTO_INJECT", "20"))

# 模拟联系人
FRIENDS = [
    {"user_id": "10001", "nickname": "小李"},
    {"user_id": "10002", "nickname": "王总"},
    {"user_id": "10003", "nickname": "产品经理"},
]
GROUPS = [
    {"group_id": "20001", "group_name": "技术交流群"},
    {"group_id": "20002", "group_name": "产品讨论群"},
    {"group_id": "20003", "group_name": "闲聊摸鱼群"},
]

# 自动注入用的假消息模板
INJECT_POOL = [
    ("private", "10001", "小李", "在忙吗？晚上一起吃饭？"),
    ("private", "10002", "王总", "那个方案明天上午给我。"),
    ("private", "10003", "产品经理", "需求文档更新了，看一下。"),
    ("group", "20001", "小李", "下午四点开会别忘了"),
    ("group", "20002", "产品经理", "新版本发布时间定了吗？"),
    ("group", "20003", "小李", "哈哈哈哈这个表情包绝了"),
]

_msg_seq = 0


def next_message_id() -> str:
    # 带毫秒时间戳：mock 重启后 seq 归零也不会和数据库旧记录撞 ID 被去重丢弃
    global _msg_seq
    _msg_seq += 1
    return f"mock-{int(time.time() * 1000)}-{_msg_seq}"


@dataclass
class MockBackend:
    messages: list[dict] = field(default_factory=list)
    ws_clients: list[StarletteWebSocket] = field(default_factory=list)
    auto_inject: bool = AUTO_INJECT_SECONDS > 0


backend = MockBackend()


def build_message_event(message_type: str, name: str, content: str,
                        is_self: bool = False) -> dict:
    """构造 OneBot v11 风格的事件。name 为好友昵称或群名。"""
    event: dict = {
        "post_type": "message",
        "message_type": message_type,
        "message_id": next_message_id(),
        "time": int(time.time()),
        "message": content,
        "raw_message": content,
        "is_self": is_self,
        "sender": {"nickname": name},
    }
    if message_type == "private":
        user_id = next((f["user_id"] for f in FRIENDS if f["nickname"] == name), "99999")
        event["user_id"] = user_id
    else:
        group_id = next((g["group_id"] for g in GROUPS if g["group_name"] == name), "99999")
        speaker = random.choice(["小李", "王总", "产品经理"])
        event["group_id"] = group_id
        event["user_id"] = next((f["user_id"] for f in FRIENDS if f["nickname"] == speaker), "10001")
        event["sender"] = {"nickname": speaker}
    return event


async def broadcast(event: dict) -> None:
    backend.messages.append(event)
    dead = []
    for ws in backend.ws_clients:
        try:
            await ws.send_text(json.dumps(event, ensure_ascii=False))
        except Exception:
            dead.append(ws)
    for ws in dead:
        backend.ws_clients.remove(ws)


async def inject_task() -> None:
    """定时注入模拟消息，方便观察自动回复闭环。"""
    while True:
        await asyncio.sleep(AUTO_INJECT_SECONDS)
        if not backend.auto_inject:
            continue
        message_type, _id, name, content = random.choice(INJECT_POOL)
        event = build_message_event(message_type, name, content)
        await broadcast(event)
        print(f"[Mock] 自动注入: {event['message_type']} {event['sender']['nickname']}: {content}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[Mock] OneBot mock server running at http://127.0.0.1:{MOCK_PORT}")
    print(f"[Mock] WebSocket endpoint: ws://127.0.0.1:{MOCK_PORT}/ws")
    print(f"[Mock] 自动注入消息: {'每 %ds' % AUTO_INJECT_SECONDS if AUTO_INJECT_SECONDS > 0 else '关闭'}")
    task = asyncio.create_task(inject_task()) if AUTO_INJECT_SECONDS > 0 else None
    yield
    if task:
        task.cancel()
    print("[Mock] Server stopped.")


app = FastAPI(title="OneBot Mock", lifespan=lifespan)


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
    return {"status": "ok", "retcode": 0, "data": FRIENDS, "message": ""}


@app.get("/get_group_list")
async def get_group_list():
    return {"status": "ok", "retcode": 0, "data": GROUPS, "message": ""}


@app.post("/send_private_msg")
async def send_private_msg(req: Request):
    body = await req.json()
    user_id = str(body.get("user_id", "unknown"))
    message = body.get("message", "")
    print(f"[Mock] 发送私聊消息 -> {user_id}: {message[:80]}")

    message_id = next_message_id()
    await broadcast({
        "post_type": "message_sent",
        "message_type": "private",
        "message_id": message_id,
        "time": int(time.time()),
        "user_id": user_id,
        "message": message,
        "raw_message": message,
        "sender": {"nickname": "我"},
        "is_self": True,
    })
    return {"status": "ok", "retcode": 0, "data": {"message_id": message_id}, "message": ""}


@app.post("/send_group_msg")
async def send_group_msg(req: Request):
    body = await req.json()
    group_id = str(body.get("group_id", "unknown"))
    message = body.get("message", "")
    print(f"[Mock] 发送群消息 -> {group_id}: {message[:80]}")

    message_id = next_message_id()
    await broadcast({
        "post_type": "message_sent",
        "message_type": "group",
        "message_id": message_id,
        "time": int(time.time()),
        "group_id": group_id,
        "user_id": "self",
        "message": message,
        "raw_message": message,
        "sender": {"nickname": "我"},
        "is_self": True,
    })
    return {"status": "ok", "retcode": 0, "data": {"message_id": message_id}, "message": ""}


@app.post("/mock/inject_message")
async def inject_message(req: Request):
    """手动注入一条模拟收到的消息（测试用）。

    body 格式：
      {"message_type": "private|group", "name": "小李|技术交流群", "content": "..."}
    """
    body = await req.json()
    message_type = body.get("message_type", "private")
    name = body.get("name") or "小李"
    content = body.get("content", "测试消息")
    event = build_message_event(message_type, name, content)
    await broadcast(event)
    print(f"[Mock] 注入消息: {event['message_type']} {event['sender']['nickname']}: {content}")
    return {"status": "ok", "retcode": 0, "data": event, "message": "injected"}


@app.post("/mock/toggle_auto_inject")
async def toggle_auto_inject(req: Request):
    body = await req.json()
    backend.auto_inject = bool(body.get("enabled", not backend.auto_inject))
    return {"status": "ok", "retcode": 0, "data": {"auto_inject": backend.auto_inject}, "message": ""}


@app.websocket("/ws")
async def websocket_endpoint(ws: StarletteWebSocket):
    await ws.accept()
    backend.ws_clients.append(ws)
    print("[Mock] WebSocket client connected")
    try:
        await ws.send_text(json.dumps({
            "post_type": "meta_event",
            "meta_event_type": "lifecycle",
            "sub_type": "connect",
            "time": int(time.time()),
        }))
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg)
                print(f"[Mock] WS received: {data}")
                if data.get("action") == "get_recent_messages":
                    await ws.send_text(json.dumps(
                        {"post_type": "meta_event", "data": backend.messages[-20:]},
                        ensure_ascii=False,
                    ))
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
