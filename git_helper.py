import subprocess

MAX_DIFF_LINES = 200

def get_diff_summary(project_path: str) -> str:
    """
    返回 git 变更摘要：变更文件列表 + diff 内容（最多 200 行）。
    如果没有变更或不是 git 仓库，返回空字符串。
    """
    try:
        # 变更文件列表
        status = subprocess.run(
            ["git", "status", "--short"],
            cwd=project_path, capture_output=True, text=True, timeout=10
        )
        files = status.stdout.strip()
        if not files:
            return ""

        # diff 内容
        diff = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=project_path, capture_output=True, text=True, timeout=10
        )
        diff_lines = diff.stdout.splitlines()
        truncated = len(diff_lines) > MAX_DIFF_LINES
        diff_text = "\n".join(diff_lines[:MAX_DIFF_LINES])

        result = f"📁 变更文件：\n{files}\n\n📝 Git Diff：\n```\n{diff_text}\n```"
        if truncated:
            result += f"\n\n⚠️ Diff 过长已截断，完整 diff 请查看本地"
        return result

    except Exception:
        return ""
