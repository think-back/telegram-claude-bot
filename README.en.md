# Telegram Claude Bot

> [简体中文](./README.md) · [繁體中文](./README.zh-TW.md) · [English](./README.en.md) · [日本語](./README.ja.md) · [한국어](./README.ko.md)

A Telegram interface wrapping the [Claude Code](https://claude.com/claude-code) CLI — drive long-running coding tasks on your local workstation from your phone: edit files, run commands, and produce commits, all from a chat window.

## Features

- **Parallel sessions** — one session per project directory; tasks across sessions don't block each other
- **Background execution with progress push** — long tasks (1-hour hard cap by default) run in the background; progress message refreshes every 4 seconds for the first 5 minutes, then every 2 minutes. Final result is pushed when done
- **Preview mode** — `/preview` makes Claude outline its plan first; `/confirm` then executes it
- **Task management** — `/tasks` shows all parallel runs, `/kill` terminates the child process immediately
- **Whitelist auth** — only the configured Telegram User ID is accepted
- **Path auto-prefix** — `shulex/` subdirectories can be referenced without the prefix (project-specific, easy to change)
- **Crash recovery** — sessions.json persists state; on restart the bot clears stale running flags and notifies the user

## Commands

```
/help               Show full help
/new <name> <proj>  Create a new session, e.g. /new refactor shulex-gpt
/switch <name>      Switch active session
/list               List all sessions
/drop <name>        Delete a session (running ones can't be deleted)
/status             Current session status
/tasks              All running tasks
/kill [name]        Kill the current (or named) session's task
/run <prompt>       Execute directly
/preview <prompt>   Preview mode: list the plan first
/confirm            Execute the previously previewed task
/cancel             Cancel the preview
/mode auto|preview  Set default mode (plain text follows this mode)
```

A plain text message triggers `/run` or `/preview` based on the current mode.

## Installation

### 1. Prerequisites

- Python **3.10+**
- [Claude Code CLI](https://claude.com/claude-code) installed and logged in
- Git Bash on Windows (required by Claude CLI)

### 2. Install dependencies

```bash
git clone <your repo URL>
cd telegram-claude-bot
pip install -r requirements.txt
```

### 3. Configure `.env`

```bash
cp .env.example .env
```

Edit `.env`:

```ini
BOT_TOKEN=token from @BotFather
ALLOWED_USER_ID=your Telegram User ID (find via @userinfobot)
WORKSPACE_ROOT=E:/workspace
GIT_BASH_PATH=E:/develop/git/Git/usr/bin/bash.exe   # required on Windows
```

### 4. Run

```bash
python bot.py
```

#### Windows autostart (optional)

Run `setup_autostart.ps1` as Administrator to register it with Task Scheduler, or use `start_bot.vbs` for silent startup.

## Project layout

```
bot.py             Entrypoint; registers command handlers
handler.py         Command business logic
task_manager.py    Background task scheduling + progress throttling
claude_runner.py   Async streaming wrapper around claude CLI (stream-json parsing)
session_store.py   sessions.json persistence
path_resolver.py   Project path resolution (with shulex subdir cache)
git_helper.py      git diff summary
text_utils.py      Long-message splitting on paragraph/line boundaries
config.py          .env loader
```

## How it works

1. Telegram receives a command → `handler.py` validates the whitelist
2. Command is dispatched to `task_manager.start()`, which spawns a background asyncio task driving `claude_runner.run_async()`
3. `claude_runner` launches `claude.cmd` with `--output-format stream-json` and parses the event stream (`tool_use` / `text` / `result`)
4. `task_manager` throttles `edit_message_text` calls to refresh the progress message
5. On completion, the progress message is rewritten to the result header, and a separate message is sent containing the full reply plus a `git diff` summary

## Notes

- A single session can only run one task at a time; use multiple sessions for parallelism
- Hard cap is 1 hour (`HARD_LIMIT_SEC`); the child process is killed when reached
- Successive `/run` calls in the same session automatically resume Claude context (`--resume <session_id>`)
- `bot.log` is in `.gitignore` — never commit it

## License

MIT
