import json
import os
from datetime import datetime

SESSIONS_FILE = os.path.join(os.path.dirname(__file__), "sessions.json")

def _load() -> dict:
    if not os.path.exists(SESSIONS_FILE):
        return {"current": None, "sessions": {}, "pending_confirm": None, "mode": "auto"}
    with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def _save(data: dict) -> None:
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def new_session(name: str, project: str, session_id: str) -> None:
    data = _load()
    data["sessions"][name] = {
        "session_id": session_id,
        "project": project,
        "created": datetime.now().isoformat()
    }
    data["current"] = name
    _save(data)

def switch_session(name: str) -> dict:
    data = _load()
    if name not in data["sessions"]:
        raise KeyError(f"会话 `{name}` 不存在")
    data["current"] = name
    _save(data)
    return data["sessions"][name]

def get_current() -> tuple[str, dict] | tuple[None, None]:
    """返回 (name, session_dict) 或 (None, None)"""
    data = _load()
    name = data.get("current")
    if not name or name not in data["sessions"]:
        return None, None
    return name, data["sessions"][name]

def update_session_id(name: str, session_id: str) -> None:
    data = _load()
    if name in data["sessions"]:
        data["sessions"][name]["session_id"] = session_id
        _save(data)

def list_sessions() -> tuple[str | None, dict]:
    """返回 (current_name, sessions_dict)"""
    data = _load()
    return data.get("current"), data.get("sessions", {})

def drop_session(name: str) -> None:
    data = _load()
    data["sessions"].pop(name, None)
    if data.get("current") == name:
        data["current"] = None
    _save(data)

def set_pending_confirm(prompt: str, project: str, session_id: str | None) -> None:
    data = _load()
    data["pending_confirm"] = {
        "prompt": prompt,
        "project": project,
        "session_id": session_id
    }
    _save(data)

def get_pending_confirm() -> dict | None:
    return _load().get("pending_confirm")

def clear_pending_confirm() -> None:
    data = _load()
    data["pending_confirm"] = None
    _save(data)

def get_mode() -> str:
    return _load().get("mode", "auto")

def set_mode(mode: str) -> None:
    data = _load()
    data["mode"] = mode
    _save(data)
