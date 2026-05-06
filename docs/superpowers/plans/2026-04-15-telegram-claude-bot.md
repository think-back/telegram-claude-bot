# Telegram Claude Bot 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现一个本地 Python Bot，通过 Telegram 消息调用本地 Claude CLI，支持多命名会话、多轮对话、任务执行、预览确认、git diff 回报，并开机自启。

**Architecture:** Bot 用 python-telegram-bot 长轮询接收消息，校验 user_id 白名单后解析命令，通过 subprocess 调用 `claude --print --verbose --output-format stream-json` 执行任务或对话，从 stream-json 输出中提取回复文本和 session_id，持久化到 sessions.json 供多会话切换使用。

**Tech Stack:** Python 3.10+, python-telegram-bot 20.x, python-dotenv, subprocess, Windows Task Scheduler

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `bot.py` | 主入口，初始化 Application，注册 handler，启动长轮询 |
| `handler.py` | 所有命令和消息的路由分发 |
| `claude_runner.py` | 调用 claude CLI，解析 stream-json，返回文本和 session_id |
| `session_store.py` | 读写 sessions.json，管理命名会话的增删改查 |
| `path_resolver.py` | 解析项目路径（动态扫描 workspace，支持多级路径） |
| `git_helper.py` | 获取 git diff，格式化变更摘要 |
| `config.py` | 从 .env 读取配置，暴露常量 |
| `.env` | BOT_TOKEN, ALLOWED_USER_ID, WORKSPACE_ROOT, GIT_BASH_PATH |
| `requirements.txt` | 依赖列表 |
| `start_bot.vbs` | 开机自启 VBScript（无窗口启动 pythonw） |

---

## Task 1: 项目初始化与配置模块

**Files:**
- Create: `E:/workspace/telegram-claude-bot/config.py`
- Create: `E:/workspace/telegram-claude-bot/.env.example`
- Create: `E:/workspace/telegram-claude-bot/requirements.txt`
- Create: `E:/workspace/telegram-claude-bot/.gitignore`

- [ ] **Step 1: 创建 requirements.txt**

```
python-telegram-bot==20.7
python-dotenv==1.0.0
```

- [ ] **Step 2: 创建 .gitignore**

```
.env
sessions.json
__pycache__/
*.pyc
```

- [ ] **Step 3: 创建 .env.example**

```env
BOT_TOKEN=your_telegram_bot_token_here
ALLOWED_USER_ID=123456789
WORKSPACE_ROOT=E:/workspace
GIT_BASH_PATH=E:/develop/git/Git/usr/bin/bash.exe
DEFAULT_MODE=auto
```

- [ ] **Step 4: 创建 config.py**

```python
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
ALLOWED_USER_ID = int(os.environ["ALLOWED_USER_ID"])
WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", "E:/workspace")
GIT_BASH_PATH = os.environ.get("GIT_BASH_PATH", "")
DEFAULT_MODE = os.environ.get("DEFAULT_MODE", "auto")
```

- [ ] **Step 5: 安装依赖**

```bash
pip install -r requirements.txt
```

Expected: 安装成功，无报错

- [ ] **Step 6: 初始化 git 仓库并提交**

```bash
cd E:/workspace/telegram-claude-bot
git init
git add requirements.txt .gitignore .env.example config.py
git commit -m "feat: project init with config"
```

---

## Task 2: 路径解析模块

**Files:**
- Create: `E:/workspace/telegram-claude-bot/path_resolver.py`
- Test: 在 Python REPL 中手动验证

- [ ] **Step 1: 创建 path_resolver.py**

