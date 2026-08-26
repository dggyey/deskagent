#!/usr/bin/env python3
"""
DeskAgent 常驻服务（守护进程）

职责单一：
  - OneBotListener：实时接收 QQ 消息入库
  - AutoReplyWorker：按配置自动回复（过滤/冷却/LLM/敏感拦截）

UI 层（web_ui.py / agent_core.py）只负责对话和展示，与后台服务完全解耦。
真实 Windows 部署时，这个进程和 LLOneBot 一起开机自启。

运行：python daemon.py      （Ctrl+C 停止）
"""
from __future__ import annotations

import logging
import time

import config
import storage
from auto_reply import worker as auto_reply_worker
from listener import listener

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> None:
    storage.init_db()
    listener.start()
    auto_reply_worker.start()
    print("=" * 46)
    print("DeskAgent 守护服务已启动（Ctrl+C 停止）")
    print("后端:", config.ONEBOT_HTTP_URL)
    print("自动回复由数据库配置控制，用 web_ui/CLI 说「开启自动回复」即可")
    print("=" * 46)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        auto_reply_worker.stop()
        listener.stop()
        print("守护服务已停止。")


if __name__ == "__main__":
    main()
