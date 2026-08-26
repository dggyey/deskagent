# DeskAgent

DeskAgent 是一个运行在 Windows 桌面上的 AI Agent，通过自然语言对话调用各种工具。当前核心能力是控制 QQ 消息的自动收发，未来可扩展文件管理、网页搜索、系统操作、日程提醒等。

项目采用 **LLOneBot + OneBot** 作为 QQ 后端，**MCP（Model Context Protocol）** 作为工具扩展协议，**OpenAI** 作为 LLM 决策核心。

> 在没有安装 QQ 的环境中（比如公司电脑），可以用内置的 `mock_server.py` 直接跑通整个闭环，无需真实 QQ 客户端。

---

## 功能特性

- ✅ 自然语言控制 QQ 自动回复（开启 / 停止 / 查状态）
- ✅ 自动回复范围控制：全部 / 仅私聊 / 仅群聊
- ✅ 白名单 / 黑名单（昵称或 QQ 号均可）
- ✅ 群聊中可设置仅在被 @ 时回复
- ✅ 自定义回复人格（prompt）
- ✅ 主动发送私聊 / 群消息
- ✅ 同一会话冷却时间，防止刷屏
- ✅ 消息级去重，防止重复回复
- ✅ 敏感内容拦截：对方索要验证码/密码/转账时不自动回复，转人工提醒；出站回复含敏感信息时丢弃
- ✅ 长期记忆：记住/忘记/列表，可按好友定向记忆，自动回复时注入上下文；敏感记忆拒收
- ✅ 全部消息本地持久化（SQLite）
- ✅ 内置 OneBot Mock Server + 端到端冒烟测试

---

## 架构

```
┌──────────────────────────────────────┐
│           用户交互入口（CLI）          │
└──────────────┬───────────────────────┘
               │ 自然语言
┌──────────────▼───────────────────────┐
│           Agent 核心 (agent_core)     │
│   LLM Function Calling / 关键词路由   │
└──┬───────────┬───────────────────────┘
   │           │
   │ MCP       │ 共享 SQLite
┌──▼────────┐ ┌▼───────────────────────┐
│qq_mcp_    │ │ OneBotListener         │
│server     │ │  (WebSocket 收消息)    │
│           │ ├────────────────────────┤
└──┬────────┘ │ AutoReplyWorker        │
   │          │  (过滤 → LLM → 回复)   │
   │          └┬───────────────────────┘
   │ OneBot HTTP / WebSocket
┌──▼───────────────────────────────────┐
│  LLOneBot（真实）/ mock（本地测试）    │
└──────────────────────────────────────┘
```

**自动回复决策流程**：

```
QQ 消息 → 监听器入库 → Worker 轮询未处理消息
  → 范围过滤（私聊/群）
  → 黑名单过滤（私聊按会话、群聊按群或发言人）
  → 白名单过滤（非空时只回名单内）
  → 仅 @ 过滤（可选）
  → 冷却时间检查
  → LLM 生成回复（可输出 [[SKIP]] 决定不回复）
  → 发送并落库
```

---

## 快速开始

### 1. 安装 Python 3.10+

本项目要求 Python >= 3.10（代码中使用了 `X | None` 等语法，MCP SDK 也要求 3.10+）。

