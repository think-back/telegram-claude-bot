import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
ALLOWED_USER_ID = int(os.environ["ALLOWED_USER_ID"])
WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", "E:/workspace")
GIT_BASH_PATH = os.environ.get("GIT_BASH_PATH", "")
