import os
import sys
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        sys.stderr.write(
            f"❌ 缺少环境变量 {key}，请在 .env 中配置（参考 .env.example）\n"
        )
        sys.exit(1)
    return value


BOT_TOKEN = _require("BOT_TOKEN")

try:
    ALLOWED_USER_ID = int(_require("ALLOWED_USER_ID"))
except ValueError:
    sys.stderr.write("❌ ALLOWED_USER_ID 必须是整数（你的 Telegram User ID）\n")
    sys.exit(1)

WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", "E:/workspace")
GIT_BASH_PATH = os.environ.get("GIT_BASH_PATH", "")
