import logging
import asyncio
import os
from logging.handlers import RotatingFileHandler
from telegram import BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters
)
from config import BOT_TOKEN, ALLOWED_USER_ID
import handler as h
import session_store

COMMANDS = [
    BotCommand("help",    "显示完整帮助"),
    BotCommand("new",     "新建会话  /new <名称> <项目路径>"),
    BotCommand("switch",  "切换会话  /switch <名称>"),
    BotCommand("list",    "列出所有会话"),
    BotCommand("drop",    "删除会话  /drop <名称>"),
    BotCommand("status",  "查看当前会话状态"),
    BotCommand("tasks",   "查看全部会话运行状态"),
    BotCommand("kill",    "终止当前(或指定)会话的任务"),
    BotCommand("run",     "执行任务  /run <需求描述>"),
    BotCommand("preview", "预览模式  /preview <需求描述>"),
    BotCommand("confirm", "确认预览并执行"),
    BotCommand("cancel",  "取消预览"),
    BotCommand("mode",    "切换模式  /mode auto|preview"),
]

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
    handlers=[
        RotatingFileHandler(
            "bot.log",
            maxBytes=5 * 1024 * 1024,   # 5MB 轮转
            backupCount=3,              # 保留 3 份
            encoding="utf-8",
        ),
        logging.StreamHandler(),
    ],
)
# 压住 polling 心跳噪声，否则 bot.log 几乎全是 getUpdates 200 OK
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)

def main() -> None:
    # Windows 上 asyncio 创建子进程必须用 ProactorEventLoop（Python 3.8+ 默认就是）
    if os.name == "nt":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except AttributeError:
            pass

    app = Application.builder().token(BOT_TOKEN).build()

    # 帮助
    app.add_handler(CommandHandler("help",   h.cmd_help))
    app.add_handler(CommandHandler("start",  h.cmd_help))  # /start 也给帮助

    # 会话管理
    app.add_handler(CommandHandler("new",    h.cmd_new))
    app.add_handler(CommandHandler("switch", h.cmd_switch))
    app.add_handler(CommandHandler("list",   h.cmd_list))
    app.add_handler(CommandHandler("drop",   h.cmd_drop))
    app.add_handler(CommandHandler("status", h.cmd_status))
    app.add_handler(CommandHandler("tasks",  h.cmd_tasks))
    app.add_handler(CommandHandler("kill",   h.cmd_kill))

    # 模式
    app.add_handler(CommandHandler("mode",    h.cmd_mode))

    # 任务执行
    app.add_handler(CommandHandler("run",     h.cmd_run))
    app.add_handler(CommandHandler("preview", h.cmd_preview))
    app.add_handler(CommandHandler("confirm", h.cmd_confirm))
    app.add_handler(CommandHandler("cancel",  h.cmd_cancel))

    # 普通消息
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, h.on_message))

    async def post_init(application: Application) -> None:
        await application.bot.set_my_commands(COMMANDS)
        # 清理上次未完成任务的 running 标记
        stale = session_store.clear_all_running()
        if stale:
            try:
                names = ", ".join(f"[{n}]" for n in stale)
                await application.bot.send_message(
                    chat_id=ALLOWED_USER_ID,
                    text=f"⚠ Bot 重启，上次有 {len(stale)} 个任务状态未知：{names}\n"
                         f"（Claude CLI 子进程可能已在后台结束或仍在运行，请自行确认）",
                )
            except Exception:
                logging.exception("发送重启通知失败")

    app.post_init = post_init

    logging.info("Bot 启动，开始长轮询...")
    app.run_polling()

if __name__ == "__main__":
    main()