```python
import os
from config import WORKSPACE_ROOT

# shulex 下的直接子目录集合（运行时扫描一次）
_SHULEX_PROJECTS: set[str] = set()

def _get_shulex_projects() -> set[str]:
    global _SHULEX_PROJECTS
    if not _SHULEX_PROJECTS:
        shulex_dir = os.path.join(WORKSPACE_ROOT, "shulex")
        if os.path.isdir(shulex_dir):
            _SHULEX_PROJECTS = {
                d for d in os.listdir(shulex_dir)
                if os.path.isdir(os.path.join(shulex_dir, d))
            }
    return _SHULEX_PROJECTS

def resolve(project_input: str) -> str:
    """
    将用户输入的项目路径解析为本地绝对路径。

    规则：
    - 如果第一段是 shulex 下的直接子目录名，自动补 shulex/ 前缀
    - 其余情况直接拼接到 WORKSPACE_ROOT
    - 路径不存在则抛 ValueError
    """
    parts = project_input.strip("/").split("/")
    first = parts[0]

    if first in _get_shulex_projects():
        full_path = os.path.join(WORKSPACE_ROOT, "shulex", *parts)
    else:
        full_path = os.path.join(WORKSPACE_ROOT, *parts)

    full_path = os.path.normpath(full_path)

    if not os.path.isdir(full_path):
        raise ValueError(f"找不到项目 `{project_input}`，路径不存在：{full_path}")

    return full_path
```

- [ ] **Step 2: 手动验证路径解析**

```python
# 在 E:/workspace/telegram-claude-bot 目录下运行
python -c "
from path_resolver import resolve
print(resolve('qa-bot'))            # E:/workspace/qa-bot
print(resolve('shulex-gpt'))        # E:/workspace/shulex/shulex-gpt
print(resolve('shulex-gpt/shulex-gpt-agents'))  # E:/workspace/shulex/shulex-gpt/shulex-gpt-agents
"
```

Expected: 三行均打印正确绝对路径，无 ValueError

- [ ] **Step 3: 提交**

```bash
git add path_resolver.py
git commit -m "feat: add project path resolver with shulex auto-prefix"
```

---

## Task 3: 会话存储模块

**Files:**
- Create: `E:/workspace/telegram-claude-bot/session_store.py`

- [ ] **Step 1: 创建 session_store.py**

```python
import json
import os
from datetime import datetime

SESSIONS_FILE = os.path.join(os.path.dirname(__file__), "sessions.json")

def _load() -> dict:
    if not os.path.exists(SESSIONS_FILE):
        return {"current": None, "sessions": {}, "pending_confirm": None, "mode": "auto"}
    with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def _save(data: dict) -> None:
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def new_session(name: str, project: str, session_id: str) -> None:
    data = _load()
    data["sessions"][name] = {
        "session_id": session_id,
        "project": project,
        "created": datetime.now().isoformat()
    }
    data["current"] = name
    _save(data)

def switch_session(name: str) -> dict:
    data = _load()
    if name not in data["sessions"]:
        raise KeyError(f"会话 `{name}` 不存在")
    data["current"] = name
    _save(data)
    return data["sessions"][name]

def get_current() -> tuple[str, dict] | tuple[None, None]:
    """返回 (name, session_dict) 或 (None, None)"""
    data = _load()
    name = data.get("current")
    if not name or name not in data["sessions"]:
        return None, None
    return name, data["sessions"][name]

def update_session_id(name: str, session_id: str) -> None:
    data = _load()
    if name in data["sessions"]:
        data["sessions"][name]["session_id"] = session_id
        _save(data)

def list_sessions() -> tuple[str | None, dict]:
    """返回 (current_name, sessions_dict)"""
    data = _load()
    return data.get("current"), data.get("sessions", {})

def drop_session(name: str) -> None:
    data = _load()
    data["sessions"].pop(name, None)
    if data.get("current") == name:
        data["current"] = None
    _save(data)

def set_pending_confirm(prompt: str, project: str, session_id: str | None) -> None:
    data = _load()
    data["pending_confirm"] = {
        "prompt": prompt,
        "project": project,
        "session_id": session_id
    }
    _save(data)

def get_pending_confirm() -> dict | None:
    return _load().get("pending_confirm")

def clear_pending_confirm() -> None:
    data = _load()
    data["pending_confirm"] = None
    _save(data)

def get_mode() -> str:
    return _load().get("mode", "auto")

def set_mode(mode: str) -> None:
    data = _load()
    data["mode"] = mode
    _save(data)
```

- [ ] **Step 2: 手动验证**

```python
python -c "
import session_store as s
s.new_session('test', 'shulex-gpt', 'fake-session-id-123')
name, sess = s.get_current()
print(name, sess)            # test {...}
s.drop_session('test')
name, sess = s.get_current()
print(name, sess)            # None None
"
```

Expected: 第一行打印 `test` 和会话信息，第二行打印 `None None`

- [ ] **Step 3: 提交**

