#!/usr/bin/env python3
"""
DeskAgent 核心

启动后做三件事：
  1. OneBotListener：连接 OneBot（LLOneBot / mock）接收 QQ 消息，写入 SQLite
  2. AutoReplyWorker：按配置自动回复（范围 / 黑白名单 / @ / 冷却）
  3. CLI 对话：理解自然语言指令，通过 MCP 调用 QQ 工具

在公司电脑没有 QQ 时，配合 mock_server.py 可以完整体验闭环。
没有 OPENAI_API_KEY 时，对话层退化为关键词路由，仍可测试自动回复。

运行：python agent_core.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import config
import memory
import storage

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("agent")

SYSTEM_PROMPT = """
你是 DeskAgent，一个桌面 AI 助手，能控制用户的 QQ（通过 MCP tools）。

可用工具：
- qq_get_status / qq_get_friend_list / qq_get_group_list：查看后端状态、好友、群
- qq_sync_contacts：同步联系人昵称与 ID 映射（用户提到昵称发不了消息时需要先同步）
- qq_send_private_msg / qq_send_group_msg：发消息（需要 QQ 号/群号；若用户只给了昵称，先查好友或群列表拿到 ID）
- qq_start_auto_reply：开启自动回复。参数：
  - scope：all（全部）/ private（仅私聊）/ group（仅群聊）
  - whitelist：白名单，昵称或 ID，非空时只回复这些会话
  - blacklist：黑名单
  - only_when_at：群聊中是否仅在被 @ 时回复
  - persona：回复人格，比如"简洁的朋友语气，不暴露是 AI"
- qq_stop_auto_reply：停止自动回复
- qq_get_auto_reply_status：查看当前自动回复配置
- memory_remember / memory_forget / memory_list：长期记忆的增删查（用户说"记住/忘记/你记得什么"时用）
- safety_get_alerts：查看敏感内容拦截提醒

