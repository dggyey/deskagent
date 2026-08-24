#!/usr/bin/env python3
"""
端到端闭环冒烟测试（不需要 API Key，不需要真实 QQ）

流程：
  1. 启动 mock_server（子进程）
  2. 通过 HTTP 调用 /mock/inject_message 注入一条"小李"的私聊消息
  3. 在数据库里开启自动回复
  4. 验证：监听器收到消息入库 -> Worker 生成回复 -> 调 mock 发送 -> mock 收到 /send_private_msg
  5. 清理

用法：.venv/bin/python smoke_test.py
"""
from __future__ import annotations

import httpx
import subprocess
import sys
import time

MOCK_PORT = 11457  # 用不同端口避免与开发实例冲突
BASE = f"http://127.0.0.1:{MOCK_PORT}"


def wait_for_mock(timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(f"{BASE}/get_version_info", timeout=1).json().get("status") == "ok":
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def main() -> int:
    import os

    os.environ["ONEBOT_HTTP_URL"] = BASE
    os.environ["ONEBOT_WS_URL"] = f"ws://127.0.0.1:{MOCK_PORT}/ws"

    # 必须在设置环境变量之后导入自己的模块
    import config
    config.ONEBOT_HTTP_URL = BASE
    config.ONEBOT_WS_URL = f"ws://127.0.0.1:{MOCK_PORT}/ws"
    config.OWNER_ID = "1"
    config.REPLY_COOLDOWN_SECONDS = 0.1

    import storage
    import onebot_client
    from listener import listener
    from auto_reply import worker

    storage.init_db()

    # 1. 起 mock
    env = {**os.environ, "MOCK_PORT": str(MOCK_PORT), "MOCK_AUTO_INJECT": "0"}
    proc = subprocess.Popen(
        [sys.executable, "mock_server.py"], env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    print("[test] mock_server 启动中...")
    if not wait_for_mock():
        print("[test] FAIL: mock_server 没能启动")
        proc.terminate()
        return 1
    print("[test] mock_server 已就绪")

    failures = []

    try:
        # 2. 起监听器与 Worker
        listener.start()
        worker.start()
        time.sleep(0.5)

        # 3. 开启自动回复（仅私聊，黑名单：王总）
        contact_王总 = "10002"
        storage.set_auto_reply_config(
            enabled=True,
            scope="private",
            blacklist=[contact_王总],
            persona="朋友语气",
        )
        cfg = storage.get_auto_reply_config()
        print(f"[test] 自动回复配置: {cfg}")
        assert cfg["enabled"] and cfg["scope"] == "private"

        # 4. 注入一条小李的私聊消息
        r1 = httpx.post(f"{BASE}/mock/inject_message", json={
            "message_type": "private", "name": "小李", "content": "在吗？",
        }, timeout=3).json()
        print(f"[test] 注入小李消息: message_id={r1['data']['message_id']}")

        # 5. 注入一条王总的私聊消息（黑名单，不应回复）
        r2 = httpx.post(f"{BASE}/mock/inject_message", json={
            "message_type": "private", "name": "王总", "content": "方案呢？",
        }, timeout=3).json()
        print(f"[test] 注入王总消息（黑名单）: message_id={r2['data']['message_id']}")

        # 6. 注入一条群消息（范围仅私聊，不应回复）
        r3 = httpx.post(f"{BASE}/mock/inject_message", json={
            "message_type": "group", "name": "技术交流群", "content": "大家下午开会",
        }, timeout=3).json()
        print(f"[test] 注入群消息（范围外）: message_id={r3['data']['message_id']}")

        # 等待处理
        time.sleep(4)

        # 7. 校验
        import sqlite3
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT sender_name, content, is_auto_reply, reply_content, handled FROM messages WHERE is_self = 0"
        ).fetchall()

        handled_all = all(row["handled"] for row in rows)
        print(f"[test] 所有消息均已标记处理: {handled_all}")
        if not handled_all:
            failures.append("存在未处理的消息")

        replies = {row["sender_name"]: row for row in rows}

        # 小李：应收到自动回复
        xiaoli = replies.get("小李")
        if not xiaoli or not xiaoli["reply_content"]:
            failures.append("小李的消息未收到自动回复")
        else:
            print(f"[test] 小李收到自动回复: {xiaoli['reply_content']}")

        # 王总：黑名单，不应回复
        wangzong = replies.get("王总")
        if wangzong and wangzong["reply_content"]:
            failures.append(f"黑名单中的王总不该收到回复，但收到: {wangzong['reply_content']}")
        else:
            print("[test] 王总（黑名单）正确地没有收到回复")

        # 群消息：范围外，不应回复
        qun = replies.get("小李")  # 群消息的 sender 是小李，需按 message_type 区分
        conn2 = sqlite3.connect(config.DB_PATH)
        conn2.row_factory = sqlite3.Row
        group_row = conn2.execute(
            "SELECT reply_content FROM messages WHERE is_self=0 AND message_type='group'"
        ).fetchone()
        if group_row and group_row["reply_content"]:
            failures.append("范围仅限私聊，但群消息被回复了")
        else:
            print("[test] 群消息（范围外）正确地没有收到回复")

        # 去重校验：同一事件重复注入
        dup = storage.save_message(
            message_id=r1["data"]["message_id"], message_type="private",
            source_id="10001", sender_id="10001", sender_name="小李",
            content="在吗？",
        )
        if dup:
            failures.append("去重失败：重复消息被再次入库")
        else:
            print("[test] 消息去重正常")

        # 主动发消息能力
        mid = onebot_client.send_private_msg("10001", "手动测试消息")
        print(f"[test] 主动发送私聊: message_id={mid}")

    finally:
        storage.set_auto_reply_config(enabled=False)
        listener.stop()
        worker.stop()
        proc.terminate()
        proc.wait(timeout=5)

    print()
    if failures:
        print("[test] 冒烟测试失败:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("[test] ✅ 冒烟测试全部通过：闭环已打通")
    return 0


if __name__ == "__main__":
    sys.exit(main())