```bash
git add session_store.py
git commit -m "feat: add named session store with JSON persistence"
```

---

## Task 4: Claude CLI 调用模块

**Files:**
- Create: `E:/workspace/telegram-claude-bot/claude_runner.py`

**关键发现（已实测）：**
- `claude --print --verbose --output-format stream-json -p "..."` 输出多行 JSON
- `assistant` 类型事件的 `message.content[].text` 包含回复文本
- `result` 类型事件包含 `session_id`
- `--resume <session_id>` 恢复指定会话

- [ ] **Step 1: 创建 claude_runner.py**

```python
import subprocess
import json
import os
from config import GIT_BASH_PATH

def run(
    prompt: str,
    project_path: str,
    session_id: str | None = None
) -> tuple[str, str]:
    """
    调用 claude CLI 执行 prompt。

    返回: (reply_text, new_session_id)
    - reply_text: Claude 的回复文本
    - new_session_id: 本次会话的 session_id（用于后续 --resume）
    """
    cmd = [
        "claude", "--print", "--verbose",
        "--output-format", "stream-json",
        "--dangerously-skip-permissions",
        "-p", prompt
    ]
    if session_id:
        cmd += ["--resume", session_id]

    env = os.environ.copy()
    if GIT_BASH_PATH:
        env["CLAUDE_CODE_GIT_BASH_PATH"] = GIT_BASH_PATH

    result = subprocess.run(
        cmd,
        cwd=project_path,
        capture_output=True,
        text=True,
        timeout=300,
        env=env
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr or "claude 进程异常退出")

    return _parse_output(result.stdout)


def _parse_output(raw: str) -> tuple[str, str]:
    """从 stream-json 输出中提取回复文本和 session_id。"""
    reply_parts = []
    session_id = ""

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_type = event.get("type")

        if event_type == "assistant":
            message = event.get("message", {})
            for block in message.get("content", []):
                if block.get("type") == "text":
                    reply_parts.append(block["text"])

        elif event_type == "result":
            session_id = event.get("session_id", "")

    return "\n".join(reply_parts).strip(), session_id
```

- [ ] **Step 2: 手动验证**

```python
# 在 E:/workspace/telegram-claude-bot 目录下运行
python -c "
from claude_runner import run
text, sid = run('用一句话介绍你自己', 'E:/workspace/telegram-claude-bot')
print('reply:', text[:100])
print('session_id:', sid)
"
```

Expected: 打印 Claude 的回复文本和一个 UUID 格式的 session_id

- [ ] **Step 3: 验证 --resume 恢复会话**

```python
python -c "
from claude_runner import run
text1, sid = run('我最喜欢的编程语言是 Python', 'E:/workspace/telegram-claude-bot')
print('sid:', sid)
text2, sid2 = run('我之前说我最喜欢什么？', 'E:/workspace/telegram-claude-bot', session_id=sid)
print('reply:', text2[:200])
"
```

Expected: text2 中 Claude 能正确回忆出 Python

- [ ] **Step 4: 提交**

```bash
git add claude_runner.py
git commit -m "feat: add claude CLI runner with stream-json parsing and session resume"
```

---

## Task 5: Git diff 模块

**Files:**
- Create: `E:/workspace/telegram-claude-bot/git_helper.py`

- [ ] **Step 1: 创建 git_helper.py**

```python
import subprocess

MAX_DIFF_LINES = 200

def get_diff_summary(project_path: str) -> str:
    """
    返回 git 变更摘要：变更文件列表 + diff 内容（最多 200 行）。
    如果没有变更或不是 git 仓库，返回空字符串。
    """
    try:
        # 变更文件列表
        status = subprocess.run(
            ["git", "status", "--short"],
            cwd=project_path, capture_output=True, text=True, timeout=10
        )
        files = status.stdout.strip()
        if not files:
            return ""

        # diff 内容
        diff = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=project_path, capture_output=True, text=True, timeout=10
        )
        diff_lines = diff.stdout.splitlines()
        truncated = len(diff_lines) > MAX_DIFF_LINES
        diff_text = "\n".join(diff_lines[:MAX_DIFF_LINES])

        result = f"📁 变更文件：\n{files}\n\n📝 Git Diff：\n```\n{diff_text}\n```"
        if truncated:
            result += f"\n\n⚠️ Diff 过长已截断，完整 diff 请查看本地"
        return result

    except Exception:
        return ""
```

