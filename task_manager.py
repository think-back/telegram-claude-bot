"""
后台任务管理：fire-and-forget 地跑 claude，节流编辑进度消息，完成时主动推送。

模型：
- 一个 session 最多一个正在跑的 BackgroundTask
- 多任务并行 = 多 session 并行
"""
import asyncio
import time
import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional

from telegram import Bot
from telegram.error import BadRequest, RetryAfter, TimedOut

import claude_runner
import session_store
import git_helper
from path_resolver import resolve
from text_utils import split_chunks

log = logging.getLogger(__name__)

MAX_MSG_LEN = 4096

# 进度节流：前 FAST_WINDOW 秒每 FAST_INTERVAL 刷一次，之后降频
FAST_WINDOW_SEC = 300           # 前 5 min
FAST_INTERVAL_SEC = 4
SLOW_INTERVAL_SEC = 120         # 之后每 2 min
HARD_LIMIT_SEC = 3600           # 1h 兜底


@dataclass
class _TaskState:
    session_name: str
    task_id: str
    chat_id: int
    progress_msg_id: int
    started_at: float
    prompt: str
    tool_count: int = 0
    last_tool: str = ""
    last_edit_ts: float = 0.0
    last_edit_text: str = ""
    asyncio_task: Optional[asyncio.Task] = field(default=None, repr=False)
    proc: Optional[asyncio.subprocess.Process] = field(default=None, repr=False)
    killed: bool = False


# 内存态：session_name -> _TaskState（sessions.json 里也有持久化标记，两者互补）
_running: dict[str, _TaskState] = {}


def is_running(session_name: str) -> bool:
    return session_name in _running


def list_running_names() -> list[str]:
    return list(_running.keys())


def get_state(session_name: str) -> Optional[_TaskState]:
    return _running.get(session_name)


def kill(session_name: str) -> bool:
    """
    终止指定 session 的任务：先 kill 子进程（真停），再 cancel asyncio task。
    返回 True 表示有任务被杀，False 表示本来就没在跑。
    """
    st = _running.get(session_name)
    if not st:
        return False
    st.killed = True
    if st.proc is not None and st.proc.returncode is None:
        try:
            st.proc.kill()
        except ProcessLookupError:
            pass
        except Exception:
            log.exception("kill proc 失败 [%s]", session_name)
    if st.asyncio_task is not None and not st.asyncio_task.done():
        st.asyncio_task.cancel()
    return True


async def start(
    bot: Bot,
    session_name: str,
    prompt: str,
    project_input: str,
    session_id: Optional[str],
    chat_id: int,
    initial_msg_id: int,
    on_finish_update_sid: bool = True,
) -> None:
    """
    启动后台任务。调用方应已确认该 session 当前没在跑。
    initial_msg_id：前面用 reply_text 发的"⏳ 执行中..."消息 id，用于 edit。
    """
    task_id = f"t-{int(time.time())}-{uuid.uuid4().hex[:6]}"
    state = _TaskState(
        session_name=session_name,
        task_id=task_id,
        chat_id=chat_id,
        progress_msg_id=initial_msg_id,
        started_at=time.time(),
        prompt=prompt,
    )
    _running[session_name] = state

    session_store.set_running(session_name, {
        "task_id": task_id,
        "started_at": state.started_at,
        "chat_id": chat_id,
        "message_id": initial_msg_id,
        "prompt": prompt,
    })

    state.asyncio_task = asyncio.create_task(
        _run_task(bot, state, project_input, session_id, on_finish_update_sid),
        name=f"bgtask:{session_name}:{task_id}",
    )


