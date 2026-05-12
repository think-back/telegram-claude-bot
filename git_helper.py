import asyncio

MAX_DIFF_LINES = 200

async def get_diff_summary(project_path: str) -> str:
    """
    返回 git 变更摘要：变更文件列表 + diff 内容（最多 200 行）。
    如果没有变更或不是 git 仓库，返回空字符串。
    """
    async def _run(*args: str) -> str | None:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=project_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return None
        return stdout.decode("utf-8", errors="replace")

    try:
        status = await _run("status", "--short")
        if status is None:
            return ""
        files = status.strip()
        if not files:
            return ""

        diff = await _run("diff", "HEAD")
        if diff is None:
            return ""
        diff_lines = diff.splitlines()
        truncated = len(diff_lines) > MAX_DIFF_LINES
        diff_text = "\n".join(diff_lines[:MAX_DIFF_LINES])

        result = f"📁 变更文件：\n{files}\n\n📝 Git Diff：\n```\n{diff_text}\n```"
        if truncated:
            result += f"\n\n⚠️ Diff 过长已截断，完整 diff 请查看本地"
        return result

    except Exception:
        return ""