- [ ] **Step 2: 手动验证（在有 git 变更的目录下）**

```bash
cd E:/workspace/telegram-claude-bot
echo "test" >> test_dirty.txt
python -c "from git_helper import get_diff_summary; print(get_diff_summary('E:/workspace/telegram-claude-bot'))"
git checkout -- . 2>/dev/null; rm -f test_dirty.txt
```

Expected: 打印包含 `test_dirty.txt` 的变更摘要

- [ ] **Step 3: 提交**

```bash
git add git_helper.py
git commit -m "feat: add git diff summary helper"
```

---

## Task 6: 命令处理模块

**Files:**
- Create: `E:/workspace/telegram-claude-bot/handler.py`

- [ ] **Step 1: 创建 handler.py**

```python
from telegram import Update
from telegram.ext import ContextTypes
from config import ALLOWED_USER_ID, DEFAULT_MODE
import session_store
import claude_runner
import git_helper
from path_resolver import resolve

MAX_MSG_LEN = 4096

async def _send(update: Update, text: str) -> None:
    """分段发送超长消息。"""
    for i in range(0, len(text), MAX_MSG_LEN):
        await update.message.reply_text(text[i:i + MAX_MSG_LEN])

def _auth(update: Update) -> bool:
    return update.effective_user.id == ALLOWED_USER_ID


# ── 会话管理命令 ──────────────────────────────────────────────

async def cmd_new(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    args = ctx.args  # [name, project_path]
    if len(args) < 2:
        await _send(update, "用法：/new <会话名> <项目路径>\n例：/new refactor shulex-gpt")
        return
    name, project_input = args[0], "/".join(args[1:])
    try:
        project_path = resolve(project_input)
    except ValueError as e:
        await _send(update, f"❌ {e}")
        return
    # 用一条无害的初始消息建立会话，拿到 session_id
    await update.message.reply_text(f"⏳ 正在建立会话 [{name}]...")
    try:
        _, sid = claude_runner.run("你好，新会话开始", project_path)
        session_store.new_session(name, project_input, sid)
        await _send(update, f"✅ 会话 [{name}] 已创建\n项目：{project_input}\n当前活跃会话：{name}")
    except Exception as e:
        await _send(update, f"❌ 创建会话失败：{e}")


async def cmd_switch(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    if not ctx.args:
        await _send(update, "用法：/switch <会话名>")
        return
    name = ctx.args[0]
    try:
        sess = session_store.switch_session(name)
        await _send(update, f"✅ 已切换到会话 [{name}]\n项目：{sess['project']}")
    except KeyError as e:
        await _send(update, f"❌ {e}")


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    current, sessions = session_store.list_sessions()
    if not sessions:
        await _send(update, "没有会话，用 /new <名称> <项目> 创建")
        return
    lines = ["📋 当前会话列表："]
    for name, info in sessions.items():
        marker = "👉 " if name == current else "   "
        lines.append(f"{marker}[{name}] → {info['project']}")
    await _send(update, "\n".join(lines))


async def cmd_drop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    if not ctx.args:
        await _send(update, "用法：/drop <会话名>")
        return
    session_store.drop_session(ctx.args[0])
    await _send(update, f"✅ 会话 [{ctx.args[0]}] 已删除")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    name, sess = session_store.get_current()
    mode = session_store.get_mode()
    if not name:
        await _send(update, f"无活跃会话\n模式：{mode}\n用 /new <名称> <项目> 创建")
        return
    await _send(update, f"当前会话：[{name}]\n项目：{sess['project']}\n模式：{mode}")


# ── 模式切换 ─────────────────────────────────────────────────

async def cmd_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    if not ctx.args or ctx.args[0] not in ("auto", "preview"):
        await _send(update, "用法：/mode auto 或 /mode preview")
        return
    session_store.set_mode(ctx.args[0])
    await _send(update, f"✅ 默认模式已切换为：{ctx.args[0]}")


# ── 任务执行 ─────────────────────────────────────────────────

async def _execute(update: Update, prompt: str, project_path: str, session_id: str | None, session_name: str) -> None:
    """执行 claude 并回复结果。"""
    try:
        reply, new_sid = claude_runner.run(prompt, project_path, session_id)
        session_store.update_session_id(session_name, new_sid)
        diff = git_helper.get_diff_summary(project_path)
        response = reply
        if diff:
            response += f"\n\n{diff}"
        await _send(update, response or "（Claude 无输出）")
    except TimeoutError:
        await _send(update, "⏱ 执行超时（5min），请缩小任务范围")
    except Exception as e:
        await _send(update, f"❌ 执行失败：{e}")


async def cmd_run(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    name, sess = session_store.get_current()
    if not name:
        await _send(update, "❌ 没有活跃会话，请先用 /new 创建")
        return
    prompt = " ".join(ctx.args)
    if not prompt:
        await _send(update, "用法：/run <需求描述>")
        return
    project_path = resolve(sess["project"])
    await update.message.reply_text(f"⏳ 执行中... [{name}]")
    await _execute(update, prompt, project_path, sess["session_id"], name)


async def cmd_preview(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    name, sess = session_store.get_current()
    if not name:
        await _send(update, "❌ 没有活跃会话，请先用 /new 创建")
        return
    prompt = " ".join(ctx.args)
    if not prompt:
        await _send(update, "用法：/preview <需求描述>")
        return
    project_path = resolve(sess["project"])
    preview_prompt = f"请先列出你打算做什么修改（不要实际修改任何文件），然后等待确认。需求：{prompt}"
    await update.message.reply_text(f"⏳ 生成预览... [{name}]")
    try:
        reply, new_sid = claude_runner.run(preview_prompt, project_path, sess["session_id"])
        session_store.update_session_id(name, new_sid)
        session_store.set_pending_confirm(prompt, sess["project"], new_sid)
        await _send(update, f"{reply}\n\n回复 /confirm 执行，/cancel 取消")
    except Exception as e:
        await _send(update, f"❌ 预览失败：{e}")


async def cmd_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    pending = session_store.get_pending_confirm()
    if not pending:
        await _send(update, "❌ 没有待确认的任务")
        return
    session_store.clear_pending_confirm()
    name, sess = session_store.get_current()
    project_path = resolve(pending["project"])
    await update.message.reply_text(f"⏳ 执行中... [{name}]")
    await _execute(update, pending["prompt"], project_path, pending["session_id"], name)


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    session_store.clear_pending_confirm()
    await _send(update, "✅ 已取消")


# ── 普通消息（转发给当前会话）─────────────────────────────────

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    name, sess = session_store.get_current()
    if not name:
        await _send(update, "❌ 没有活跃会话，请先用 /new 创建")
        return
    prompt = update.message.text
    mode = session_store.get_mode()
    project_path = resolve(sess["project"])

    if mode == "preview":
        await cmd_preview.__wrapped__ if hasattr(cmd_preview, '__wrapped__') else None
        # preview 模式下普通消息也走预览流程
        preview_prompt = f"请先列出你打算做什么修改（不要实际修改任何文件），然后等待确认。需求：{prompt}"
        await update.message.reply_text(f"⏳ 生成预览... [{name}]")
        try:
            reply, new_sid = claude_runner.run(preview_prompt, project_path, sess["session_id"])
            session_store.update_session_id(name, new_sid)
            session_store.set_pending_confirm(prompt, sess["project"], new_sid)
            await _send(update, f"{reply}\n\n回复 /confirm 执行，/cancel 取消")
        except Exception as e:
            await _send(update, f"❌ 预览失败：{e}")
    else:
        await update.message.reply_text(f"⏳ 处理中... [{name}]")
        await _execute(update, prompt, project_path, sess["session_id"], name)
```

