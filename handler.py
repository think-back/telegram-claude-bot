from telegram import Update
from telegram.ext import ContextTypes
from config import ALLOWED_USER_ID
import session_store
import claude_runner
import task_manager
from path_resolver import resolve
from text_utils import split_chunks

MAX_MSG_LEN = 4096

async def _send(update: Update, text: str) -> None:
    """分段发送超长消息（按段落 / 行边界切）。"""
    chunks = split_chunks(text, MAX_MSG_LEN)
    if not chunks:
        return
    for chunk in chunks:
        await update.message.reply_text(chunk)

def _auth(update: Update) -> bool:
    return update.effective_user.id == ALLOWED_USER_ID


def _fmt_elapsed(sec: float) -> str:
    sec = int(sec)
    m, s = divmod(sec, 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}h{m}m{s}s"
    return f"{m}m{s}s" if m else f"{s}s"


async def _reject_if_running(update: Update, name: str) -> bool:
    """若当前会话有任务在跑，发提示并返回 True。"""
    if not task_manager.is_running(name):
        return False
    import time
    info = session_store.get_running(name) or {}
    started = info.get("started_at", time.time())
    elapsed = time.time() - float(started)
    await _send(
        update,
        f"⚠ [{name}] 已有任务在跑 ({_fmt_elapsed(elapsed)})\n"
        f"可选：\n"
        f"/switch <其他会话>   切到别的会话起新任务\n"
        f"/new <名称> <项目>   新建会话\n"
        f"/tasks               查看全部运行中任务\n"
        f"/kill                终止当前会话的任务",
    )
    return True


# ── 会话管理命令 ──────────────────────────────────────────────

