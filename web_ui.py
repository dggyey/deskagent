#!/usr/bin/env python3
"""
DeskAgent WebUI（Gradio）

先启动 mock 或真实 LLOneBot 后端，再运行本文件：

    .venv/bin/python mock_server.py     # 终端 1（无 QQ 环境时）
    .venv/bin/python web_ui.py          # 终端 2

浏览器打开 http://127.0.0.1:7860

左侧：对话窗口（和 Agent 聊天，支持全部自然语言指令）
右侧：自动回复状态 / 敏感内容提醒 / 长期记忆，每 3 秒自动刷新
"""
from __future__ import annotations

import asyncio
import atexit
import json
import subprocess
import sys
import threading
from pathlib import Path

import gradio as gr

import config
import storage
from agent_core import DeskAgent


class AgentBridge:
    """把 DeskAgent（含 MCP 异步会话）钉在专属事件循环线程上，
    Gradio 的同步 handler 通过 run_coroutine_threadsafe 调用它。"""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True, name="agent-loop").start()
        self.agent = DeskAgent()
        asyncio.run_coroutine_threadsafe(self.agent.connect_mcp(), self.loop).result(timeout=30)

    def chat(self, text: str) -> str:
        fut = asyncio.run_coroutine_threadsafe(self.agent.chat(text), self.loop)
        return fut.result(timeout=120)

    def call_tool_sync(self, name: str, arguments: dict) -> str:
        fut = asyncio.run_coroutine_threadsafe(
            self.agent.call_tool(name, arguments), self.loop
        )
        return fut.result(timeout=60)


bridge: AgentBridge | None = None


def respond(history: list, message: str):
    message = (message or "").strip()
    if not message:
        return history, ""
    history = history + [{"role": "user", "content": message}]
    try:
        reply = bridge.chat(message)
    except Exception as exc:  # noqa: BLE001
        reply = f"出错了：{exc}"
    history = history + [{"role": "assistant", "content": reply}]
    return history, ""


def quick_cmd(history: list, command: str):
    return respond(history, command)


def quick_send(target_kind: str, target_name: str, content: str):
    """快捷发送面板：不经 LLM，直接调 MCP 发出去。对象支持昵称或 ID。"""
    target_name = (target_name or "").strip()
    content = (content or "").strip()
    if not target_name or not content:
        return "⚠️ 请先填对象和内容。对象可填昵称（如 小李）或 QQ 号 / 群号。"
    kind = "friend" if target_kind == "私聊" else "group"
    target_id = storage.resolve_contact(kind, target_name) or target_name
    try:
        if kind == "friend":
            result = bridge.call_tool_sync("qq_send_private_msg", {"user_id": target_id, "content": content})
        else:
            result = bridge.call_tool_sync("qq_send_group_msg", {"group_id": target_id, "content": content})
    except Exception as exc:  # noqa: BLE001
        return f"发送失败：{exc}"
    return f"✅ {result}"


