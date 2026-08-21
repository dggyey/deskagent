#!/usr/bin/env python3
"""
QQ Agent CLI

最小命令行入口，直接复用 agent_core.QQAgent。
"""
from agent_core import main

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