行为要求：
1. 用户只说昵称时（例如"只回小李""别回王总"），从好友/群列表中解析出 ID 再传参。
2. 操作完成后用一句自然的话确认结果。
3. 不确定的参数不要瞎编，直接问用户。
"""

# 无 API Key 时的关键词路由，保证公司电脑也能演示闭环
KEYWORD_TOOLS = {
    "开启自动回复": ("qq_start_auto_reply", {}),
    "停止自动回复": ("qq_stop_auto_reply", {}),
    "自动回复状态": ("qq_get_auto_reply_status", {}),
    "同步联系人": ("qq_sync_contacts", {}),
    "好友列表": ("qq_get_friend_list", {}),
    "群列表": ("qq_get_group_list", {}),
    "状态": ("qq_get_status", {}),
    "拦截提醒": ("safety_get_alerts", {}),
    "你记得什么": ("memory_list", {}),
    "记忆列表": ("memory_list", {}),
}


class DeskAgent:
    def __init__(self) -> None:
        self._exit_stack = AsyncExitStack()
        self.session: ClientSession | None = None
        self.tool_schemas: list[dict] = []
        self.messages: list[dict] = []

    # ------------------------------------------------------------------
    # MCP 连接
    # ------------------------------------------------------------------

    async def connect_mcp(self) -> None:
        server_script = str(Path(__file__).parent / "qq_mcp_server.py")
        params = StdioServerParameters(
            command=sys.executable,
            args=[server_script],
        )
        # stdio_client 和 ClientSession 都是异步上下文管理器，
        # 必须正确进入，否则 dispatcher 不会启动
        read, write = await self._exit_stack.enter_async_context(stdio_client(params))
        self.session = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await self.session.initialize()

        tools = await self.session.list_tools()
        for tool in tools.tools:
            self.tool_schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema or {"type": "object", "properties": {}},
                },
            })
        logger.info("MCP 已连接，可用工具: %s", [t["function"]["name"] for t in self.tool_schemas])

    async def close(self) -> None:
        await self._exit_stack.aclose()

    async def call_tool(self, name: str, arguments: dict) -> str:
        result = await self.session.call_tool(name, arguments)
        return "\n".join(
            item.text for item in result.content if getattr(item, "type", None) == "text"
        )

    # ------------------------------------------------------------------
    # 对话
    # ------------------------------------------------------------------

    async def chat(self, user_input: str) -> str:
        if not config.OPENAI_API_KEY:
            return await self._keyword_route(user_input)

        from openai import OpenAI

        client = OpenAI(
            api_key=config.OPENAI_API_KEY,
            base_url=config.OPENAI_BASE_URL or None,
        )
        self.messages.append({"role": "user", "content": user_input})

        for _round in range(5):  # 最多 5 轮工具调用
            resp = await asyncio.to_thread(
                client.chat.completions.create,
                model=config.LLM_MODEL,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}] + self.messages[-20:],
                tools=self.tool_schemas,
                tool_choice="auto",
            )
            msg = resp.choices[0].message

            if not msg.tool_calls:
                answer = msg.content or "(无回复)"
                self.messages.append({"role": "assistant", "content": answer})
                return answer

            self.messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
            })
            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                logger.info("调用工具 %s(%s)", name, json.dumps(args, ensure_ascii=False))
                result = await self.call_tool(name, args)
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
        return "抱歉，处理指令时调用层级过深，请换个说法再说一次。"

    async def _keyword_route(self, user_input: str) -> str:
        """无 API Key 时的兜底：关键词直接对应工具调用。"""
        # 记忆指令带参数，优先单独处理
        if user_input.startswith(("记住", "记一下", "记得")):
            return memory.remember(user_input)
        if user_input.startswith(("忘记", "忘掉", "删除记忆")):
            return memory.forget(user_input)

        for keyword, (tool, args) in KEYWORD_TOOLS.items():
            if keyword in user_input:
                result = await self.call_tool(tool, args)
                return (
                    f"（调试模式：未配置 OPENAI_API_KEY，按关键词执行了 {tool}）\n\n{result}"
                )
        return (
            "未配置 OPENAI_API_KEY，当前仅支持关键词指令：\n"
            + "\n".join(f"  - {k}" for k in KEYWORD_TOOLS)
            + "\n  - 记住 小李：喜欢美式咖啡\n  - 忘记 咖啡\n  - 拦截提醒"
        )


# ----------------------------------------------------------------------
# 启动
# ----------------------------------------------------------------------

async def main() -> None:
    storage.init_db()

    # 1. 后台服务（监听 + 自动回复）在独立子进程里跑，
    #    与 CLI 主进程的事件循环彻底隔离
    import subprocess as _subprocess
    import sys as _sys

    daemon_proc = _subprocess.Popen(
        [_sys.executable, str(Path(__file__).parent / "daemon.py")],
    )

    # 2. Agent + MCP
    agent = DeskAgent()
    await agent.connect_mcp()

    print("=" * 50)
    print("DeskAgent 已启动")
    if not config.OPENAI_API_KEY:
        print("[提示] 未设置 OPENAI_API_KEY，对话层为关键词调试模式")
    print("示例指令：")
    print("  - 同步联系人")
    print("  - 开启自动回复 / 停止自动回复 / 自动回复状态")
    print("  - 只给小李自动回（需要 LLM）")
    print("  - 给技术交流群发消息说下午开会（需要 LLM）")
    print("  - 记住 小李：喜欢美式咖啡 / 忘记 咖啡 / 你记得什么")
    print("  - 拦截提醒（查看被拦下的敏感消息）")
    print("输入 exit 退出")
    print("=" * 50)

    alert_task = asyncio.create_task(_alert_notifier())

    loop = asyncio.get_event_loop()
    try:
        while True:
            try:
                user_input = await loop.run_in_executor(None, input, "\n你: ")
            except EOFError:
                break
            user_input = user_input.strip()
            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit", "退出"}:
                break
            try:
                reply = await agent.chat(user_input)
            except Exception as exc:  # noqa: BLE001
                logger.exception("处理消息失败")
                reply = f"出错了：{exc}"
            print(f"\nAgent: {reply}")
    finally:
        alert_task.cancel()
        await agent.close()
        daemon_proc.terminate()
        print("已退出。")


async def _alert_notifier() -> None:
    """轮询未读的敏感内容提醒，实时打印到控制台。"""
    while True:
        await asyncio.sleep(2)
        try:
            unseen = storage.get_alerts(unseen_only=True, limit=10)
            if unseen:
                print()
                for row in unseen:
                    print(
                        f"⚠️  敏感内容提醒：{row['sender_name']}（{row['source_id']}）"
                        f"「{row['content']}」—— {row['reason']}。已拦截，未自动回复，请人工处理。"
                    )
                storage.mark_alerts_seen()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    asyncio.run(main())
