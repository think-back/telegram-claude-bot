import os
from config import WORKSPACE_ROOT

# shulex 下的直接子目录集合（运行时扫描一次）
_SHULEX_PROJECTS: set[str] = set()

def _get_shulex_projects() -> set[str]:
    global _SHULEX_PROJECTS
    if not _SHULEX_PROJECTS:
        shulex_dir = os.path.join(WORKSPACE_ROOT, "shulex")
        if os.path.isdir(shulex_dir):
            _SHULEX_PROJECTS = {
                d for d in os.listdir(shulex_dir)
                if os.path.isdir(os.path.join(shulex_dir, d))
            }
    return _SHULEX_PROJECTS

def resolve(project_input: str) -> str:
    """
    将用户输入的项目路径解析为本地绝对路径。

    规则：
    - 如果第一段是 shulex 下的直接子目录名，自动补 shulex/ 前缀
    - 其余情况直接拼接到 WORKSPACE_ROOT
    - 路径不存在则抛 ValueError
    """
    parts = project_input.strip("/").split("/")
    first = parts[0]

    if first in _get_shulex_projects():
        full_path = os.path.join(WORKSPACE_ROOT, "shulex", *parts)
    else:
        full_path = os.path.join(WORKSPACE_ROOT, *parts)

    full_path = os.path.normpath(full_path)

    if not os.path.isdir(full_path):
        raise ValueError(f"找不到项目 `{project_input}`，路径不存在：{full_path}")

    return full_path
