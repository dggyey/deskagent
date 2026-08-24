#!/usr/bin/env python3
"""
DeskAgent LLM 调用层

- 有 OPENAI_API_KEY 时调用真实模型
- 没有时降级为 mock 回复，方便公司电脑无 Key 环境调试
"""
from __future__ import annotations

import config

DEFAULT_PERSONA = "你是用户的替身，用自然、简短、口语化的语气回复，不要暴露自己是 AI。"


def _call_openai(system_prompt: str, user_prompt: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=config.OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=512,
    )
    return (resp.choices[0].message.content or "").strip()


def generate_auto_reply(msg: dict, persona: str) -> str | None:
    """根据收到的消息生成自动回复。返回 None 表示不回复。"""
    persona = persona or DEFAULT_PERSONA
    source_label = "好友" if msg["type"] == "private" else f"群「{msg.get('source_name') or msg['source_id']}」"
    user_prompt = (
        f"{source_label} {msg['sender_name'] or msg['sender_id']} 发来消息：\n"
        f"「{msg['content']}」\n\n"
        "请判断是否回复：\n"
        "- 若不需要回复（如刷屏、无意义、敏感内容），只输出 [[SKIP]]\n"
        "- 否则直接输出回复文本，不要带引号和前缀"
    )

    if not config.OPENAI_API_KEY:
        # mock 模式：简单可预测的回复，便于本地测试
        if "不用回" in msg["content"] or "[[SKIP]]" in msg["content"]:
            return None
        return f"[自动回复] 收到啦：{msg['content'][:20]}"

    reply = _call_openai(persona, user_prompt)
    if not reply or "[[SKIP]]" in reply:
        return None
    return reply


def chat(system_prompt: str, user_prompt: str) -> str:
    """通用单次对话，供 Agent 决策使用。"""
    if not config.OPENAI_API_KEY:
        return f"[mock-llm] {user_prompt[:80]}"
    return _call_openai(system_prompt, user_prompt)