推荐用 [uv](https://github.com/astral-sh/uv) 管理：

```powershell
# Windows: https://docs.astral.sh/uv/getting-started/installation/
uv python install 3.12
cd deskagent
uv venv --python 3.12 .venv
```

### 2. 安装依赖

```powershell
# uv
uv pip install -p .venv\Scripts\python.exe -r requirements.txt

# 或标准方式
.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 配置环境变量

```powershell
copy .env.example .env
```

编辑 `.env`：

```bash
# 可选：配了就用真实模型，不配就用关键词调试模式
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini

# 开发测试时使用 mock 后端（默认值）
ONEBOT_HTTP_URL=http://127.0.0.1:11451
ONEBOT_WS_URL=ws://127.0.0.1:11451/ws
```

### 3.5（可选但推荐）接入大模型

不配 API Key 时是对话关键词调试模式；配了就解锁完整的自然语言理解和真实自动回复。
任何 OpenAI 兼容服务都支持，例如：

| 服务 | `OPENAI_BASE_URL` | `LLM_MODEL` |
|------|-------------------|-------------|
| OpenAI 官方 | （留空） | `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| OpenRouter（含 Claude） | `https://openrouter.ai/api/v1` | `anthropic/claude-sonnet-4.5` |

填好 `OPENAI_API_KEY` + （可选）`OPENAI_BASE_URL` + `LLM_MODEL` 三行即可。

### 4. 启动 Mock 后端（公司电脑 / 无 QQ 环境）

```powershell
.venv\Scripts\python.exe mock_server.py
```

### 5. 启动交互界面（二选一）

**命令行版**：

```powershell
cd deskagent
.venv\Scripts\python.exe agent_core.py
```

**网页版（推荐）**：

```powershell
cd deskagent
.venv\Scripts\python.exe web_ui.py
```

浏览器打开 http://127.0.0.1:7860 ：

- 左侧：对话窗口，支持全部自然语言指令
- 右侧：自动回复状态 / QQ 消息记录 / 敏感内容提醒 / 长期记忆，每 3 秒自动刷新
- 快捷按钮：一键开启/停止自动回复等
- 「QQ 快捷发送」面板：不经 LLM 直接发消息（昵称或 ID 均可）

### 5.5 手机当遥控器（同一 Wi-Fi 下）

WebUI 默认监听局域网并带登录密码（默认 `admin / deskagent123`，可在 `.env` 用
`DESKAGENT_PASS` 修改）。

1. 启动后，终端会打印「手机访问：http://你的电脑IP:7860」
2. 手机浏览器打开该地址，输入账号密码登录
3. Chrome/Edge 菜单 →「添加到主屏幕」，得到全屏类 App 体验
4. 在「QQ 快捷发送」面板直接发消息，或在对话框下指令

### 6. 尝试对话

```text
你: 同步联系人
Agent: 联系人同步完成：3 个好友，3 个群

你: 开启自动回复
Agent: 自动回复已开启。当前配置：{"enabled": true, "scope": "all", ...}

你: 停止自动回复
Agent: 自动回复已停止。
```

配置了 `OPENAI_API_KEY` 后，还可以说自然语言指令：

```text
你: 只在私聊里自动回复，王总别回，语气像朋友
你: 给技术交流群发消息说下午三点开会
你: 把小李加到白名单
```

---

## 切换到真实 QQ（Windows 环境）

1. 安装 QQ NT 客户端（9.9.x+）
2. 安装 [LiteLoaderQQNT](https://github.com/LiteLoaderQQNT/LiteLoaderQQNT)
3. 安装 [LLOneBot](https://github.com/LLOneBot/LLOneBot) 插件
4. 在 LLOneBot 设置中开启 HTTP + 正向 WebSocket
5. 修改 `.env`：

```bash
ONEBOT_HTTP_URL=http://127.0.0.1:3000
ONEBOT_WS_URL=ws://127.0.0.1:3001
```

6. 重启 `agent_core.py`，代码无需改动

---

## 项目结构

```
deskagent/
├── agent_core.py         # Agent 主进程：CLI + LLM + MCP Client + 监听器/Worker
├── qq_mcp_server.py      # QQ MCP Server：9 个 QQ 工具
├── mock_server.py        # OneBot Mock 后端（本地测试用）
├── auto_reply.py         # 自动回复引擎（过滤 + 冷却 + LLM + 发送）
├── listener.py           # OneBot WebSocket 消息监听器（断线重连）
├── storage.py            # SQLite 存储（消息/联系人/自动回复配置）
├── onebot_client.py      # OneBot HTTP 客户端
├── llm.py                # LLM 调用层（无 Key 时降级为 mock）
├── config.py             # 配置读取
├── cli.py                # 命令行入口
├── smoke_test.py         # 端到端冒烟测试
├── requirements.txt
├── .env.example
└── README.md
```

---

## MCP Tools

| Tool | 说明 |
|------|------|
| `qq_get_status` | 获取 OneBot 后端状态 |
| `qq_get_friend_list` | 获取好友列表（顺带落库） |
| `qq_get_group_list` | 获取群列表（顺带落库） |
| `qq_send_private_msg` | 发送私聊消息 |
| `qq_send_group_msg` | 发送群消息（支持 @） |
| `qq_start_auto_reply` | 启动自动回复（范围/名单/仅@/人格） |
| `qq_stop_auto_reply` | 停止自动回复 |
| `qq_get_auto_reply_status` | 查看自动回复配置 |
| `qq_sync_contacts` | 同步联系人昵称 ↔ ID 映射 |

---

## 开发说明

### 运行冒烟测试

不需要 API Key，不需要真实 QQ：

```powershell
.venv\Scripts\python.exe smoke_test.py
```

验证内容：消息入库去重、黑名单过滤、范围过滤、自动回复发送。

### 关键设计决策

- **MCP SDK 固定 <2.0.0**：2.0 是完全重写版本，API 不兼容
- **消息防重复**：`message_id` 唯一索引 + `message_sent` 事件强制标记 is_self，防止自动回复回复自己造成死循环
- **跨进程共享 SQLite**：MCP 子进程和 Agent 主进程通过数据库共享自动回复配置，写入超时设为 10 秒

---

## 示例指令

- `开启自动回复，用朋友语气`
- `只在群里回复，只回 @ 我的消息`
- `除了王总，别人都自动回复`
- `只给小李自动回`
- `给技术交流群发消息说下午三点开会`
- `查看自动回复状态`
- `停止自动回复`

---

## 注意事项

- 本项目使用的 QQ Bot 方式（LLOneBot / OneBot）并非腾讯官方 API，存在账号风控风险，建议仅个人使用
- 不要在公司电脑上使用工作 QQ 测试
- API Key 存放在 `.env` 文件中，已被 gitignore，不要提交到 GitHub

---

## 路线图

- [x] 消息收发 + 去重
- [x] 自动回复：范围 / 黑白名单 / 仅 @ / 冷却 / 人格
- [x] 敏感内容拦截（入站 + 出站，转人工提醒）
- [x] 长期记忆（全局 + 按联系人定向）
- [x] 端到端冒烟测试
- [x] WebUI（Gradio：对话 + 状态/提醒/记忆面板）
- [ ] 文件操作、网页搜索、系统命令等更多 MCP tools
- [ ] LLM 语义级敏感判断（可选开关）
- [ ] 桌面宠物前端（Tkinter/PyQt）

---

## License

MIT
