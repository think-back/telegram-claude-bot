# Telegram Claude Bot

> [简体中文](./README.md) · [繁體中文](./README.zh-TW.md) · [English](./README.en.md) · [日本語](./README.ja.md) · [한국어](./README.ko.md)

為 [Claude Code](https://claude.com/claude-code) CLI 套上一層 Telegram 介面——在手機上發一條指令，就能讓本地工作站上的 Claude 執行長任務、改程式碼、提交 commit。

## 特性

- **多會話並行**：一個會話對應一個專案目錄，會話之間任務互不阻塞
- **背景執行 + 進度推送**：長任務（預設 1 小時硬上限）丟到背景跑，前 5 分鐘每 4 秒刷新進度，之後每 2 分鐘刷新一次，完成後主動推送結果
- **預覽模式**：`/preview` 讓 Claude 先列出計畫，再 `/confirm` 實際修改
- **任務管理**：`/tasks` 查看所有並行任務、`/kill` 即時終止子行程
- **白名單驗證**：僅接受指定 Telegram User ID 的請求
- **路徑自動補全**：`shulex/` 子目錄可省略前綴（專案特化，可自行調整）
- **崩潰回復**：sessions.json 持久化，bot 重啟時清理過期標記並主動通知使用者

## 指令

```
/help               顯示完整說明
/new <名稱> <專案>  建立新會話，例：/new refactor shulex-gpt
/switch <名稱>      切換會話
/list               列出全部會話
/drop <名稱>        刪除會話（執行中無法刪除）
/status             目前會話狀態
/tasks              全部任務執行狀態
/kill [名稱]        終止當前（或指定）會話的任務
/run <需求>         直接執行
/preview <需求>     預覽模式：先列計畫
/confirm            確認執行預覽過的任務
/cancel             取消預覽
/mode auto|preview  預設模式（直接傳純文字依此模式執行）
```

直接傳純文字訊息會依當前模式觸發 `/run` 或 `/preview`。

## 安裝

### 1. 前置需求

- Python **3.10+**
- [Claude Code CLI](https://claude.com/claude-code) 已安裝並登入
- Windows 使用者需 Git Bash（Claude CLI 相依）

### 2. 安裝相依套件

```bash
git clone <您的儲存庫 URL>
cd telegram-claude-bot
pip install -r requirements.txt
```

### 3. 設定 `.env`

```bash
cp .env.example .env
```

編輯 `.env`：

```ini
BOT_TOKEN=向 @BotFather 申請的 token
ALLOWED_USER_ID=您的 Telegram User ID（用 @userinfobot 查詢）
WORKSPACE_ROOT=E:/workspace
GIT_BASH_PATH=E:/develop/git/Git/usr/bin/bash.exe   # Windows 必填
```

### 4. 啟動

```bash
python bot.py
```

#### Windows 自動啟動（選用）

以系統管理員身分執行 `setup_autostart.ps1`，會註冊至工作排程器，開機自動啟動；或使用 `start_bot.vbs` 進行靜默啟動。

## 專案結構

```
bot.py             主進入點，註冊指令處理器
handler.py         指令業務邏輯
task_manager.py    背景任務排程 + 進度節流
claude_runner.py   非同步串流呼叫 claude CLI（解析 stream-json）
session_store.py   sessions.json 持久化
path_resolver.py   專案路徑解析（含 shulex 子目錄快取）
git_helper.py      git diff 摘要
text_utils.py      長訊息依段落/行切分
config.py          .env 載入
```

## 運作原理

1. Telegram 收到指令 → `handler.py` 驗證白名單
2. 指令派發至 `task_manager.start()`，背景 asyncio 任務驅動 `claude_runner.run_async()`
3. `claude_runner` 以 `--output-format stream-json` 啟動 `claude.cmd`，解析事件流（`tool_use` / `text` / `result`）
4. `task_manager` 節流呼叫 `edit_message_text` 刷新進度訊息
5. 任務完成時將進度訊息編輯為 header，再附上 `git diff` 摘要傳送完整結果

## 注意事項

- 單一會話同時只能執行一個任務，需要並行請使用多會話
- 任務硬上限 1 小時（`HARD_LIMIT_SEC`），逾時強制終止子行程
- 同一會話多次 `/run` 自動延續 Claude 對話上下文（`--resume <session_id>`）
- `bot.log` 已列入 `.gitignore`，請勿 commit

## License

MIT
