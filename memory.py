#!/usr/bin/env python3
"""
DeskAgent 长期记忆

- remember(text)：解析"记住 XX：内容"，XX 是好友/群昵称时存入对方作用域，否则存全局
- forget(text)：按关键词删除记忆
- list_text()：把记忆列表渲染成文本

记忆内容含敏感词（密码/验证码/卡号等）时直接拒收。
"""
from __future__ import annotations

import re

import storage


def remember(text: str) -> str:
    text = re.sub(r"^(帮我|请)?(记住|记得|记一下)[:：,，\s]*", "", text).strip()
    if not text:
        return "要记住什么？格式示例：记住 小李：喜欢美式咖啡"

    # "记住 小李：喜欢美式咖啡" -> 作用域为小李
    m = re.match(r"^(\S+?)[:：](.+)$", text)
    if m:
        name, content = m.group(1).strip(), m.group(2).strip()
        friend_id = storage.resolve_contact("friend", name)
        group_id = storage.resolve_contact("group", name)
        scope = friend_id or group_id or "*"
        label = name if scope != "*" else "全局"
    else:
        scope, content, label = "*", text, "全局"

    if storage.is_memory_blocked(content):
        return "不能记住包含密码/验证码/卡号等敏感信息的内容。"

    storage.add_memory(scope, content)
    return f"已记住（{label}）：{content}"


def forget(text: str) -> str:
    keyword = re.sub(r"^(帮我|请)?(忘记|忘掉|删除记忆)[:：,，\s]*", "", text).strip()
    if not keyword:
        return "要忘记哪条记忆？给出关键词即可。"
    n_friend = storage.forget_memory("*", keyword)
    n_scope = 0
    for row in storage.get_memories(limit=200):
        n_scope += storage.forget_memory(row["scope"], keyword)
    total = n_friend + n_scope
    return f"已删除 {total} 条记忆。" if total else "没有找到匹配的记忆。"


def list_text() -> str:
    rows = storage.get_memories(limit=50)
    if not rows:
        return "目前还没有长期记忆。说「记住 小李：喜欢美式」就能让我记住。"
    lines = ["我记得这些："]
    for row in rows:
        tag = "全局" if row["scope"] == "*" else row["scope"]
        lines.append(f"- [{tag}] {row['content']}")
    return "\n".join(lines)
