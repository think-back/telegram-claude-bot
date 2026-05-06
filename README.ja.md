# Telegram Claude Bot

> [简体中文](./README.md) · [繁體中文](./README.zh-TW.md) · [English](./README.en.md) · [日本語](./README.ja.md) · [한국어](./README.ko.md)

[Claude Code](https://claude.com/claude-code) CLI を Telegram でラップする bot です。スマートフォンからチャットでコマンドを送るだけで、ローカルワークステーション上の Claude に長時間タスクの実行・コード修正・コミット作成までさせることができます。

## 特徴

- **複数セッション並列**：1 セッション = 1 プロジェクトディレクトリ。セッション間のタスクは互いにブロックしません
- **バックグラウンド実行 + 進捗通知**：長時間タスク（デフォルト 1 時間ハードリミット）はバックグラウンドで実行。最初の 5 分間は 4 秒ごと、それ以降は 2 分ごとに進捗メッセージを更新し、完了時には結果を能動的にプッシュします
- **プレビューモード**：`/preview` で Claude にまず計画を提示させ、`/confirm` で実際に実行
- **タスク管理**：`/tasks` で全並列タスクを確認、`/kill` でサブプロセスを即座に終了
- **ホワイトリスト認証**：指定した Telegram User ID のみ受け付け
- **パス自動補完**：`shulex/` 配下のサブディレクトリはプレフィックス省略可（プロジェクト固有、変更可）
- **クラッシュ回復**：sessions.json に永続化。bot 再起動時に stale な running フラグを掃除し、ユーザーに通知します

## コマンド

```
/help               ヘルプを表示
/new <名前> <PJ>    新しいセッションを作成（例：/new refactor shulex-gpt）
/switch <名前>      セッションを切り替え
/list               全セッションを一覧
/drop <名前>        セッションを削除（実行中のものは削除不可）
/status             現在のセッションの状態
/tasks              全タスクの実行状態
/kill [名前]        現在（または指定）セッションのタスクを終了
/run <要件>         直接実行
/preview <要件>     プレビューモード：先に計画を提示
/confirm            プレビュー済みタスクを実行
/cancel             プレビューをキャンセル
/mode auto|preview  デフォルトモードを設定（プレーンテキストはこのモードで動作）
```

プレーンテキストを送ると、現在のモードに応じて `/run` または `/preview` が発火します。

## インストール

### 1. 前提条件

- Python **3.10+**
- [Claude Code CLI](https://claude.com/claude-code) がインストール済みかつログイン済み
- Windows の場合は Git Bash（Claude CLI の依存）

### 2. 依存パッケージのインストール

```bash
git clone <あなたのリポジトリ URL>
cd telegram-claude-bot
pip install -r requirements.txt
```

### 3. `.env` の設定

```bash
cp .env.example .env
```

`.env` を編集：

```ini
BOT_TOKEN=@BotFather から取得した token
ALLOWED_USER_ID=自分の Telegram User ID（@userinfobot で確認）
WORKSPACE_ROOT=E:/workspace
GIT_BASH_PATH=E:/develop/git/Git/usr/bin/bash.exe   # Windows では必須
```

### 4. 起動

```bash
python bot.py
```

#### Windows 自動起動（任意）

管理者権限で `setup_autostart.ps1` を実行すると、タスクスケジューラに登録され OS 起動時に自動起動します。`start_bot.vbs` でサイレント起動も可能です。

## プロジェクト構成

```
bot.py             エントリポイント。コマンドハンドラを登録
handler.py         コマンドのビジネスロジック
task_manager.py    バックグラウンドタスクのスケジューリングと進捗スロットリング
claude_runner.py   claude CLI の非同期ストリーミングラッパ（stream-json 解析）
session_store.py   sessions.json への永続化
path_resolver.py   プロジェクトパス解決（shulex サブディレクトリのキャッシュ付き）
git_helper.py      git diff サマリ
text_utils.py      長文メッセージを段落／行境界で分割
config.py          .env ローダ
```

## 動作原理

1. Telegram でコマンドを受信 → `handler.py` がホワイトリスト検証
2. コマンドが `task_manager.start()` にディスパッチされ、バックグラウンドの asyncio タスクが `claude_runner.run_async()` を駆動
3. `claude_runner` が `--output-format stream-json` で `claude.cmd` を起動し、イベントストリーム（`tool_use` / `text` / `result`）をパース
4. `task_manager` が `edit_message_text` 呼び出しをスロットリングし、進捗メッセージを更新
5. 完了時は進捗メッセージをヘッダに書き換え、別メッセージで完全な返答と `git diff` サマリを送信

## 注意事項

- 1 つのセッションで同時に実行できるタスクは 1 つのみ。並列実行が必要な場合は複数セッションを使用してください
- ハードリミットは 1 時間（`HARD_LIMIT_SEC`）。到達時はサブプロセスを強制終了します
- 同一セッション内で連続して `/run` を呼ぶと Claude のコンテキストが自動的に継続されます（`--resume <session_id>`）
- `bot.log` は `.gitignore` に含まれています — commit しないでください

## License

MIT
