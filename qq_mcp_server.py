#!/usr/bin/env python3
"""
QQ MCP Server

封装 OneBot/LLOneBot API 为 MCP tools。
通过环境变量 ONEBOT_HTTP_URL 指定后端，默认连接 mock server。

运行：python qq_mcp_server.py
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

ONEBOT_HTTP_URL = os.environ.get("ONEBOT_HTTP_URL", "http://127.0.0.1:11451")

app = Server("qq-mcp")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="qq_get_status",
            description="获取 OneBot 后端连接状态",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="qq_get_friend_list",
            description="获取 QQ 好友列表",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="qq_get_group_list",
            description="获取 QQ 群列表",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="qq_send_private_msg",
            description="向指定 QQ 好友发送私聊消息",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "对方 QQ 号"},
                    "content": {"type": "string", "description": "消息内容"},
                },
                "required": ["user_id", "content"],
            },
        ),
        Tool(
            name="qq_send_group_msg",
            description="向指定 QQ 群发送消息",
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {"type": "string", "description": "群号"},
                    "content": {"type": "string", "description": "消息内容"},
                    "at_members": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选，需要 @ 的 QQ 号列表",
                    },
                },
                "required": ["group_id", "content"],
            },
        ),
        Tool(
            name="qq_start_auto_reply",
            description="启动 QQ 自动回复。可指定范围、人格、黑白名单。",
            inputSchema={
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": ["all", "private", "group"],
                        "default": "all",
                        "description": "自动回复范围",
                    },
                    "whitelist": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "白名单（昵称或 QQ 号），为空则不限",
                    },
                    "blacklist": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "黑名单（昵称或 QQ 号）",
                    },
                    "only_when_at": {
                        "type": "boolean",
                        "default": False,
                        "description": "群聊中是否只在被 @ 时回复",
                    },
                    "persona": {
                        "type": "string",
                        "description": "回复人格提示词",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="qq_stop_auto_reply",
            description="停止 QQ 自动回复",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="qq_get_auto_reply_status",
            description="获取当前自动回复状态",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
    ]


async def onebot_request(path: str, method: str = "GET", payload: dict | None = None) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        url = f"{ONEBOT_HTTP_URL}{path}"
        if method.upper() == "GET":
            r = await client.get(url)
        else:
            r = await client.post(url, json=payload)
        return r.json()


auto_reply_state = {
    "enabled": False,
    "scope": "all",
    "whitelist": [],
    "blacklist": [],
    "only_when_at": False,
    "persona": "你是一个 helpful assistant，用自然简短的语气回复。",
}


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "qq_get_status":
        data = await onebot_request("/get_version_info")
        return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False))]

    if name == "qq_get_friend_list":
        data = await onebot_request("/get_friend_list")
        return [TextContent(type="text", text=json.dumps(data.get("data", []), ensure_ascii=False))]

    if name == "qq_get_group_list":
        data = await onebot_request("/get_group_list")
        return [TextContent(type="text", text=json.dumps(data.get("data", []), ensure_ascii=False))]

    if name == "qq_send_private_msg":
        payload = {
            "user_id": arguments["user_id"],
            "message": arguments["content"],
        }
        data = await onebot_request("/send_private_msg", "POST", payload)
        return [TextContent(type="text", text=f"私聊发送成功: {data}")]

    if name == "qq_send_group_msg":
        message = arguments["content"]
        # 处理 @ 成员，简单拼接为 [CQ:at,qq=xxx]
        for member in arguments.get("at_members", []):
            message += f"[CQ:at,qq={member}] "
        payload = {
            "group_id": arguments["group_id"],
            "message": message,
        }
        data = await onebot_request("/send_group_msg", "POST", payload)
        return [TextContent(type="text", text=f"群消息发送成功: {data}")]

    if name == "qq_start_auto_reply":
        auto_reply_state["enabled"] = True
        auto_reply_state["scope"] = arguments.get("scope", "all")
        auto_reply_state["whitelist"] = arguments.get("whitelist", [])
        auto_reply_state["blacklist"] = arguments.get("blacklist", [])
        auto_reply_state["only_when_at"] = arguments.get("only_when_at", False)
        if arguments.get("persona"):
            auto_reply_state["persona"] = arguments["persona"]
        return [TextContent(
            type="text",
            text=f"已启动自动回复: {json.dumps(auto_reply_state, ensure_ascii=False)}",
        )]

    if name == "qq_stop_auto_reply":
        auto_reply_state["enabled"] = False
        return [TextContent(type="text", text="已停止自动回复")]

    if name == "qq_get_auto_reply_status":
        return [TextContent(
            type="text",
            text=json.dumps(auto_reply_state, ensure_ascii=False),
        )]

    raise ValueError(f"Unknown tool: {name}")


async def main():
    print(f"[QQ MCP] Connecting to OneBot backend: {ONEBOT_HTTP_URL}", flush=True)
    async with stdio_server(server=app) as (read, write):
        await app.run(read, write, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
