#!/usr/bin/env python3
"""
Agent Core

- 通过 MCP Client 调用 qq-mcp-server
- 使用 OpenAI Function Calling 做决策
- 支持开启/停止自动回复、发送消息等

在公司电脑无法安装 QQ 时，配合 mock_server.py 一起测试。
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import OpenAI

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")

SYSTEM_PROMPT = """
你是一个 Windows QQ Agent 助手。你有以下 MCP tools 可用：

- qq_get_status: 获取 OneBot 后端状态
- qq_get_friend_list: 获取 QQ 好友列表
- qq_get_group_list: 获取 QQ 群列表
- qq_send_private_msg: 向 QQ 好友发消息
- qq_send_group_msg: 向 QQ 群发消息
- qq_start_auto_reply: 启动自动回复，可指定 scope (all/private/group)、白名单、黑名单、人格
- qq_stop_auto_reply: 停止自动回复
- qq_get_auto_reply_status: 查看自动回复配置

规则：
1. 用户说"开启自动回复"、"帮我看着 QQ"等，就调用 qq_start_auto_reply。
2. 用户说"停止"、"关了"等，就调用 qq_stop_auto_reply。
3. 发送消息需要准确的 user_id/group_id。如果用户只给了昵称，先用 friend_list/group_list 查找对应 ID。
4. 人格提示词要自然、符合场景，不要暴露是 AI。
5. 简单查询直接回复，不需要调用 tool 就别调用。
""".strip()


class QQAgent:
    def __init__(self):
        self.client = OpenAI(api_key=OPENAI_API_KEY)
        self.session: ClientSession | None = None
        self.messages: list[dict] = []
        self.tool_schemas: list[dict] = []

    async def setup(self):
        params = StdioServerParameters(
            command="python",
            args=["qq_mcp_server.py"],
            env=None,
        )
        self._streams = await stdio_client(params).__aenter__()
        read, write = self._streams
        self.session = ClientSession(read, write)
        await self.session.initialize()

        # 拉取 MCP tools 并转成 OpenAI function schema
        tools_result = await self.session.list_tools()
        for tool in tools_result.tools:
            self.tool_schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema,
                },
            })

    async def teardown(self):
        if self.session:
            await self.session.__aexit__(None, None, None)

    async def execute_tool(self, name: str, arguments: dict) -> str:
        if not self.session:
            return "MCP session not initialized"
        result = await self.session.call_tool(name, arguments=arguments)
        return "\n".join(item.text for item in result.content if hasattr(item, "text"))

    async def chat(self, user_input: str) -> str:
        self.messages.append({"role": "user", "content": user_input})

        response = self.client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + self.messages,
            tools=self.tool_schemas,
            tool_choice="auto",
        )

        assistant_msg = response.choices[0].message

        # 没有 tool call，直接返回
        if not assistant_msg.tool_calls:
            self.messages.append({
                "role": "assistant",
                "content": assistant_msg.content or "",
            })
            return assistant_msg.content or ""

        # 有 tool call
        self.messages.append({
            "role": "assistant",
            "content": assistant_msg.content or "",
            "tool_calls": [tc.model_dump() for tc in assistant_msg.tool_calls],
        })

        for tc in assistant_msg.tool_calls:
            name = tc.function.name
            args = json.loads(tc.function.arguments)
            print(f"  [Tool] {name}({args})")
            result = await self.execute_tool(name, args)
            self.messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

        # 再次调用让 LLM 总结 tool 结果
        final = self.client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + self.messages,
        )
        content = final.choices[0].message.content or ""
        self.messages.append({"role": "assistant", "content": content})
        return content


async def main():
    if not OPENAI_API_KEY:
        print("请设置 OPENAI_API_KEY 环境变量")
        return

    agent = QQAgent()
    await agent.setup()
    try:
        print("QQ Agent 已启动。输入 'exit' 退出。")
        while True:
            user_input = input("\n你: ").strip()
            if user_input.lower() in {"exit", "quit", "退出"}:
                break
            if not user_input:
                continue
            reply = await agent.chat(user_input)
            print(f"\nAgent: {reply}")
    finally:
        await agent.teardown()


if __name__ == "__main__":
    asyncio.run(main())
