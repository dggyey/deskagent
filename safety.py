#!/usr/bin/env python3
"""
DeskAgent 敏感内容拦截

两道防线：
  1. 入站检查 check_inbound：对方消息涉及敏感请求（要验证码、密码、转账、借钱等）时，
     不交给 LLM 自动回复，改为生成一条本地提醒让用户人工处理。
  2. 出站检查 check_outbound：自动回复内容包含敏感信息（验证码、密码、卡号、身份证号）时，
     直接丢弃不发送，同样落一条提醒。

规则层先行（快、零成本）；配置了 OPENAI_API_KEY 且规则命中不了时，
可再让 LLM 做语义判断（check_inbound_llm），默认关闭语义层以避免误伤和额外开销。
"""
from __future__ import annotations

import re

# 入站敏感请求模式：对方在索要这些内容时绝不允许自动回复
INBOUND_SENSITIVE_PATTERNS: list[tuple[str, str]] = [
    (r"验证码", "对方索要验证码"),
    (r"(发|告诉我|说一下|给我).{0,6}(密码|口令)", "对方索要密码"),
    (r"(银行卡|卡号|账号).{0,10}(发|告诉|给我)", "对方索要账号/卡号"),
    (r"(转账|转钱|汇款|打钱)", "涉及转账/汇款"),
    (r"(借|借给).{0,6}(钱|块|元)", "涉及借钱"),
    (r"(身份证(号)?|证件号).{0,10}(发|告诉|给我)", "对方索要身份证号"),
    (r"(支付密码|交易密码)", "对方索要支付密码"),
]

# 出站敏感内容模式：自动回复正文中不允许出现这些
OUTBOUND_SENSITIVE_PATTERNS: list[tuple[str, str]] = [
    (r"验证码\s*[是为]?\s*[\d]{4,8}", "回复中包含验证码数字"),
    (r"(我的|你的)?密码\s*[是为:：]\s*\S{4,}", "回复中包含密码"),
    (r"\d{16,19}", "回复中包含疑似银行卡号（16-19 位连续数字）"),
    (r"\d{17}[\dXx]", "回复中包含疑似身份证号"),
    (r"(支付|交易)密码", "回复中包含支付密码字样"),
]


def _first_match(content: str, patterns: list[tuple[str, str]]) -> str | None:
    for pattern, reason in patterns:
        if re.search(pattern, content):
            return reason
    return None


def check_inbound(content: str) -> str | None:
    """入站检查。返回命中原因，None 表示通过。"""
    return _first_match(content, INBOUND_SENSITIVE_PATTERNS)


def check_outbound(reply: str) -> str | None:
    """出站检查。返回命中原因，None 表示可以发送。"""
    return _first_match(reply, OUTBOUND_SENSITIVE_PATTERNS)
