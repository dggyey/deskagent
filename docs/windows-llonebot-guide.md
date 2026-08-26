# Windows 真机联调手册：接入真实 QQ（LLOneBot）

> 目标：在你自己的 Windows 电脑上，把 DeskAgent 从「mock 后端」切换到「真实 QQ」，
> 让自动回复真的发生在你的 QQ 上。全程约 30 分钟。
>
> 本手册假设你已经在公司电脑上跑通了 mock 流程（见过 WebUI、下过指令、注入过消息）。

---

## 0. 开始前必读（3 条，关乎账号安全）

1. **用小号或私人号测试，不要用工作号。** 非官方接入有理论上的风控风险。
2. **新设备首次登录 QQ 后，先正常使用几天再加机器人。** 别一上来就高频收发消息。
3. **自动回复范围先开「仅私聊 + 白名单 1 个好友」**，观察一两天再放开。

---

## 1. 环境清单

| 项目 | 要求 |
|------|------|
| 系统 | Windows 10 / 11（64 位） |
| Python | 3.10+（推荐用 uv 装 3.12） |
| QQ | 官方 QQ NT 版本（官网下载，9.9.x） |
| LiteLoaderQQNT | 插件加载器 |
| LLOneBot | OneBot 协议插件 |
| 网络 | 能访问 GitHub（下插件用，下不动就用加速镜像） |

---

## 2. 安装 QQ NT

1. 去 https://im.qq.com 下载 Windows 版 QQ（现在默认就是 NT 架构）
2. 正常安装、登录
3. 确认版本：左下角设置 → 关于 QQ，版本号形如 `9.9.x-xxxxx`

> ⚠️ 不要装太老的 TIM / QQ9 旧架构，LLOneBot 只支持 NT 版本。

---

## 3. 安装 LiteLoaderQQNT（插件加载器）

推荐**安装器方式**（自动处理 QQ 目录和启动注入）：

1. 打开 https://github.com/LiteLoaderQQNT/LiteLoaderQQNT/releases
2. 下载 `LiteLoaderQQNT.Installer.exe`（或 `.msix`）
3. **先完全退出 QQ**（托盘右键退出）
4. 运行安装器 → 它会自动检测 QQ 安装路径 → 安装
5. 重新打开 QQ，左侧边栏（或设置里）出现「LiteLoader」相关入口 = 成功

> 装不上时的备用方案（手动）：
> 下载 release 里的 `LiteLoaderQQNT.zip`，解压后整个文件夹放到
> `C:\Program Files\Tencent\QQNT\resources\app\LiteLoader`（按你实际安装目录），
> 再把 `resources\app\app_launcher\index.js` 首行改为
> `require('../LiteLoader');`。QQ 更新后可能需要重做这一步，所以优先用安装器。

---

## 4. 安装 LLOneBot 插件

1. 打开 https://github.com/LLOneBot/LLOneBot/releases
2. 下载最新版 `llonebot-x.x.x.pak` 或 zip 包
3. 放入插件目录（二选一）：
   - 用户目录：`%APPDATA%\QQ\LiteLoader\plugins\`（不存在就新建）
   - 或安装目录：`<QQ 安装目录>\LiteLoader\plugins\`
   - 如果是 zip，解压成文件夹后放入，文件夹名随意（如 `LLOneBot`）
4. 重启 QQ → 设置里能看到 **LLOneBot 配置界面** = 成功

---

## 5. 配置 LLOneBot 的网络服务

打开 QQ 设置 → LiteLoader → LLOneBot，找到「网络配置」，按下表填：

| 配置项 | 值 | 说明 |
|--------|-----|------|
| 启用 HTTP 服务（正向） | ✅ | 端口填 `3000`（被占用可换，记下来改 .env） |
| 启用正向 WebSocket | ✅ | 端口填 `3001` |
| 反向 WebSocket | ❌ 不用开 | DeskAgent 用正向连接 |
| access token | **留空** | 留空最省事；填了的话 .env 里也要配 |
| 上报自身消息（message_sent） | ✅ 如果有该开关 | 没有也没关系，代码有 is_self 兜底 |

保存后，浏览器打开验证：

```
http://127.0.0.1:3000/get_version_info
```

看到 `"app_name":"LLOneBot"` 之类的 JSON = **后端通了**。

再试：

```
http://127.0.0.1:3000/get_friend_list
```

> 注意：刚登录时好友列表可能为空，先在 QQ 客户端里点开一次「联系人」页让它建缓存，再刷新。

---

## 6. 把代码搬到 Windows

方式 A（推荐）：U 盘 / 网盘 把整个 `deskagent` 文件夹拷过去。
方式 B：Windows 上 `git clone https://github.com/dggyey/deskagent.git`。

