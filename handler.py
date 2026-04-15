from telegram import Update
from telegram.ext import ContextTypes
from config import ALLOWED_USER_ID
import session_store
import claude_runner
import git_helper
from path_resolver import resolve

MAX_MSG_LEN = 4096

async def _send(update: Update, text: str) -> None:
    """分段发送超长消息。"""
    for i in range(0, len(text), MAX_MSG_LEN):
        await update.message.reply_text(text[i:i + MAX_MSG_LEN])

def _auth(update: Update) -> bool:
    return update.effective_user.id == ALLOWED_USER_ID


# ── 会话管理命令 ──────────────────────────────────────────────

async def cmd_new(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    args = ctx.args
    if len(args) < 2:
        await _send(update, "用法：/new <会话名> <项目路径>\n例：/new refactor shulex-gpt")
        return
    name, project_input = args[0], "/".join(args[1:])
    try:
        project_path = resolve(project_input)
    except ValueError as e:
        await _send(update, f"❌ {e}")
        return
    await update.message.reply_text(f"⏳ 正在建立会话 [{name}]...")
    try:
        _, sid = claude_runner.run("你好，新会话开始", project_path)
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
        await _send(update, f"✅ 已切换到会话 [{name}]\n项目：{sess['project']}")
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
        lines.append(f"{marker}[{name}] → {info['project']}")
    await _send(update, "\n".join(lines))


async def cmd_drop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    if not ctx.args:
        await _send(update, "用法：/drop <会话名>")
        return
    session_store.drop_session(ctx.args[0])
    await _send(update, f"✅ 会话 [{ctx.args[0]}] 已删除")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    name, sess = session_store.get_current()
    mode = session_store.get_mode()
    if not name:
        await _send(update, f"无活跃会话\n模式：{mode}\n用 /new <名称> <项目> 创建")
        return
    await _send(update, f"当前会话：[{name}]\n项目：{sess['project']}\n模式：{mode}")


# ── 模式切换 ─────────────────────────────────────────────────

async def cmd_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    if not ctx.args or ctx.args[0] not in ("auto", "preview"):
        await _send(update, "用法：/mode auto 或 /mode preview")
        return
    session_store.set_mode(ctx.args[0])
    await _send(update, f"✅ 默认模式已切换为：{ctx.args[0]}")


# ── 任务执行 ─────────────────────────────────────────────────

async def _execute(update: Update, prompt: str, project_path: str, session_id: str | None, session_name: str) -> None:
    """执行 claude 并回复结果。"""
    try:
        reply, new_sid = claude_runner.run(prompt, project_path, session_id)
        session_store.update_session_id(session_name, new_sid)
        diff = git_helper.get_diff_summary(project_path)
        response = reply
        if diff:
            response += f"\n\n{diff}"
        await _send(update, response or "（Claude 无输出）")
    except TimeoutError:
        await _send(update, "⏱ 执行超时（5min），请缩小任务范围")
    except Exception as e:
        await _send(update, f"❌ 执行失败：{e}")


async def cmd_run(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    name, sess = session_store.get_current()
    if not name:
        await _send(update, "❌ 没有活跃会话，请先用 /new 创建")
        return
    prompt = " ".join(ctx.args)
    if not prompt:
        await _send(update, "用法：/run <需求描述>")
        return
    project_path = resolve(sess["project"])
    await update.message.reply_text(f"⏳ 执行中... [{name}]")
    await _execute(update, prompt, project_path, sess["session_id"], name)


async def cmd_preview(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    name, sess = session_store.get_current()
    if not name:
        await _send(update, "❌ 没有活跃会话，请先用 /new 创建")
        return
    prompt = " ".join(ctx.args)
    if not prompt:
        await _send(update, "用法：/preview <需求描述>")
        return
    project_path = resolve(sess["project"])
    preview_prompt = f"请先列出你打算做什么修改（不要实际修改任何文件），然后等待确认。需求：{prompt}"
    await update.message.reply_text(f"⏳ 生成预览... [{name}]")
    try:
        reply, new_sid = claude_runner.run(preview_prompt, project_path, sess["session_id"])
        session_store.update_session_id(name, new_sid)
        session_store.set_pending_confirm(prompt, sess["project"], new_sid)
        await _send(update, f"{reply}\n\n回复 /confirm 执行，/cancel 取消")
    except Exception as e:
        await _send(update, f"❌ 预览失败：{e}")


async def cmd_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    pending = session_store.get_pending_confirm()
    if not pending:
        await _send(update, "❌ 没有待确认的任务")
        return
    session_store.clear_pending_confirm()
    name, sess = session_store.get_current()
    project_path = resolve(pending["project"])
    await update.message.reply_text(f"⏳ 执行中... [{name}]")
    await _execute(update, pending["prompt"], project_path, pending["session_id"], name)


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    session_store.clear_pending_confirm()
    await _send(update, "✅ 已取消")


# ── 普通消息（转发给当前会话）─────────────────────────────────

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    name, sess = session_store.get_current()
    if not name:
        await _send(update, "❌ 没有活跃会话，请先用 /new 创建")
        return
    prompt = update.message.text
    mode = session_store.get_mode()
    project_path = resolve(sess["project"])

    if mode == "preview":
        preview_prompt = f"请先列出你打算做什么修改（不要实际修改任何文件），然后等待确认。需求：{prompt}"
        await update.message.reply_text(f"⏳ 生成预览... [{name}]")
        try:
            reply, new_sid = claude_runner.run(preview_prompt, project_path, sess["session_id"])
            session_store.update_session_id(name, new_sid)
            session_store.set_pending_confirm(prompt, sess["project"], new_sid)
            await _send(update, f"{reply}\n\n回复 /confirm 执行，/cancel 取消")
        except Exception as e:
            await _send(update, f"❌ 预览失败：{e}")
    else:
        await update.message.reply_text(f"⏳ 处理中... [{name}]")
        await _execute(update, prompt, project_path, sess["session_id"], name)