async def cmd_new(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    args = ctx.args
    if len(args) < 2:
        await _send(update, "用法：/new <会话名> <项目路径>\n例：/new refactor shulex-gpt")
        return
    name, project_input = args[0], "/".join(args[1:])

    # 同名覆盖保护：正在跑的不能覆盖；空闲会话需要先 /drop
    _, existing = session_store.list_sessions()
    if name in existing:
        if task_manager.is_running(name):
            await _send(update, f"❌ [{name}] 正在跑任务，先 /kill 再重建")
            return
        await _send(update, f"❌ 会话 [{name}] 已存在，先 /drop {name} 再重建")
        return

    try:
        project_path = resolve(project_input)
    except ValueError as e:
        await _send(update, f"❌ {e}")
        return
    await update.message.reply_text(f"⏳ 正在建立会话 [{name}]...")

    # 关键：不能用同步 claude_runner.run()，会阻塞整个事件循环最长 300s
    try:
        sid = ""
        async for ev in claude_runner.run_async("你好，新会话开始", project_path):
            kind = ev.get("kind")
            if kind == "result":
                sid = ev.get("session_id", "") or sid
            elif kind == "error":
                msg = ev.get("message", "")
                if msg:
                    await _send(update, f"❌ 创建会话失败：{msg[:500]}")
                    return
        if not sid:
            await _send(update, "❌ 创建会话失败：未获得 session_id")
            return
        session_store.new_session(name, project_input, sid)
        await _send(update, f"✅ 会话 [{name}] 已创建\n项目：{project_input}\n当前活跃会话：{name}")
    except Exception as e:
        await _send(update, f"❌ 创建会话失败：{e}")


async def cmd_switch(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    if not ctx.args:
        await _send(update, "用法：/switch <会话名>")
        return
    name = ctx.args[0]
    try:
        sess = session_store.switch_session(name)
        running_note = "（⏳ 有任务在跑）" if task_manager.is_running(name) else ""
        await _send(update, f"✅ 已切换到会话 [{name}] {running_note}\n项目：{sess['project']}")
    except KeyError as e:
        await _send(update, f"❌ {e}")


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    current, sessions = session_store.list_sessions()
    if not sessions:
        await _send(update, "没有会话，用 /new <名称> <项目> 创建")
        return
    lines = ["📋 当前会话列表："]
    for name, info in sessions.items():
        marker = "👉 " if name == current else "   "
        tag = " 🔄" if task_manager.is_running(name) else ""
        lines.append(f"{marker}[{name}]{tag} → {info['project']}")
    await _send(update, "\n".join(lines))


async def cmd_drop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    if not ctx.args:
        await _send(update, "用法：/drop <会话名>")
        return
    name = ctx.args[0]
    if task_manager.is_running(name):
        await _send(update, f"❌ [{name}] 仍在执行任务，先 /kill 或等它完成")
        return
    session_store.drop_session(name)
    await _send(update, f"✅ 会话 [{name}] 已删除")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    name, sess = session_store.get_current()
    mode = session_store.get_mode()
    pending = session_store.get_pending_confirm()
    if not name:
        text = f"无活跃会话\n模式：{mode}\n用 /new <名称> <项目> 创建"
        if pending:
            text += f"\n\n⏸ 有待确认任务：{_truncate(pending.get('prompt', ''), 60)}\n   /confirm 执行 /cancel 取消"
        await _send(update, text)
        return
    running = "⏳ 有任务在跑" if task_manager.is_running(name) else "💤 空闲"
    text = f"当前会话：[{name}]\n项目：{sess['project']}\n模式：{mode}\n状态：{running}"
    if pending:
        text += f"\n\n⏸ 有待确认任务：{_truncate(pending.get('prompt', ''), 60)}\n   /confirm 执行 /cancel 取消"
    await _send(update, text)


def _truncate(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n] + "…"


async def cmd_tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    import time
    current, sessions = session_store.list_sessions()
    if not sessions:
        await _send(update, "没有会话")
        return
    lines = ["📋 全部会话"]
    for name, info in sessions.items():
        marker = "● " if name == current else "  "
        st = task_manager.get_state(name)
        if st:
            elapsed = time.time() - st.started_at
            tail = st.last_tool or "等待输出"
            lines.append(f"{marker}[{name}] 🔄 {_fmt_elapsed(elapsed)} · {st.tool_count}工具 · {tail}")
            lines.append(f"     ↳ {_truncate(st.prompt, 40)}")
        else:
            lines.append(f"{marker}[{name}] 💤 idle")
    await _send(update, "\n".join(lines))


async def cmd_kill(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """手动终止：/kill [会话名]，不带参数则杀当前会话的任务。"""
    if not _auth(update): return
    if ctx.args:
        name = ctx.args[0]
    else:
        name, _ = session_store.get_current()
    if not name:
        await _send(update, "❌ 没有指定会话")
        return
    if not task_manager.kill(name):
        await _send(update, f"[{name}] 没有在跑的任务")
        return
    await _send(update, f"🛑 已终止 [{name}]（Claude 子进程已 kill）")


# ── 模式切换 ─────────────────────────────────────────────────

async def cmd_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    if not ctx.args or ctx.args[0] not in ("auto", "preview"):
        await _send(update, "用法：/mode auto 或 /mode preview")
        return
    session_store.set_mode(ctx.args[0])
    await _send(update, f"✅ 默认模式已切换为：{ctx.args[0]}")


# ── 任务执行（fire-and-forget）─────────────────────────────────

async def _dispatch_bg(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    project_input: str,
    session_id: str | None,
    session_name: str,
    header: str,
) -> None:
    """发启动提示并把任务交给 task_manager。"""
    msg = await update.message.reply_text(header)
    await task_manager.start(
        bot=ctx.bot,
        session_name=session_name,
        prompt=prompt,
        project_input=project_input,
        session_id=session_id,
        chat_id=msg.chat_id,
        initial_msg_id=msg.message_id,
    )


async def _start_preview(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    name: str,
    sess: dict,
) -> None:
    """预览模式的公共入口：包 prompt、记 pending、派发任务。"""
    preview_prompt = (
        f"请先列出你打算做什么修改（不要实际修改任何文件），然后等待确认。需求：{prompt}"
    )
    session_store.set_pending_confirm(prompt, sess["project"], sess["session_id"])
    await _dispatch_bg(
        update, ctx, preview_prompt, sess["project"], sess["session_id"], name,
        header=f"⏳ [{name}] 预览生成中...（完成后回复 /confirm 执行 /cancel 取消）",
    )


async def cmd_run(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    name, sess = session_store.get_current()
    if not name:
        await _send(update, "❌ 没有活跃会话，请先用 /new 创建")
        return
    if await _reject_if_running(update, name): return
    prompt = " ".join(ctx.args)
    if not prompt:
        await _send(update, "用法：/run <需求描述>")
        return
    await _dispatch_bg(
        update, ctx, prompt, sess["project"], sess["session_id"], name,
        header=f"⏳ [{name}] 启动中...",
    )


async def cmd_preview(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    name, sess = session_store.get_current()
    if not name:
        await _send(update, "❌ 没有活跃会话，请先用 /new 创建")
        return
    if await _reject_if_running(update, name): return
    prompt = " ".join(ctx.args)
    if not prompt:
        await _send(update, "用法：/preview <需求描述>")
        return
    await _start_preview(update, ctx, prompt, name, sess)


async def cmd_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    pending = session_store.get_pending_confirm()
    if not pending:
        await _send(update, "❌ 没有待确认的任务")
        return
    name, _ = session_store.get_current()
    if not name:
        await _send(update, "❌ 没有活跃会话")
        return
    if await _reject_if_running(update, name): return
    session_store.clear_pending_confirm()
    # pending["session_id"] 是预览前的 sid；预览跑完 session_store 里已是最新 sid
    latest_sid = session_store.list_sessions()[1].get(name, {}).get("session_id")
    await _dispatch_bg(
        update, ctx, pending["prompt"], pending["project"], latest_sid, name,
        header=f"⏳ [{name}] 执行确认任务...",
    )


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    session_store.clear_pending_confirm()
    await _send(update, "✅ 已取消")


# ── 帮助 ─────────────────────────────────────────────────────

HELP_TEXT = """🤖 Telegram Claude Bot

━━ 会话管理 ━━
/new <名称> <项目>   新建会话，例：/new refactor shulex-gpt
/switch <名称>       切换当前会话
/list                列出所有会话
/drop <名称>         删除会话（不能删正在跑的）
/status              查看当前会话状态
/tasks               查看全部会话运行状态

━━ 任务执行 ━━
/run <需求>          直接执行
/preview <需求>      预览模式：先列计划，/confirm 执行
/confirm             确认执行待确认任务
/cancel              取消待确认任务
/kill [名称]         终止当前（或指定）会话的任务
/mode auto|preview   切换默认模式（直接发文本走这个模式）

━━ 快捷 ━━
直接发文本 = /run 或 /preview（看模式）

━━ 备注 ━━
• 项目路径支持 shulex 自动补前缀
• 单会话一次只能跑一个任务
• 多会话可并行
• 进度消息前 5min 每 4s 刷，之后 2min 一次
• 硬上限 1h"""


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    await _send(update, HELP_TEXT)


# ── 普通消息（转发给当前会话）─────────────────────────────────

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    name, sess = session_store.get_current()
    if not name:
        await _send(update, "❌ 没有活跃会话，请先用 /new 创建")
        return
    if await _reject_if_running(update, name): return
    prompt = update.message.text
    mode = session_store.get_mode()

    if mode == "preview":
        await _start_preview(update, ctx, prompt, name, sess)
    else:
        await _dispatch_bg(
            update, ctx, prompt, sess["project"], sess["session_id"], name,
            header=f"⏳ [{name}] 启动中...",
        )