然后：

```powershell
cd deskagent

# 有 uv 就用 uv（公司电脑装过）；没有就先装：pip install uv 或官网脚本
uv python install 3.12
uv venv --python 3.12 .venv
uv pip install -p .venv\Scripts\python.exe -r requirements.txt

# 没有 uv 的经典方式：
# py -3.12 -m venv .venv
# .venv\Scripts\activate
# pip install -r requirements.txt
```

---

## 7. 配置 .env（关键 3 处）

复制 `.env.example` 为 `.env`，改这几处：

```bash
# 1) LLM（公司电脑那个 DeepSeek key 直接复用即可）
OPENAI_API_KEY=sk-你的key
OPENAI_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash

# 2) 后端指向真实 LLOneBot（不再是 11451 的 mock！）
ONEBOT_HTTP_URL=http://127.0.0.1:3000
ONEBOT_WS_URL=ws://127.0.0.1:3001

# 3) 填你自己的 QQ 号（识别"别人 @ 的是不是我"、防止给自己发消息）
AGENT_OWNER_QQ=你的QQ号

# 4) WebUI 密码改掉
DESKAGENT_PASS=一个强密码
```

---

## 8. 启动与验收

**不要启动 mock_server！** 直接：

```powershell
.venv\Scripts\python.exe web_ui.py
```

打开 http://127.0.0.1:7860 登录后按顺序做：

1. 对话框输入 **`同步联系人`**
   → 右侧记忆/状态区或直接看回复，应报「X 个好友，Y 个群」且是**真实数量**
2. 输入 **`只在私聊里自动回复，白名单加 <一个你信任的好友昵称>`**
3. 让那位好友给你发一句「在吗」
   → 几秒内「QQ 消息记录」面板应出现对方消息 + 🤖 自动回复
4. 满意后再逐步放开范围（全部 / 群聊 / 仅 @）

手机遥控同样可用：同一 Wi-Fi 下手机访问 `http://电脑IP:7860`。

---

## 9. 故障速查表

| 现象 | 排查 |
|------|------|
| `get_version_info` 打不开 | QQ 没启动 / LLOneBot 服务没开 / 端口不是 3000 / 防火墙拦了 |
| 好友列表为空 | 在 QQ 客户端点开一次「联系人」页再刷新 |
| 消息收不到（面板不刷新） | 检查正向 WebSocket 是否启用、端口与 .env 是否一致；重启 web_ui |
| 自己发的消息被当成别人消息回复（刷屏） | `.env` 里 `AGENT_OWNER_QQ` 没填或填错；LLOneBot 开启"上报自身消息" |
| 发消息失败 | 看 WebUI 对话区报错文本；确认 QQ 处于在线状态而非离线保护 |
| QQ 更新后插件失效 | 正常现象，等 LiteLoader/LLOneBot 适配新版，或回退 QQ 版本 |

---

## 10. 可选：开机自启全家桶

1. **QQ 自启**：QQ 设置 → 基本 → 开机自动启动
2. **LLOneBot**：默认随 QQ 启动并恢复服务（其设置里有"随启动开启服务"则勾上）
3. **DeskAgent 自启**：
   ```powershell
   # 写一个 start_deskagent.bat：
   @echo off
   cd /d C:\path\to\deskagent
   start "" /min .venv\Scripts\python.exe web_ui.py
   # 把 bat 快捷方式扔进 shell:startup（运行框输入 shell:startup 回车）
   ```

---

## 11. 收尾心态

- 第一周只开「私聊 + 白名单」，观察自动回复质量
- 敏感拦截面板每天扫一眼，它是你的安全网
- 任何异常（比如 QQ 被踢下线）→ 先停自动回复，再排查

跑通后你就拥有了：一台挂机 Windows + 真 QQ + AI 自动回复 + 手机遥控台。
祝玩得开心。
