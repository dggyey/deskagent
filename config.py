#!/usr/bin/env python3
"""
DeskAgent 配置读取

优先从 .env / 环境变量读取，缺省时使用适合本地开发的默认值。
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

BASE_DIR = Path(__file__).parent
STORAGE_DIR = BASE_DIR / "storage"
STORAGE_DIR.mkdir(exist_ok=True)

DB_PATH = STORAGE_DIR / "deskagent.db"

# LLM（任何 OpenAI 兼容服务都可以，base_url 留空则走 OpenAI 官方）
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")

# OneBot 后端（mock 或真实 LLOneBot）
ONEBOT_HTTP_URL = os.environ.get("ONEBOT_HTTP_URL", "http://127.0.0.1:11451")
ONEBOT_WS_URL = os.environ.get("ONEBOT_WS_URL", "ws://127.0.0.1:11451/ws")
ONEBOT_ACCESS_TOKEN = os.environ.get("ONEBOT_ACCESS_TOKEN", "")

# Agent 行为
OWNER_ID = os.environ.get("AGENT_OWNER_QQ", "")
REPLY_COOLDOWN_SECONDS = float(os.environ.get("AUTO_REPLY_COOLDOWN_SECONDS", "3"))
WORKER_POLL_SECONDS = float(os.environ.get("WORKER_POLL_SECONDS", "2"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
