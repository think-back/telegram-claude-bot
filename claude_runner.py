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
    # Windows 下需要使用 claude.cmd，否则 FileNotFoundError
    claude_exe = "claude.cmd" if os.name == "nt" else "claude"
    cmd = [
        claude_exe, "--print", "--verbose",
        "--output-format", "stream-json",
        "--dangerously-skip-permissions",
        "-p", prompt
    ]
    if session_id:
        cmd += ["--resume", session_id]

    env = os.environ.copy()
    if GIT_BASH_PATH:
        # Windows 路径需要使用反斜杠，否则 claude 报找不到文件
        env["CLAUDE_CODE_GIT_BASH_PATH"] = GIT_BASH_PATH.replace("/", os.sep)

    result = subprocess.run(
        cmd,
        cwd=project_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
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
