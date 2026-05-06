import os
import time
from config import WORKSPACE_ROOT

# shulex 下的直接子目录集合，TTL 60s
_SHULEX_CACHE: dict[str, object] = {"ts": 0.0, "value": set()}
_CACHE_TTL = 60.0

def _get_shulex_projects() -> set[str]:
    now = time.time()
    if now - _SHULEX_CACHE["ts"] < _CACHE_TTL and _SHULEX_CACHE["value"]:
        return _SHULEX_CACHE["value"]  # type: ignore[return-value]
    shulex_dir = os.path.join(WORKSPACE_ROOT, "shulex")
    value: set[str] = set()
    if os.path.isdir(shulex_dir):
        try:
            value = {
                d for d in os.listdir(shulex_dir)
                if os.path.isdir(os.path.join(shulex_dir, d))
            }
        except OSError:
            pass
    _SHULEX_CACHE["ts"] = now
    _SHULEX_CACHE["value"] = value
    return value

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
