# Telegram Claude Bot

> [简体中文](./README.md) · [繁體中文](./README.zh-TW.md) · [English](./README.en.md) · [日本語](./README.ja.md) · [한국어](./README.ko.md)

把 [Claude Code](https://claude.com/claude-code) CLI 套上一个 Telegram 接口——在手机上发一条命令，就能让本地工作站上的 Claude 跑长任务、改代码、提 commit。

## 特性

- **多会话并行**：一个会话对应一个项目目录，会话之间任务互不阻塞
- **后台执行 + 进度推送**：长任务（默认 1 小时硬上限）丢到后台跑，前 5 分钟每 4 秒刷新进度，之后每 2 分钟刷新一次，完成后主动推送结果
- **预览模式**：`/preview` 让 Claude 先列计划，再 `/confirm` 真改
- **任务管理**：`/tasks` 看全部并行任务、`/kill` 实时终止子进程
- **白名单鉴权**：只接受指定 Telegram User ID 的请求
- **路径自动补全**：`shulex/` 子目录可省略前缀（项目特化，可改）
- **崩溃恢复**：sessions.json 持久化，bot 重启时清理 stale 标记并主动通知用户

## 命令

```
/help               显示完整帮助
/new <名> <项目>    新建会话，例：/new refactor shulex-gpt
/switch <名>        切换会话
/list               列出所有会话
/drop <名>          删除会话（不能删正在跑的）
/status             当前会话状态
/tasks              全部任务运行状态
/kill [名]          终止当前（或指定）会话的任务
/run <需求>         直接执行
/preview <需求>     预览模式：先列计划
/confirm            确认执行预览过的任务
/cancel             取消预览
/mode auto|preview  默认模式（直接发文本走这个模式）
```

直接发普通文本会按当前模式触发 `/run` 或 `/preview`。

## 安装

### 1. 前置依赖

- Python **3.10+**
- [Claude Code CLI](https://claude.com/claude-code) 已安装并登录
- Windows 用户需 Git Bash（Claude CLI 依赖）

### 2. 装依赖

```bash
git clone <你的仓库 URL>
cd telegram-claude-bot
pip install -r requirements.txt
```

### 3. 配 `.env`

```bash
cp .env.example .env
```

编辑 `.env`：

```ini
BOT_TOKEN=从 @BotFather 申请的 token
ALLOWED_USER_ID=你的 Telegram User ID（@userinfobot 查）
WORKSPACE_ROOT=E:/workspace
GIT_BASH_PATH=E:/develop/git/Git/usr/bin/bash.exe   # Windows 必填
```

### 4. 启动

```bash
python bot.py
```

#### Windows 自启动（可选）

以管理员身份运行 `setup_autostart.ps1`，会注册到任务计划程序，开机自动启动；或用 `start_bot.vbs` 静默启动。

## 项目结构

```
bot.py             主入口，注册命令处理器
handler.py         命令业务逻辑
task_manager.py    后台任务调度 + 进度节流
claude_runner.py   异步流式调用 claude CLI（解析 stream-json）
session_store.py   sessions.json 持久化
path_resolver.py   项目路径解析（含 shulex 子目录缓存）
git_helper.py      git diff 摘要
text_utils.py      长消息按段落/行切分
config.py          .env 加载
```

## 工作原理

1. Telegram 收到命令 → `handler.py` 校验白名单
2. 命令派发到 `task_manager.start()`，后台 asyncio 任务驱动 `claude_runner.run_async()`
3. `claude_runner` 以 `--output-format stream-json` 启动 `claude.cmd`，解析事件流（`tool_use` / `text` / `result`）
4. `task_manager` 节流 `edit_message_text` 刷新进度消息
5. 任务完成时把进度消息编辑成 header，再附 `git diff` 摘要发送完整结果

## 注意事项

- 单会话同一时刻只能跑一个任务，多任务请用多会话
- 任务硬上限 1 小时（`HARD_LIMIT_SEC`），到点强杀子进程
- 同一会话多次 `/run` 自动续接 Claude 上下文（`--resume <session_id>`）
- `bot.log` 已在 `.gitignore` 中，请不要 commit

## License

MIT