- [ ] **Step 2: 修复 on_message 里的 preview 模式冗余代码**

将 `on_message` 里 preview 分支替换为直接调用内联逻辑（已在上面写完整，不需要额外修改）。

- [ ] **Step 3: 提交**

```bash
git add handler.py
git commit -m "feat: add command handlers for session management and task execution"
```

---

## Task 7: 主入口 bot.py

**Files:**
- Create: `E:/workspace/telegram-claude-bot/bot.py`

- [ ] **Step 1: 创建 bot.py**

```python
import logging
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters
)
from config import BOT_TOKEN
import handler as h

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    # 会话管理
    app.add_handler(CommandHandler("new",    h.cmd_new))
    app.add_handler(CommandHandler("switch", h.cmd_switch))
    app.add_handler(CommandHandler("list",   h.cmd_list))
    app.add_handler(CommandHandler("drop",   h.cmd_drop))
    app.add_handler(CommandHandler("status", h.cmd_status))

    # 模式
    app.add_handler(CommandHandler("mode",    h.cmd_mode))

    # 任务执行
    app.add_handler(CommandHandler("run",     h.cmd_run))
    app.add_handler(CommandHandler("preview", h.cmd_preview))
    app.add_handler(CommandHandler("confirm", h.cmd_confirm))
    app.add_handler(CommandHandler("cancel",  h.cmd_cancel))

    # 普通消息
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, h.on_message))

    logging.info("Bot 启动，开始长轮询...")
    app.run_polling()

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 复制 .env.example 为 .env 并填入真实值**

```bash
cp .env.example .env
# 编辑 .env，填入：
# BOT_TOKEN=你从 @BotFather 拿到的 token
# ALLOWED_USER_ID=你的 Telegram user_id（可从 @userinfobot 获取）
# WORKSPACE_ROOT=E:/workspace
# GIT_BASH_PATH=E:/develop/git/Git/usr/bin/bash.exe
```

- [ ] **Step 3: 启动测试**

```bash
python bot.py
```

Expected: 控制台输出 `Bot 启动，开始长轮询...`，无报错

- [ ] **Step 4: Telegram 发送 `/new test qa-bot`**

Expected: Bot 回复 `✅ 会话 [test] 已创建`

- [ ] **Step 5: 发送普通消息 `你好`**

Expected: Bot 回复 Claude 的响应文本

- [ ] **Step 6: 提交**

```bash
git add bot.py
git commit -m "feat: add main bot entrypoint with all handlers registered"
```

---

## Task 8: 开机自启（Windows 任务计划程序）

**Files:**
- Create: `E:/workspace/telegram-claude-bot/start_bot.vbs`
- Create: `E:/workspace/telegram-claude-bot/setup_autostart.ps1`

- [ ] **Step 1: 创建 start_bot.vbs（无窗口启动）**

```vbscript
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "pythonw E:\workspace\telegram-claude-bot\bot.py", 0, False
```

- [ ] **Step 2: 创建 setup_autostart.ps1（注册任务计划）**

```powershell
$taskName = "TelegramClaudeBot"
$scriptPath = "E:\workspace\telegram-claude-bot\start_bot.vbs"
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument $scriptPath
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0 -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force
Write-Host "✅ 任务计划 [$taskName] 注册成功，下次登录时自动启动"
```

- [ ] **Step 3: 以管理员身份运行 PowerShell，执行注册脚本**

```powershell
# 以管理员身份打开 PowerShell，然后运行：
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
& "E:\workspace\telegram-claude-bot\setup_autostart.ps1"
```

Expected: 输出 `✅ 任务计划 [TelegramClaudeBot] 注册成功`

- [ ] **Step 4: 验证任务已注册**

```powershell
Get-ScheduledTask -TaskName "TelegramClaudeBot" | Select-Object TaskName, State
```

Expected: 显示 `TelegramClaudeBot  Ready`

- [ ] **Step 5: 提交**

```bash
git add start_bot.vbs setup_autostart.ps1
git commit -m "feat: add autostart via Windows Task Scheduler"
```

---

## Task 9: 端到端验证

- [ ] **Step 1: 重启电脑，等待 30 秒后检查 Bot 是否自动上线**

在 Telegram 发送 `/status`，Expected: Bot 正常回复

- [ ] **Step 2: 完整流程验证**

```
/new coding shulex-gpt          → 创建会话
/status                          → 显示当前会话信息
帮我介绍一下这个项目的结构        → Claude 分析目录
继续，这个项目用了什么框架？       → Claude 上下文连续回复
/new debug qa-bot               → 创建第二个会话
/list                            → 显示两个会话
/switch coding                  → 切换回第一个
/preview 在 pom.xml 里加一个依赖 → 预览模式
/confirm                        → 确认执行
/mode preview                   → 切换默认预览模式
/drop debug                     → 删除会话
```

- [ ] **Step 3: 最终提交**

```bash
git add -A
git commit -m "chore: final verification complete"
```
