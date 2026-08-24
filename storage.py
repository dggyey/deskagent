#!/usr/bin/env python3
"""
DeskAgent 存储层（SQLite）

- messages：所有收发消息，message_id 唯一，用于去重
- contacts：好友/群名称 -> ID 映射
- auto_reply_config：自动回复配置（单行）

使用标准库 sqlite3 + 锁，跨线程调用安全（监听器线程 / Worker 线程 / Agent 主循环）。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time

import config

_LOCK = threading.Lock()


def _connect() -> sqlite3.Connection:
    # timeout：Agent 主进程与 MCP 子进程共享同一个数据库，给跨进程写入留出等待时间
    conn = sqlite3.connect(config.DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _LOCK, _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT UNIQUE,
                message_type TEXT NOT NULL,           -- private / group
                source_id TEXT NOT NULL,              -- user_id 或 group_id
                sender_id TEXT,
                sender_name TEXT,
                content TEXT,
                is_self INTEGER DEFAULT 0,            -- 是否本人发出
                is_auto_reply INTEGER DEFAULT 0,      -- 是否由自动回复发出
                handled INTEGER DEFAULT 0,            -- 自动回复是否已处理
                reply_content TEXT,
                created_at REAL
            );

            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,                   -- friend / group
                target_id TEXT NOT NULL,
                name TEXT NOT NULL,
                updated_at REAL,
                UNIQUE(kind, target_id)
            );

            CREATE TABLE IF NOT EXISTS auto_reply_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                enabled INTEGER DEFAULT 0,
                scope TEXT DEFAULT 'all',             -- all / private / group
                whitelist TEXT DEFAULT '[]',          -- JSON: 目标 ID 列表
                blacklist TEXT DEFAULT '[]',
                only_when_at INTEGER DEFAULT 0,
                persona TEXT DEFAULT '',
                updated_at REAL
            );

            INSERT OR IGNORE INTO auto_reply_config (id) VALUES (1);
            """
        )


# ---------------------------------------------------------------------------
# messages
# ---------------------------------------------------------------------------

def save_message(message_id: str, message_type: str, source_id: str,
                 sender_id: str, sender_name: str, content: str,
                 is_self: bool = False, is_auto_reply: bool = False) -> bool:
    """保存一条消息。返回 True 表示是新消息，False 表示已存在（去重）。"""
    with _LOCK, _connect() as conn:
        try:
            conn.execute(
                """
                INSERT INTO messages
                    (message_id, message_type, source_id, sender_id, sender_name,
                     content, is_self, is_auto_reply, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (message_id, message_type, source_id, sender_id, sender_name,
                 content, int(is_self), int(is_auto_reply), time.time()),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def get_unhandled_messages(limit: int = 20) -> list[sqlite3.Row]:
    with _LOCK, _connect() as conn:
        return conn.execute(
            """
            SELECT * FROM messages
            WHERE handled = 0 AND is_self = 0
            ORDER BY created_at ASC LIMIT ?
            """,
            (limit,),
        ).fetchall()


def mark_handled(msg_id: int, reply_content: str | None,
                 is_auto_reply: bool = False) -> None:
    with _LOCK, _connect() as conn:
        conn.execute(
            "UPDATE messages SET handled = 1, reply_content = ?, is_auto_reply = ? WHERE id = ?",
            (reply_content, int(is_auto_reply), msg_id),
        )


# ---------------------------------------------------------------------------
# contacts
# ---------------------------------------------------------------------------

def upsert_contact(kind: str, target_id: str, name: str) -> None:
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO contacts (kind, target_id, name, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(kind, target_id) DO UPDATE SET
                name = excluded.name, updated_at = excluded.updated_at
            """,
            (kind, target_id, name, time.time()),
        )


def get_contacts(kind: str | None = None) -> list[sqlite3.Row]:
    with _LOCK, _connect() as conn:
        if kind:
            return conn.execute(
                "SELECT * FROM contacts WHERE kind = ? ORDER BY name", (kind,)
            ).fetchall()
        return conn.execute("SELECT * FROM contacts ORDER BY kind, name").fetchall()


def resolve_contact(kind: str, name_or_id: str) -> str | None:
    """把昵称或 ID 解析为 target_id。"""
    with _LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT target_id FROM contacts WHERE kind = ? AND (name = ? OR target_id = ?)",
            (kind, name_or_id, name_or_id),
        ).fetchone()
        return row["target_id"] if row else None


# ---------------------------------------------------------------------------
# auto_reply_config
# ---------------------------------------------------------------------------

def get_auto_reply_config() -> dict:
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM auto_reply_config WHERE id = 1").fetchone()
    return {
        "enabled": bool(row["enabled"]),
        "scope": row["scope"],
        "whitelist": json.loads(row["whitelist"]),
        "blacklist": json.loads(row["blacklist"]),
        "only_when_at": bool(row["only_when_at"]),
        "persona": row["persona"],
    }


def set_auto_reply_config(**fields) -> dict:
    """按字段更新自动回复配置，返回最新配置。"""
    allowed = {"enabled", "scope", "whitelist", "blacklist", "only_when_at", "persona"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if updates:
        if "whitelist" in updates:
            updates["whitelist"] = json.dumps(updates["whitelist"], ensure_ascii=False)
        if "blacklist" in updates:
            updates["blacklist"] = json.dumps(updates["blacklist"], ensure_ascii=False)
        if "enabled" in updates:
            updates["enabled"] = int(updates["enabled"])
        if "only_when_at" in updates:
            updates["only_when_at"] = int(updates["only_when_at"])
        updates["updated_at"] = time.time()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        with _LOCK, _connect() as conn:
            conn.execute(
                f"UPDATE auto_reply_config SET {set_clause} WHERE id = 1",
                tuple(updates.values()),
            )
    return get_auto_reply_config()
