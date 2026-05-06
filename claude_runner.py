import subprocess
import asyncio
import json
import os
from typing import AsyncIterator, Callable, Optional
from config import GIT_BASH_PATH


def _build_cmd_env(prompt: str, session_id: str | None) -> tuple[list[str], dict]:
    """构造 claude CLI 命令行和环境变量。Windows 下用 claude.cmd。"""
    claude_exe = "claude.cmd" if os.name == "nt" else "claude"
    cmd = [
        claude_exe, "--print", "--verbose",
        "--output-format", "stream-json",
        "--dangerously-skip-permissions",
        "-p", prompt,
    ]
    if session_id:
        cmd += ["--resume", session_id]

    env = os.environ.copy()
    if GIT_BASH_PATH:
        # Windows 路径必须反斜杠，否则 claude 找不到 bash
        env["CLAUDE_CODE_GIT_BASH_PATH"] = GIT_BASH_PATH.replace("/", os.sep)
    return cmd, env


async def run_async(
    prompt: str,
    project_path: str,
    session_id: str | None = None,
    on_proc_started: Optional[Callable[[asyncio.subprocess.Process], None]] = None,
) -> AsyncIterator[dict]:
    """
    异步流式调用 claude CLI，逐事件 yield。

    on_proc_started：子进程创建后立即回调，用于外部持有 proc 以便 kill。

    事件结构:
      {"kind": "tool_use", "name": str, "input_preview": str}
      {"kind": "text", "text": str}
      {"kind": "result", "session_id": str, "reply": str}
      {"kind": "error", "message": str}
      {"kind": "done", "returncode": int}
    """
    cmd, env = _build_cmd_env(prompt, session_id)

    # Windows 下 claude.cmd 是批处理，必须走 shell 解析 PATH。
    # asyncio 在 Windows 要求 ProactorEventLoop（3.8+ 默认）。
    if os.name == "nt":
        cmdline = subprocess.list2cmdline(cmd)
        proc = await asyncio.create_subprocess_shell(
            cmdline,
            cwd=project_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    else:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=project_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

    if on_proc_started is not None:
        try:
            on_proc_started(proc)
        except Exception:
            pass

    reply_parts: list[str] = []
    final_session_id = ""

    assert proc.stdout is not None
    try:
        async for raw_line in proc.stdout:
            try:
                line = raw_line.decode("utf-8", errors="replace").strip()
            except Exception:
                continue
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = event.get("type")
            if etype == "assistant":
                message = event.get("message", {})
                for block in message.get("content", []):
                    btype = block.get("type")
                    if btype == "text":
                        text = block.get("text", "")
                        if text:
                            reply_parts.append(text)
                            yield {"kind": "text", "text": text}
                    elif btype == "tool_use":
                        name = block.get("name", "?")
                        inp = block.get("input", {}) or {}
                        preview = _tool_input_preview(name, inp)
                        yield {"kind": "tool_use", "name": name, "input_preview": preview}
            elif etype == "result":
                final_session_id = event.get("session_id", "")
    finally:
        # 如果生成器被 aclose / 外部 cancel，这里要杀掉子进程，避免孤儿
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            except Exception:
                pass
        returncode = await proc.wait()
        if returncode != 0:
            stderr_bytes = b""
            if proc.stderr is not None:
                try:
                    stderr_bytes = await proc.stderr.read()
                except Exception:
                    pass
            stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
            yield {"kind": "error", "message": stderr_text or f"claude 进程退出码 {returncode}"}

        yield {
            "kind": "result",
            "session_id": final_session_id,
            "reply": "\n".join(reply_parts).strip(),
        }
        yield {"kind": "done", "returncode": returncode}


def _tool_input_preview(name: str, inp: dict) -> str:
    """给不同工具提取有用的参数预览。"""
    if name in ("Read", "Write", "Edit", "NotebookEdit"):
        p = inp.get("file_path") or inp.get("notebook_path") or ""
        return os.path.basename(p) if p else ""
    if name == "Bash":
        cmd = inp.get("command", "")
        return (cmd[:60] + "…") if len(cmd) > 60 else cmd
    if name in ("Grep", "Glob"):
        return inp.get("pattern", "")[:60]
    if name == "WebFetch":
        return inp.get("url", "")[:60]
    if name == "WebSearch":
        return inp.get("query", "")[:60]
    if name == "Agent":
        return inp.get("description", "")[:60]
    # 兜底：第一个字符串参数
    for v in inp.values():
        if isinstance(v, str):
            return v[:60]
    return ""
