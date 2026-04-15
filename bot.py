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
