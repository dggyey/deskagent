#!/usr/bin/env python3
"""
DeskAgent QQ MCP Server

把 OneBot（LLOneBot / mock）的 QQ 能力封装为 MCP tools。
自动回复状态持久化在 SQLite 中，由 Agent 主进程里的
OneBotListener + AutoReplyWorker 读取并执行。

运行：python qq_mcp_server.py
"""
from __future__ import annotations

import asyncio
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

import config
import onebot_client
import storage

storage.init_db()

app = Server("deskagent-qq")


def _text(content: str) -> list[TextContent]:
    return [TextContent(type="text", text=content)]


async def _run(fn, *args):
    """在线程池执行同步的网络 / DB 调用，避免阻塞事件循环。"""
    return await asyncio.to_thread(fn, *args)


def _resolve_ids(names: list[str]) -> list[str]:
    """把昵称解析为 QQ 号 / 群号，解析不了就原样保留。"""
    resolved = []
    for name in names or []:
        nid = storage.resolve_contact("friend", name) or storage.resolve_contact("group", name)
        resolved.append(nid or name)
    return resolved


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="qq_get_status",
            description="获取 OneBot 后端（LLOneBot / mock）连接状态",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="qq_get_friend_list",
            description="获取 QQ 好友列表（昵称和 QQ 号）",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="qq_get_group_list",
            description="获取 QQ 群列表（群名和群号）",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="qq_send_private_msg",
            description="向指定 QQ 好友发送私聊消息",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "好友 QQ 号"},
                    "content": {"type": "string", "description": "消息内容"},
                },
                "required": ["user_id", "content"],
            },
        ),
        Tool(
            name="qq_send_group_msg",
            description="向指定 QQ 群发送消息，可 @ 指定成员",
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {"type": "string", "description": "群号"},
                    "content": {"type": "string", "description": "消息内容"},
                    "at_members": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选，需要 @ 的成员 QQ 号",
                    },
                },
                "required": ["group_id", "content"],
            },
        ),
        Tool(
            name="qq_start_auto_reply",
            description=(
                "启动 QQ 自动回复。"
                "scope: all（全部）/ private（仅私聊）/ group（仅群聊）。"
                "白名单非空时只回复名单内的会话；黑名单中的会话永不自动回复。"
                "名单里可填昵称或 QQ 号。"
                "only_when_at=true 时，群聊里只在被 @ 时回复。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": ["all", "private", "group"],
                        "description": "自动回复范围",
                        "default": "all",
                    },
                    "whitelist": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "白名单（昵称或 ID），为空表示不限制",
                    },
                    "blacklist": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "黑名单（昵称或 ID）",
                    },
                    "only_when_at": {
                        "type": "boolean",
                        "description": "群聊中是否只在被 @ 时回复",
                        "default": False,
                    },
                    "persona": {
                        "type": "string",
                        "description": "回复人格提示词，用于设定回复语气和角色",
                    },
                },
            },
        ),
        Tool(
            name="qq_stop_auto_reply",
            description="停止 QQ 自动回复",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="qq_get_auto_reply_status",
            description="查看当前自动回复配置（是否开启、范围、黑白名单、人格）",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="qq_sync_contacts",
            description="同步 QQ 好友列表和群列表到本地，建立昵称到 ID 的映射",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "qq_get_status":
            data = await _run(onebot_client.get_status)
            return _text(json.dumps(data, ensure_ascii=False, indent=2))

        if name == "qq_get_friend_list":
            friends = await _run(onebot_client.get_friend_list)
            for f in friends:
                storage.upsert_contact("friend", str(f.get("user_id")), f.get("nickname", ""))
            return _text(json.dumps(friends, ensure_ascii=False, indent=2))

        if name == "qq_get_group_list":
            groups = await _run(onebot_client.get_group_list)
            for g in groups:
                storage.upsert_contact("group", str(g.get("group_id")), g.get("group_name", ""))
            return _text(json.dumps(groups, ensure_ascii=False, indent=2))

        if name == "qq_send_private_msg":
            user_id = str(arguments["user_id"])
            content = str(arguments.get("content", ""))
            if config.OWNER_ID and user_id == config.OWNER_ID:
                return _text("不能给自己发消息")
            mid = await _run(onebot_client.send_private_msg, user_id, content)
            return _text(f"已发送私聊消息给 {user_id}（message_id={mid}）")

        if name == "qq_send_group_msg":
            group_id = str(arguments["group_id"])
            content = str(arguments.get("content", ""))
            at_members = arguments.get("at_members") or []
            if not content:
                return _text("消息内容不能为空")
            mid = await _run(onebot_client.send_group_msg, group_id, content, at_members)
            return _text(f"已发送群消息到 {group_id}（message_id={mid}）")

        if name == "qq_start_auto_reply":
            cfg = storage.set_auto_reply_config(
                enabled=True,
                scope=arguments.get("scope") or "all",
                whitelist=_resolve_ids(arguments.get("whitelist") or []),
                blacklist=_resolve_ids(arguments.get("blacklist") or []),
                only_when_at=bool(arguments.get("only_when_at", False)),
                persona=arguments.get("persona") or "",
            )
            # 若开启了自动回复，则确保 Worker 在运行（Agent 主进程内管理，此处只改配置）
            return _text("自动回复已开启。当前配置：\n" + json.dumps(cfg, ensure_ascii=False, indent=2))

        if name == "qq_stop_auto_reply":
            cfg = storage.set_auto_reply_config(enabled=False)
            return _text("自动回复已停止。")

        if name == "qq_get_auto_reply_status":
            return _text(json.dumps(storage.get_auto_reply_config(), ensure_ascii=False, indent=2))

        if name == "qq_sync_contacts":
            friends = await _run(onebot_client.get_friend_list)
            groups = await _run(onebot_client.get_group_list)
            for f in friends:
                storage.upsert_contact("friend", str(f.get("user_id")), f.get("nickname", ""))
            for g in groups:
                storage.upsert_contact("group", str(g.get("group_id")), g.get("group_name", ""))
            return _text(f"联系人同步完成：{len(friends)} 个好友，{len(groups)} 个群")

        return _text(f"未知工具: {name}")
    except Exception as exc:  # noqa: BLE001
        return _text(f"[调用失败] {name}: {exc}")


async def main():
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