async def _run_task(
    bot: Bot,
    state: _TaskState,
    project_input: str,
    session_id: Optional[str],
    on_finish_update_sid: bool,
) -> None:
    name = state.session_name
    project_path = resolve(project_input)

    final_reply = ""
    final_sid = ""
    error_msg = ""
    returncode = 0
    hit_hard_limit = False

    def _capture_proc(p):
        state.proc = p

    try:
        agen = claude_runner.run_async(
            prompt=state.prompt,
            project_path=project_path,
            session_id=session_id,
            on_proc_started=_capture_proc,
        ).__aiter__()

        while True:
            remaining = HARD_LIMIT_SEC - (time.time() - state.started_at)
            if remaining <= 0:
                hit_hard_limit = True
                break
            try:
                event = await asyncio.wait_for(agen.__anext__(), timeout=remaining)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                hit_hard_limit = True
                break

            kind = event.get("kind")
            if kind == "tool_use":
                state.tool_count += 1
                tname = event.get("name", "?")
                preview = event.get("input_preview", "")
                state.last_tool = f"{tname}({preview})" if preview else tname
                await _maybe_edit_progress(bot, state)
            elif kind == "text":
                # 文字片段只做节流刷新，不把内容推到进度条（避免刷屏）
                await _maybe_edit_progress(bot, state)
            elif kind == "result":
                final_reply = event.get("reply", "")
                final_sid = event.get("session_id", "")
            elif kind == "error":
                error_msg = event.get("message", "") or error_msg
            elif kind == "done":
                returncode = event.get("returncode", 0)

    except asyncio.CancelledError:
        # 被 /kill 取消；收尾仍要执行（不要 re-raise，否则下面的通知/清理会被跳过）
        state.killed = True
    except Exception as e:
        log.exception("后台任务异常 [%s]", name)
        error_msg = str(e)

    # 更新 session 的 claude session_id
    if on_finish_update_sid and final_sid:
        try:
            session_store.update_session_id(name, final_sid)
        except Exception:
            log.exception("update_session_id 失败 [%s]", name)

    # 组装最终消息
    elapsed = time.time() - state.started_at
    try:
        diff = git_helper.get_diff_summary(project_path)
    except Exception:
        diff = ""

    if state.killed:
        header = f"🛑 [{name}] 已终止 ({_fmt_elapsed(elapsed)}, {state.tool_count} 工具)"
    elif hit_hard_limit:
        header = f"⏱ [{name}] 达到 1h 硬上限 ({_fmt_elapsed(elapsed)}, {state.tool_count} 工具)"
    elif error_msg and not final_reply:
        header = f"❌ [{name}] 失败 ({_fmt_elapsed(elapsed)}, {state.tool_count} 工具)"
    elif returncode != 0 and not final_reply:
        header = f"❌ [{name}] 退出码 {returncode} ({_fmt_elapsed(elapsed)}, {state.tool_count} 工具)"
    else:
        header = f"✅ [{name}] 完成 ({_fmt_elapsed(elapsed)}, {state.tool_count} 工具)"

    body_parts = [header]
    if final_reply:
        body_parts.append("")
        body_parts.append(final_reply)
    if error_msg:
        body_parts.append("")
        body_parts.append(f"stderr: {error_msg[:500]}")
    if diff:
        body_parts.append("")
        body_parts.append(diff)

    full = "\n".join(body_parts).strip() or "（无输出）"

    # 先把进度消息编辑成 header（简短），然后用新消息发送完整内容（按段落分段）
    await _safe_edit(bot, state.chat_id, state.progress_msg_id, header)

    for chunk in split_chunks(full, MAX_MSG_LEN):
        try:
            await bot.send_message(chat_id=state.chat_id, text=chunk)
        except Exception:
            log.exception("发送完成消息失败 [%s]", name)

    # 清理
    _running.pop(name, None)
    try:
        session_store.clear_running(name)
    except Exception:
        log.exception("clear_running 失败 [%s]", name)


async def _maybe_edit_progress(bot: Bot, state: _TaskState) -> None:
    now = time.time()
    elapsed = now - state.started_at
    interval = FAST_INTERVAL_SEC if elapsed <= FAST_WINDOW_SEC else SLOW_INTERVAL_SEC
    if now - state.last_edit_ts < interval:
        return

    text = _render_progress(state, elapsed)
    if text == state.last_edit_text:
        state.last_edit_ts = now
        return

    ok = await _safe_edit(bot, state.chat_id, state.progress_msg_id, text)
    if ok:
        state.last_edit_ts = now
        state.last_edit_text = text


def _render_progress(state: _TaskState, elapsed: float) -> str:
    lines = [
        f"⏳ [{state.session_name}] 执行中",
        f"├ ⏱ {_fmt_elapsed(elapsed)}",
        f"├ 🔧 {state.tool_count} 个工具",
    ]
    if state.last_tool:
        lines.append(f"└ {state.last_tool}")
    else:
        lines.append("└ 等待输出...")
    if elapsed > FAST_WINDOW_SEC:
        lines.append("（已进入低频刷新，完成时会主动通知）")
    return "\n".join(lines)


async def _safe_edit(bot: Bot, chat_id: int, message_id: int, text: str) -> bool:
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text[:MAX_MSG_LEN])
        return True
    except BadRequest as e:
        # 消息未变 / 消息不可编辑 —— 忽略
        if "not modified" in str(e).lower():
            return True
        log.warning("edit_message_text BadRequest: %s", e)
        return False
    except RetryAfter as e:
        log.warning("TG 限流 retry after %s", e.retry_after)
        await asyncio.sleep(float(e.retry_after) + 0.5)
        return False
    except TimedOut:
        return False
    except Exception:
        log.exception("edit_message_text 失败")
        return False


def _fmt_elapsed(sec: float) -> str:
    sec = int(sec)
    m, s = divmod(sec, 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}h{m}m{s}s"
    return f"{m}m{s}s" if m else f"{s}s"