def render_status() -> tuple[str, str, str, str]:
    cfg = storage.get_auto_reply_config()
    state_icon = "🟢 已开启" if cfg["enabled"] else "⛔ 已关闭"
    status = (
        f"### 自动回复状态\n"
        f"- 状态：{state_icon}\n"
        f"- 范围：{cfg['scope']}\n"
        f"- 白名单：{', '.join(cfg['whitelist']) or '（不限）'}\n"
        f"- 黑名单：{', '.join(cfg['blacklist']) or '（无）'}\n"
        f"- 仅 @ 时回复：{'是' if cfg['only_when_at'] else '否'}\n"
        f"- 人格：{cfg['persona'] or '默认'}\n"
    )

    conn = storage._connect()
    total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    auto = conn.execute("SELECT COUNT(*) FROM messages WHERE is_auto_reply = 1").fetchone()[0]
    rows = conn.execute(
        "SELECT COUNT(*) FROM alerts"
    ).fetchone()[0]
    conn.close()
    status += f"\n消息 {total} 条，其中自动回复 {auto} 条；拦截提醒 {rows} 条。\n"

    alerts = storage.get_alerts(unseen_only=False, limit=6)
    if alerts:
        lines = ["### 敏感内容提醒（最新在前）"]
        for row in alerts:
            seen = "✅" if row["handled"] else "🔴"
            lines.append(f"- {seen} {row['sender_name']}：{row['reason']}\n  「{row['content']}」")
        alerts_md = "\n".join(lines)
    else:
        alerts_md = "### 敏感内容提醒\n暂无拦截记录。"

    memories = storage.get_memories(limit=10)
    if memories:
        lines = ["### 长期记忆"]
        for row in memories:
            tag = "全局" if row["scope"] == "*" else row["scope"]
            lines.append(f"- [{tag}] {row['content']}")
        memory_md = "\n".join(lines)
    else:
        memory_md = "### 长期记忆\n暂无。说「记住 小李：喜欢美式」试试。"

    # QQ 消息记录：对方发的 + 我（自动）回的，按时间正序
    conn = storage._connect()
    msg_rows = conn.execute(
        """
        SELECT message_type, source_id, sender_name, content, is_self, is_auto_reply
        FROM messages ORDER BY id DESC LIMIT 10
        """,
    ).fetchall()
    conn.close()
    if msg_rows:
        lines = ["### QQ 消息记录（最新在前）"]
        for row in msg_rows:
            where = "群" if row["message_type"] == "group" else "私"
            if row["is_self"]:
                tag = "🤖 自动回" if row["is_auto_reply"] else "💬 我"
                lines.append(f"- [{where}] {tag} → {row['content']}")
            else:
                lines.append(f"- [{where}] {row['sender_name']}：{row['content']}")
        messages_md = "\n".join(lines)
    else:
        messages_md = "### QQ 消息记录\n暂无。注入一条消息就会出现在这里。"

    return status, alerts_md, memory_md, messages_md


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="DeskAgent", theme=gr.themes.Soft()) as demo:
        gr.Markdown(
            "# 🐾 DeskAgent\n"
            "和 Agent 说话来控制 QQ 自动回复、记忆与提醒。"
            "右侧面板每 3 秒自动刷新。"
        )
        with gr.Row():
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(
                    type="messages", height=540,
                    placeholder="在这里和 DeskAgent 对话，例如：\n- 开启自动回复，只回私聊\n- 记住 小李：喜欢美式咖啡\n- 给技术交流群发消息说下午开会",
                )
                with gr.Row():
                    msg = gr.Textbox(
                        placeholder="输入指令，例如：开启自动回复",
                        scale=5, show_label=False, container=False,
                    )
                    send_btn = gr.Button("发送", variant="primary", scale=1)
                with gr.Row():
                    btn_on = gr.Button("开启自动回复", size="sm")
                    btn_off = gr.Button("停止自动回复", size="sm")
                    btn_sync = gr.Button("同步联系人", size="sm")
                    btn_mem = gr.Button("你记得什么", size="sm")
                    btn_alerts = gr.Button("拦截提醒", size="sm")
            with gr.Column(scale=1):
                status_md = gr.Markdown("### 自动回复状态\n加载中…")
                messages_md = gr.Markdown("### QQ 消息记录\n加载中…")
                alerts_md = gr.Markdown("### 敏感内容提醒\n加载中…")
                memory_md = gr.Markdown("### 长期记忆\n加载中…")

        with gr.Group():
            gr.Markdown("### 📨 QQ 快捷发送（手机遥控用）")
            with gr.Row():
                kind = gr.Radio(["私聊", "群聊"], value="私聊", show_label=False, scale=2)
                target = gr.Textbox(placeholder="小李 或 QQ 号/群号", show_label=False, scale=3)
            with gr.Row():
                qmsg = gr.Textbox(placeholder="要发送的内容", show_label=False, scale=5)
                qsend = gr.Button("发送", variant="primary", scale=1)
            qresult = gr.Markdown("对象支持昵称，首次使用请先「同步联系人」。")

        PANELS = [status_md, alerts_md, memory_md, messages_md]
        qsend.click(quick_send, inputs=[kind, target, qmsg], outputs=qresult) \
            .then(render_status, outputs=PANELS)

        msg.submit(respond, inputs=[chatbot, msg], outputs=[chatbot, msg]) \
            .then(render_status, outputs=PANELS)
        send_btn.click(respond, inputs=[chatbot, msg], outputs=[chatbot, msg]) \
            .then(render_status, outputs=PANELS)
        btn_on.click(quick_cmd, inputs=[chatbot, gr.State("开启自动回复")], outputs=[chatbot, msg]) \
            .then(render_status, outputs=PANELS)
        btn_off.click(quick_cmd, inputs=[chatbot, gr.State("停止自动回复")], outputs=[chatbot, msg]) \
            .then(render_status, outputs=PANELS)
        btn_sync.click(quick_cmd, inputs=[chatbot, gr.State("同步联系人")], outputs=[chatbot, msg]) \
            .then(render_status, outputs=PANELS)
        btn_mem.click(quick_cmd, inputs=[chatbot, gr.State("你记得什么")], outputs=[chatbot, msg]) \
            .then(render_status, outputs=PANELS)
        btn_alerts.click(quick_cmd, inputs=[chatbot, gr.State("拦截提醒")], outputs=[chatbot, msg]) \
            .then(render_status, outputs=PANELS)

        demo.load(render_status, outputs=PANELS, every=3)

    return demo


def main() -> None:
    storage.init_db()

    # 后台服务（监听 + 自动回复）放在独立子进程里跑，
    # 与 Gradio/uvicorn 的事件循环彻底隔离，互不干扰
    daemon_proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).parent / "daemon.py")],
    )
    atexit.register(daemon_proc.terminate)

    global bridge
    print("[WebUI] 正在连接 MCP 工具层…")
    bridge = AgentBridge()

    import socket

    try:
        lan_ip = socket.gethostbyname(socket.gethostname())
    except OSError:
        lan_ip = "你的电脑IP"
    print(f"[WebUI] 就绪")
    print(f"  本机访问:   http://127.0.0.1:{config.WEBUI_PORT}")
    print(f"  手机访问:   http://{lan_ip}:{config.WEBUI_PORT} （同一 Wi-Fi 下）")
    print(f"  登录账号:   {config.WEBUI_USER} / {config.WEBUI_PASS}")
    print("  （密码可在 .env 用 DESKAGENT_PASS 修改）")

    demo = build_ui()
    try:
        demo.launch(
            server_name=config.WEBUI_HOST,
            server_port=config.WEBUI_PORT,
            auth=(config.WEBUI_USER, config.WEBUI_PASS),
        )
    finally:
        daemon_proc.terminate()


if __name__ == "__main__":
    main()
