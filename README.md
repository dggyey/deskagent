# QQ Agent

一个基于 Windows 平台运行的 AI Agent，通过自然语言对话控制 QQ 消息的自动收发、人格切换与任务执行。

项目采用 **LLOneBot + OneBot** 作为 QQ 后端，**MCP（Model Context Protocol）** 作为工具扩展协议，**OpenAI/Claude** 作为 LLM 决策核心。

> 在公司或没有安装 QQ 的环境下，可以使用内置的 `mock_server.py` 直接跑通整个链路，无需真实 QQ 客户端。

---

## 功能特性

- 自然语言控制 QQ 自动回复
- 支持指定自动回复范围：全部 / 仅私聊 / 仅群聊
- 支持白名单、黑名单、仅 @ 时回复
- 支持自定义回复人格（prompt）
- 支持主动发送私聊 / 群消息
- 内置 MCP Server，所有 QQ 能力以 tools 形式暴露
- 内置 OneBot Mock Server，方便本地开发测试
- 回家后只需修改环境变量即可切换为真实 QQ

---

## 架构

```
┌──────────────────────────────────────┐
│           用户交互入口                │
│      CLI / WebUI / 桌面宠物           │
└──────────────┬───────────────────────┘
               │
┌──────────────▼───────────────────────┐
│           Agent 核心                  │
│   LLM + MCP Client + 自动回复策略     │
└──────────────┬───────────────────────┘
               │ MCP Protocol
┌──────────────▼───────────────────────┐
│          qq-mcp-server                │
└──────────────┬───────────────────────┘
               │ OneBot HTTP / WebSocket
┌──────────────▼───────────────────────┐
│     LLOneBot (真实) / mock (测试)     │
└──────────────┬───────────────────────┘
               │
            QQ 服务器 / 本地 mock
```

---

## 快速开始

### 1. 克隆项目并安装依赖

```powershell
cd qq-agent
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 配置环境变量

```powershell
copy .env.example .env
```

编辑 `.env`：

```bash
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini

# 开发测试时使用 mock
ONEBOT_HTTP_URL=http://127.0.0.1:11451
ONEBOT_WS_URL=ws://127.0.0.1:11451/ws
```

### 3. 启动 Mock 后端

```powershell
python mock_server.py
```

### 4. 启动 Agent CLI

另开一个终端：

```powershell
.venv\Scripts\activate
python agent_core.py
```

### 5. 尝试对话

```text
你: 开启自动回复，只在私聊里回
Agent: 已启动自动回复...

你: 给小李发消息说我今晚加班
Agent: 已发送消息...

你: 停止自动回复
Agent: 已停止自动回复。
```

---

## 切换到真实 QQ（回家/生产环境）

1. 在 Windows 上安装 QQ NT 客户端
2. 安装 LiteLoaderQQNT
3. 安装 LLOneBot 插件
4. 在 LLOneBot 中开启 HTTP 和反向 WebSocket
5. 修改 `.env`：

```bash
ONEBOT_HTTP_URL=http://127.0.0.1:3000
ONEBOT_WS_URL=ws://127.0.0.1:3001
```

6. 重新运行 `agent_core.py`

代码不需要任何改动。

---

## 项目结构

```
qq-agent/
├── mock_server.py        # OneBot Mock 后端（本地测试）
├── qq_mcp_server.py      # QQ MCP Server
├── agent_core.py         # Agent 核心（LLM + MCP Client）
├── cli.py                # 命令行入口
├── requirements.txt      # Python 依赖
├── .env.example          # 配置模板
└── README.md             # 本文件
```

---

## MCP Tools

`qq_mcp_server.py` 提供以下 tools：

| Tool | 说明 |
|------|------|
| `qq_get_status` | 获取 OneBot 后端状态 |
| `qq_get_friend_list` | 获取好友列表 |
| `qq_get_group_list` | 获取群列表 |
| `qq_send_private_msg` | 发送私聊消息 |
| `qq_send_group_msg` | 发送群消息 |
| `qq_start_auto_reply` | 启动自动回复 |
| `qq_stop_auto_reply` | 停止自动回复 |
| `qq_get_auto_reply_status` | 查看自动回复配置 |

---

## 示例指令

- `开启自动回复，用朋友语气`
- `只在群里回复，只回复 @ 我的消息`
- `除了王总，别人都自动回复`
- `给技术交流群发消息说下午三点开会`
- `查看自动回复状态`
- `停止自动回复`

---

## 注意事项

- 本项目使用的 QQ Bot 方式（LLOneBot / OneBot）并非腾讯官方 API，存在账号风控风险，建议仅个人使用。
- 不要在公司工作电脑上使用工作 QQ 测试。
- API Key 存放在 `.env` 文件中，不要提交到 GitHub。

---

## 未来计划

- [ ] 自动回复 Worker：监听 WebSocket 消息并自动回复
- [ ] SQLite 消息持久化
- [ ] 黑白名单实时过滤
- [ ] 长期记忆（向量数据库）
- [ ] WebUI / 桌面宠物前端
- [ ] 网页搜索、文件操作等更多 MCP tools

---

## License

MIT
