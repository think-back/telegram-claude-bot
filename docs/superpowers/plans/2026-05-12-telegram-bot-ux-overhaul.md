# Telegram Claude Bot · UX Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把散装命令 + 时间节流的体验升级成"按需召唤的会话面板 + 事件驱动进度"，并补必要的单测。

**Architecture:** 在 `handler` 和 `claude_runner` 之间插入 `progress_emitter`（把 stream-json 转语义事件）和 `panel`（统一会话视图 + Inline 按钮 + 活面板登记表）；新增 `forcereply_bridge` 处理"按钮 + 文字输入"的状态映射。老命令保留不动。

**Tech Stack:** Python 3.10+ · python-telegram-bot 22.7 (async) · pytest + pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-05-12-telegram-bot-ux-overhaul-design.md`

---

## File Structure Overview

| 文件 | 状态 | 责任 |
|------|------|------|
| `progress_emitter.py` | 新增 | 纯逻辑：raw stream-json → 语义事件，无 I/O |
| `forcereply_bridge.py` | 新增 | ForceReply pending 状态机 + TTL，无 I/O |
| `panel.py` | 新增 | 面板渲染、活面板登记表、callback 路由、广播刷新 |
| `task_manager.py` | 改 | 删除时间节流；订阅 `progress_emitter`；事件触发 `panel.broadcast_change` 与详情消息编辑 |
| `handler.py` | 改 | 新增 `cmd_panel`、callback 入口、ForceReply reply 抓取、`/preview` 完成挂【确认/取消】按钮；老命令保留 |
| `bot.py` | 改 | 注册 `CallbackQueryHandler` + `/panel` 命令 |
| `tests/conftest.py` | 新增 | pytest-asyncio 配置 |
| `tests/test_progress_emitter.py` | 新增 | 语义事件触发时点 |
| `tests/test_panel.py` | 新增 | 渲染快照 + callback_data 编解码 + 不可用按钮提示 |
| `requirements.txt` | 改 | 加 pytest、pytest-asyncio |

---

## Task 1: 测试基建

**Files:**
- Modify: `requirements.txt`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: 加测试依赖**

修改 `requirements.txt`：

```
python-telegram-bot==22.7
python-dotenv==1.0.0
pytest==8.3.3
pytest-asyncio==0.24.0
```

- [ ] **Step 2: 装依赖**

Run: `pip install pytest==8.3.3 pytest-asyncio==0.24.0`
Expected: 安装成功

- [ ] **Step 3: 建 tests 包**

创建 `tests/__init__.py` 空文件。

创建 `tests/conftest.py`：

```python
import pytest

# 允许 pytest-asyncio 自动识别 async 测试，无需每个加 @pytest.mark.asyncio
pytest_plugins = ("pytest_asyncio",)

def pytest_collection_modifyitems(config, items):
    for item in items:
        if "asyncio" in item.keywords:
            continue
        # 仅对 async def 自动加 marker
        if hasattr(item, "function") and getattr(item.function, "__code__", None):
            if item.function.__code__.co_flags & 0x100:  # CO_COROUTINE
                item.add_marker(pytest.mark.asyncio)
```

加 `pytest.ini` 在项目根：

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 4: 跑空套件验证**

Run: `pytest tests/ -v`
Expected: `no tests ran` 或 `collected 0 items`，没有报错

- [ ] **Step 5: Commit**

```bash
git add requirements.txt tests/__init__.py tests/conftest.py pytest.ini
git commit -m "test: bootstrap pytest + pytest-asyncio infrastructure"
```

---

## Task 2: progress_emitter 测试先行

**Files:**
- Create: `tests/test_progress_emitter.py`

- [ ] **Step 1: 写完整测试套**

创建 `tests/test_progress_emitter.py`：

```python
"""progress_emitter 把 claude_runner 的 stream-json 事件转语义事件。"""
import pytest
from progress_emitter import (
    EmitterState, feed, maybe_heartbeat, EventKind,
    HEARTBEAT_SEC,
)


def tool_event(name, preview=""):
    return {"kind": "tool_use", "name": name, "input_preview": preview}


def test_first_tool_use_triggers_tool_switch():
    state = EmitterState(started_at=1000.0)
    sem = feed(state, tool_event("Read", "bot.py"), now=1001.0)
    assert sem is not None
    assert sem.kind == EventKind.TOOL_SWITCH
    assert "Read" in sem.text
    assert state.last_tool == "Read"


def test_same_tool_repeated_no_emit():
    state = EmitterState(started_at=1000.0)
    feed(state, tool_event("Read", "a.py"), now=1001.0)
    sem = feed(state, tool_event("Read", "b.py"), now=1002.0)
    assert sem is None


def test_tool_switch_back_and_forth():
    state = EmitterState(started_at=1000.0)
    feed(state, tool_event("Read", "a.py"), now=1001.0)
    s1 = feed(state, tool_event("Grep", "foo"), now=1002.0)
    s2 = feed(state, tool_event("Read", "b.py"), now=1003.0)
    assert s1.kind == EventKind.TOOL_SWITCH and "Grep" in s1.text
    assert s2.kind == EventKind.TOOL_SWITCH and "Read" in s2.text


def test_first_write_fires_once():
    state = EmitterState(started_at=1000.0)
    sem = feed(state, tool_event("Edit", "bot.py"), now=1001.0)
    assert sem.kind == EventKind.FIRST_WRITE
    assert "bot.py" in sem.text
    # 第二次 Edit 不再触发 first_write，且 last_tool 未变所以也无 tool_switch
    s2 = feed(state, tool_event("Edit", "x.py"), now=1002.0)
    assert s2 is None
    # 切到别的工具再切回 Edit 触发 tool_switch（不是 first_write）
    feed(state, tool_event("Read", "y.py"), now=1003.0)
    s3 = feed(state, tool_event("Edit", "z.py"), now=1004.0)
    assert s3.kind == EventKind.TOOL_SWITCH


def test_first_write_covers_write_edit_multiedit():
    for tool in ("Write", "Edit", "MultiEdit"):
        state = EmitterState(started_at=1000.0)
        sem = feed(state, tool_event(tool, "a.py"), now=1001.0)
        assert sem.kind == EventKind.FIRST_WRITE, tool


def test_first_test_via_pytest():
    state = EmitterState(started_at=1000.0)
    sem = feed(state, tool_event("Bash", "pytest tests/foo.py"), now=1001.0)
    assert sem.kind == EventKind.FIRST_TEST


def test_first_test_via_npm():
    state = EmitterState(started_at=1000.0)
    sem = feed(state, tool_event("Bash", "npm test -- --watch"), now=1001.0)
    assert sem.kind == EventKind.FIRST_TEST


def test_first_test_fires_once():
    state = EmitterState(started_at=1000.0)
    feed(state, tool_event("Bash", "pytest a"), now=1001.0)
    s2 = feed(state, tool_event("Bash", "pytest b"), now=1002.0)
    # 第二次 pytest：不再触发 first_test，但是 last_tool 仍是 Bash 所以也不切换
    assert s2 is None


def test_first_git_via_prefix():
    state = EmitterState(started_at=1000.0)
    sem = feed(state, tool_event("Bash", "git status"), now=1001.0)
    assert sem.kind == EventKind.FIRST_GIT
    assert "git status" in sem.text


def test_non_git_bash_not_treated_as_git():
    state = EmitterState(started_at=1000.0)
    sem = feed(state, tool_event("Bash", "ls -la"), now=1001.0)
    assert sem.kind == EventKind.TOOL_SWITCH  # 仅 Bash 切换


def test_error_event_emits_and_marks_is_error():
    state = EmitterState(started_at=1000.0)
    sem = feed(state, {"kind": "error", "message": "boom"}, now=1001.0)
    assert sem.kind == EventKind.ERROR
    assert sem.is_error is True
    assert "boom" in sem.text


def test_text_event_no_emit():
    state = EmitterState(started_at=1000.0)
    sem = feed(state, {"kind": "text", "text": "hello"}, now=1001.0)
    assert sem is None


def test_done_event_no_emit():
    state = EmitterState(started_at=1000.0)
    sem = feed(state, {"kind": "done", "returncode": 0}, now=1001.0)
    assert sem is None


def test_heartbeat_no_activity_yet():
    """任务起步阶段（last_emit_ts == 0），HEARTBEAT_SEC 后仍要兜底心跳。"""
    state = EmitterState(started_at=1000.0)
    sem = maybe_heartbeat(state, now=1000.0 + HEARTBEAT_SEC + 1)
    assert sem is not None
    assert sem.kind == EventKind.HEARTBEAT


def test_heartbeat_not_yet_due():
    state = EmitterState(started_at=1000.0)
    feed(state, tool_event("Read", "a.py"), now=1001.0)
    sem = maybe_heartbeat(state, now=1010.0)
    assert sem is None


def test_heartbeat_fires_after_silence():
    state = EmitterState(started_at=1000.0)
    feed(state, tool_event("Read", "a.py"), now=1001.0)
    sem = maybe_heartbeat(state, now=1001.0 + HEARTBEAT_SEC + 0.1)
    assert sem is not None
    assert sem.kind == EventKind.HEARTBEAT


def test_heartbeat_resets_after_real_event():
    state = EmitterState(started_at=1000.0)
    feed(state, tool_event("Read", "a.py"), now=1001.0)
    hb = maybe_heartbeat(state, now=1001.0 + HEARTBEAT_SEC + 0.1)
    assert hb is not None
    # 心跳后再来一个事件，心跳计时归零
    feed(state, tool_event("Grep", "x"), now=1001.0 + HEARTBEAT_SEC + 1)
    sem = maybe_heartbeat(state, now=1001.0 + HEARTBEAT_SEC + 2)
    assert sem is None  # 还没到下一轮心跳
```

- [ ] **Step 2: 跑测试，确认全部失败（模块未实现）**

Run: `pytest tests/test_progress_emitter.py -v`
Expected: 全部 FAIL 或 `ImportError: No module named 'progress_emitter'`

- [ ] **Step 3: Commit 失败测试**

```bash
git add tests/test_progress_emitter.py
git commit -m "test: add progress_emitter test suite (failing)"
```

---

## Task 3: 实现 progress_emitter

**Files:**
- Create: `progress_emitter.py`

- [ ] **Step 1: 写实现**

创建 `progress_emitter.py`：

```python
"""把 claude_runner 的 stream-json 原始事件转译成"语义事件"。

不做 I/O、不依赖 Telegram —— 纯函数 + 显式 EmitterState 便于单测。
任一 raw event 至多产出 0 或 1 个 SemanticEvent。
"""
from dataclasses import dataclass
from enum import Enum

HEARTBEAT_SEC = 120

# Bash 命令中包含其一即视为"跑测试"（substring 匹配，preview 已被 claude_runner 截到 60 字符）
TEST_CMD_HINTS = (
    "pytest", "npm test", "yarn test", "pnpm test",
    "go test", "mvn test", "cargo test", "jest", "vitest",
)

WRITE_TOOLS = ("Write", "Edit", "MultiEdit")


class EventKind(Enum):
    TOOL_SWITCH = "tool_switch"
    FIRST_WRITE = "first_write"
    FIRST_TEST = "first_test"
    FIRST_GIT = "first_git"
    ERROR = "error"
    HEARTBEAT = "heartbeat"


@dataclass
class SemanticEvent:
    kind: EventKind
    text: str            # 详情消息 header 文案
    tool: str = ""       # tool_switch / first_* 时的 tool 名
    is_error: bool = False


@dataclass
class EmitterState:
    started_at: float           # 任务开始时间（外部传入）
    last_tool: str = ""
    seen_write: bool = False
    seen_test: bool = False
    seen_git: bool = False
    last_emit_ts: float = 0.0   # 上次产出 SemanticEvent 的时刻


def feed(state: EmitterState, event: dict, now: float) -> SemanticEvent | None:
    """消费一个原始事件，可能产出 0/1 个语义事件。会原地更新 state。"""
    kind = event.get("kind")

    if kind == "tool_use":
        tool = event.get("name", "?")
        preview = event.get("input_preview", "") or ""

        # 优先级：first_write > first_test > first_git > tool_switch
        if tool in WRITE_TOOLS and not state.seen_write:
            state.seen_write = True
            state.last_tool = tool
            state.last_emit_ts = now
            target = preview or "?"
            return SemanticEvent(
                EventKind.FIRST_WRITE,
                f"✍️ 开始改代码 (首个文件: {target})",
                tool=tool,
            )

        if tool == "Bash":
            if not state.seen_test and any(h in preview for h in TEST_CMD_HINTS):
                state.seen_test = True
                state.last_tool = tool
                state.last_emit_ts = now
                return SemanticEvent(EventKind.FIRST_TEST, "🧪 跑测试中", tool=tool)
            if not state.seen_git and preview.startswith("git "):
                state.seen_git = True
                state.last_tool = tool
                state.last_emit_ts = now
                return SemanticEvent(
                    EventKind.FIRST_GIT,
                    f"📦 git 操作: {preview[:60]}",
                    tool=tool,
                )

        if tool != state.last_tool:
            state.last_tool = tool
            state.last_emit_ts = now
            target = preview or ""
            text = f"🛠 切到 {tool}" + (f": {target}" if target else "")
            return SemanticEvent(EventKind.TOOL_SWITCH, text, tool=tool)

        return None

    if kind == "error":
        msg = (event.get("message", "") or "")[:120]
        state.last_emit_ts = now
        return SemanticEvent(EventKind.ERROR, f"❌ 工具出错: {msg}", is_error=True)

    # text / result / done 不触发语义事件
    return None


def maybe_heartbeat(state: EmitterState, now: float) -> SemanticEvent | None:
    """没有真实事件时的兜底心跳。"""
    # 从未产出过事件：以 started_at 为基线
    baseline = state.last_emit_ts if state.last_emit_ts > 0 else state.started_at
    if now - baseline < HEARTBEAT_SEC:
        return None
    state.last_emit_ts = now
    minutes = int((now - state.started_at) // 60)
    return SemanticEvent(EventKind.HEARTBEAT, f"⏳ 仍在运行 · 已 {minutes} 分")
```

- [ ] **Step 2: 跑测试**

Run: `pytest tests/test_progress_emitter.py -v`
Expected: 16 passed

- [ ] **Step 3: Commit**

```bash
git add progress_emitter.py
git commit -m "feat: progress_emitter — stream-json to semantic events"
```

---

## Task 4: forcereply_bridge

**Files:**
- Create: `forcereply_bridge.py`
- Create: `tests/test_forcereply_bridge.py`

- [ ] **Step 1: 写测试**

创建 `tests/test_forcereply_bridge.py`：

```python
import forcereply_bridge as frb
from forcereply_bridge import PendingKind


def setup_function():
    frb._pending.clear()


def test_register_and_consume_within_ttl():
    frb.register(chat_id=1, prompt_msg_id=10, kind=PendingKind.NEW_SESSION, now=1000.0)
    p = frb.consume(chat_id=1, reply_to_msg_id=10, now=1100.0)
    assert p is not None
    assert p.kind == PendingKind.NEW_SESSION


def test_consume_removes_entry():
    frb.register(1, 10, PendingKind.NEW_SESSION, now=1000.0)
    frb.consume(1, 10, now=1001.0)
    assert frb.consume(1, 10, now=1002.0) is None


def test_consume_after_ttl_returns_none():
    frb.register(1, 10, PendingKind.NEW_SESSION, now=1000.0)
    p = frb.consume(1, 10, now=1000.0 + frb.TTL_SEC + 1)
    assert p is None


def test_consume_wrong_msg_id():
    frb.register(1, 10, PendingKind.NEW_SESSION, now=1000.0)
    assert frb.consume(1, 11, now=1001.0) is None


def test_consume_wrong_chat_id():
    frb.register(1, 10, PendingKind.NEW_SESSION, now=1000.0)
    assert frb.consume(2, 10, now=1001.0) is None


def test_gc_removes_expired():
    frb.register(1, 10, PendingKind.NEW_SESSION, now=1000.0)
    frb.register(1, 11, PendingKind.NEW_SESSION, now=1500.0)
    removed = frb.gc(now=1000.0 + frb.TTL_SEC + 1)
    assert removed == 1
    assert frb.consume(1, 10, now=1500.0) is None
    assert frb.consume(1, 11, now=1500.0) is not None
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `pytest tests/test_forcereply_bridge.py -v`
Expected: ImportError 或全部 FAIL

- [ ] **Step 3: 写实现**

创建 `forcereply_bridge.py`：

```python
"""ForceReply 流程的 pending 状态机。

Telegram 的 ForceReply 没有内建上下文。本模块负责:
- bot 发出 ForceReply 提示时登记 (chat_id, prompt_msg_id) → 待执行动作
- 用户的 reply 到达时按 (chat_id, reply_to_msg_id) 反查动作
- 5 分钟内没 reply 自动 GC
"""
import time
from dataclasses import dataclass
from enum import Enum

TTL_SEC = 300


class PendingKind(Enum):
    NEW_SESSION = "new_session"


@dataclass
class Pending:
    chat_id: int
    prompt_msg_id: int
    kind: PendingKind
    created_at: float


# (chat_id, prompt_msg_id) → Pending
_pending: dict[tuple[int, int], Pending] = {}


def register(
    chat_id: int,
    prompt_msg_id: int,
    kind: PendingKind,
    now: float | None = None,
) -> None:
    if now is None:
        now = time.time()
    _pending[(chat_id, prompt_msg_id)] = Pending(
        chat_id=chat_id, prompt_msg_id=prompt_msg_id, kind=kind, created_at=now,
    )


def consume(
    chat_id: int,
    reply_to_msg_id: int,
    now: float | None = None,
) -> Pending | None:
    if now is None:
        now = time.time()
    key = (chat_id, reply_to_msg_id)
    p = _pending.pop(key, None)
    if p is None:
        return None
    if now - p.created_at > TTL_SEC:
        return None
    return p


def gc(now: float | None = None) -> int:
    if now is None:
        now = time.time()
    expired = [k for k, p in _pending.items() if now - p.created_at > TTL_SEC]
    for k in expired:
        _pending.pop(k, None)
    return len(expired)
```

- [ ] **Step 4: 跑测试**

Run: `pytest tests/test_forcereply_bridge.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add forcereply_bridge.py tests/test_forcereply_bridge.py
git commit -m "feat: forcereply_bridge — ForceReply pending state machine"
```

---

## Task 5: panel 渲染纯函数（先写测试）

**Files:**
- Create: `tests/test_panel.py`

- [ ] **Step 1: 写渲染测试**

创建 `tests/test_panel.py`：

```python
import pytest
from unittest.mock import patch, MagicMock

import panel
from panel import PanelRecord


@pytest.fixture(autouse=True)
def _isolate_state():
    panel._panels.clear()
    panel._session_error_flags.clear()
    yield
    panel._panels.clear()
    panel._session_error_flags.clear()


def _mock_sessions(current, sessions):
    return patch("panel.session_store.list_sessions", return_value=(current, sessions))


def _mock_get_state(map_):
    def fn(name):
        return map_.get(name)
    return patch("panel.task_manager.get_state", side_effect=fn)


def test_render_empty():
    rec = PanelRecord(chat_id=1, msg_id=10)
    with _mock_sessions(None, {}), _mock_get_state({}):
        text, kb = panel.render(rec)
    assert "暂无会话" in text
    assert rec.session_names == []
    # 仍有底部 3 个全局按钮
    rows = kb.inline_keyboard
    assert len(rows) == 1
    assert [b.callback_data for b in rows[0]] == ["new", "rf", "cls"]


def test_render_one_idle_session():
    rec = PanelRecord(chat_id=1, msg_id=10)
    sessions = {"foo": {"project": "shulex-gpt", "session_id": "s1", "created": "x"}}
    with _mock_sessions("foo", sessions), _mock_get_state({}):
        text, kb = panel.render(rec)
    assert "foo" in text
    assert "shulex-gpt" in text
    assert "idle" in text
    assert rec.session_names == ["foo"]
    # 行按钮：sw:0 / kl:0 / dt:0 / dr:0
    row = kb.inline_keyboard[0]
    assert [b.callback_data for b in row] == ["sw:0", "kl:0", "dt:0", "dr:0"]


def test_render_running_session_uses_green():
    rec = PanelRecord(chat_id=1, msg_id=10)
    sessions = {"foo": {"project": "p", "session_id": "s", "created": "x"}}
    fake_state = MagicMock(started_at=0.0, last_tool="Edit(a.py)", tool_count=3)
    with _mock_sessions("foo", sessions), _mock_get_state({"foo": fake_state}):
        text, _ = panel.render(rec)
    assert "🟢" in text
    assert "Edit" in text


def test_render_error_flag_makes_yellow():
    rec = PanelRecord(chat_id=1, msg_id=10)
    sessions = {"foo": {"project": "p", "session_id": "s", "created": "x"}}
    panel.mark_session_error("foo")
    with _mock_sessions("foo", sessions), _mock_get_state({}):
        text, _ = panel.render(rec)
    assert "🟡" in text


def test_render_multiple_sessions_indices():
    rec = PanelRecord(chat_id=1, msg_id=10)
    sessions = {
        "a": {"project": "p1", "session_id": "s", "created": "x"},
        "b": {"project": "p2", "session_id": "s", "created": "x"},
        "c": {"project": "p3", "session_id": "s", "created": "x"},
    }
    with _mock_sessions("a", sessions), _mock_get_state({}):
        _, kb = panel.render(rec)
    assert rec.session_names == ["a", "b", "c"]
    # 第二行第二个按钮（💀 for b）应该是 kl:1
    assert kb.inline_keyboard[1][1].callback_data == "kl:1"


def test_render_pending_drop_shows_confirm_button():
    rec = PanelRecord(chat_id=1, msg_id=10)
    rec.pending_drop.add(0)
    sessions = {"foo": {"project": "p", "session_id": "s", "created": "x"}}
    with _mock_sessions("foo", sessions), _mock_get_state({}):
        _, kb = panel.render(rec)
    # 第 4 个按钮变为 dr2:0
    assert kb.inline_keyboard[0][3].callback_data == "dr2:0"


def test_register_get_unregister():
    rec = panel.register_panel(chat_id=1, msg_id=99)
    assert panel.get_panel(1, 99) is rec
    panel.unregister_panel(1, 99)
    assert panel.get_panel(1, 99) is None


def test_gc_removes_stale_panels():
    rec = panel.register_panel(1, 10)
    rec.last_touched_at = 0  # 远古时刻
    panel.register_panel(1, 11)  # 新鲜
    removed = panel.gc(now=panel.PANEL_TTL_SEC + 1)
    assert removed == 1
    assert panel.get_panel(1, 10) is None
    assert panel.get_panel(1, 11) is not None


def test_mark_and_clear_session_error():
    panel.mark_session_error("x")
    assert "x" in panel._session_error_flags
    panel.clear_session_error("x")
    assert "x" not in panel._session_error_flags
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `pytest tests/test_panel.py -v`
Expected: ImportError（panel 模块还不存在）

- [ ] **Step 3: Commit**

```bash
git add tests/test_panel.py
git commit -m "test: add panel render + state test suite (failing)"
```

---

## Task 6: 实现 panel.py（渲染 + 登记表）

**Files:**
- Create: `panel.py`

- [ ] **Step 1: 写最小骨架，让渲染相关测试过**

创建 `panel.py`：

```python
"""会话面板：渲染 + 活面板登记表 + callback 路由 + 广播刷新。"""
import asyncio
import logging
import time
from dataclasses import dataclass, field

from telegram import (
    Bot, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply,
)
from telegram.error import BadRequest, RetryAfter, TimedOut

import session_store
import task_manager
import forcereply_bridge

log = logging.getLogger(__name__)

PANEL_TTL_SEC = 600


@dataclass
class PanelRecord:
    chat_id: int
    msg_id: int
    session_names: list[str] = field(default_factory=list)
    last_touched_at: float = field(default_factory=time.time)
    pending_drop: set[int] = field(default_factory=set)


# 活面板登记表: (chat_id, msg_id) -> PanelRecord
_panels: dict[tuple[int, int], PanelRecord] = {}

# 全局会话错误标记（跨面板共享）
_session_error_flags: set[str] = set()

# debounce: 同一面板的 broadcast 50ms 内合并
_debounce_handles: dict[tuple[int, int], asyncio.Task] = {}


def mark_session_error(name: str) -> None:
    _session_error_flags.add(name)


def clear_session_error(name: str) -> None:
    _session_error_flags.discard(name)


def render(panel: PanelRecord) -> tuple[str, InlineKeyboardMarkup]:
    """渲染面板文本和按钮；同时刷新 panel.session_names 索引。"""
    current, sessions = session_store.list_sessions()
    panel.session_names = list(sessions.keys())

    ts = time.strftime("%H:%M")
    lines = [f"🎛 会话面板  ({ts})", "─────────────────"]
    keyboard: list[list[InlineKeyboardButton]] = []

    if not sessions:
        lines.append("（暂无会话，点 ➕ 新建）")
    else:
        for idx, name in enumerate(panel.session_names):
            info = sessions[name]
            project = info.get("project", "?")
            st = task_manager.get_state(name)
            has_err = name in _session_error_flags

            if st:
                elapsed_m = int((time.time() - st.started_at) // 60)
                tail = st.last_tool or "等待输出"
                light = "🟡" if has_err else "🟢"
                summary = f"{light} {name} · {project} · {tail} · {elapsed_m}m"
            elif has_err:
                summary = f"🟡 {name} · {project} · 异常结束"
            else:
                summary = f"⚪ {name} · {project} · idle"

            marker = "● " if name == current else ""
            lines.append(f"{marker}{summary}")

            pending = idx in panel.pending_drop
            row = [
                InlineKeyboardButton("🔄", callback_data=f"sw:{idx}"),
                InlineKeyboardButton("💀", callback_data=f"kl:{idx}"),
                InlineKeyboardButton("📋", callback_data=f"dt:{idx}"),
                InlineKeyboardButton(
                    "⚠确认删" if pending else "🗑",
                    callback_data=f"dr2:{idx}" if pending else f"dr:{idx}",
                ),
            ]
            keyboard.append(row)

    lines.append("─────────────────")
    keyboard.append([
        InlineKeyboardButton("➕ 新建", callback_data="new"),
        InlineKeyboardButton("🔃 刷新", callback_data="rf"),
        InlineKeyboardButton("❌ 关闭", callback_data="cls"),
    ])
    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


def register_panel(chat_id: int, msg_id: int) -> PanelRecord:
    rec = PanelRecord(chat_id=chat_id, msg_id=msg_id)
    _panels[(chat_id, msg_id)] = rec
    return rec


def get_panel(chat_id: int, msg_id: int) -> PanelRecord | None:
    return _panels.get((chat_id, msg_id))


def unregister_panel(chat_id: int, msg_id: int) -> None:
    _panels.pop((chat_id, msg_id), None)


def gc(now: float | None = None) -> int:
    if now is None:
        now = time.time()
    stale = [k for k, p in _panels.items() if now - p.last_touched_at > PANEL_TTL_SEC]
    for k in stale:
        _panels.pop(k, None)
    return len(stale)


# refresh / broadcast / dispatch_callback 在下一个任务里补
```

- [ ] **Step 2: 跑测试**

Run: `pytest tests/test_panel.py -v`
Expected: 9 passed

- [ ] **Step 3: Commit**

```bash
git add panel.py
git commit -m "feat: panel render + active-panel registry"
```

---

## Task 7: panel 的 refresh / broadcast / dispatch_callback

**Files:**
- Modify: `panel.py`

- [ ] **Step 1: 在 panel.py 文件末尾追加**

替换 `panel.py` 末尾的注释行 `# refresh / broadcast / dispatch_callback 在下一个任务里补`，改为：

```python
async def refresh(bot: Bot, p: PanelRecord) -> bool:
    text, kb = render(p)
    try:
        await bot.edit_message_text(
            chat_id=p.chat_id, message_id=p.msg_id, text=text, reply_markup=kb,
        )
        p.last_touched_at = time.time()
        return True
    except BadRequest as e:
        if "not modified" in str(e).lower():
            p.last_touched_at = time.time()
            return True
        log.warning("panel edit BadRequest: %s", e)
        unregister_panel(p.chat_id, p.msg_id)
        return False
    except RetryAfter as e:
        log.warning("panel TG rate-limited, retry after %ss", e.retry_after)
        await asyncio.sleep(float(e.retry_after) + 0.5)
        return False
    except TimedOut:
        return False
    except Exception:
        log.exception("panel refresh 失败")
        return False


async def broadcast_change(bot: Bot, session_name: str | None = None) -> None:
    """会话状态变化时调用：对所有活面板触发 debounce 刷新。"""
    gc()
    for p in list(_panels.values()):
        _schedule_refresh(bot, p)


def _schedule_refresh(bot: Bot, p: PanelRecord) -> None:
    key = (p.chat_id, p.msg_id)
    existing = _debounce_handles.get(key)
    if existing and not existing.done():
        return

    async def _do():
        try:
            await asyncio.sleep(0.05)
            await refresh(bot, p)
        finally:
            _debounce_handles.pop(key, None)

    _debounce_handles[key] = asyncio.create_task(_do(), name=f"panel-refresh:{key}")


async def dispatch_callback(bot: Bot, callback_query) -> None:
    """处理面板相关 CallbackQuery（鉴权由上层完成；/preview 的 cf:/cn: 不进这里）。"""
    chat_id = callback_query.message.chat_id
    msg_id = callback_query.message.message_id
    data = callback_query.data or ""

    p = get_panel(chat_id, msg_id)
    if p is None:
        await callback_query.answer("面板已过期，请重发 /panel", show_alert=True)
        return

    p.last_touched_at = time.time()

    if data == "rf":
        await callback_query.answer("已刷新")
        await refresh(bot, p)
        return
    if data == "cls":
        await callback_query.answer("已关闭")
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text="🎛 面板已关闭")
        except Exception:
            pass
        unregister_panel(chat_id, msg_id)
        return
    if data == "new":
        await callback_query.answer()
        prompt = await bot.send_message(
            chat_id=chat_id,
            text="请回复这条消息，格式：<会话名> <项目路径>\n例：refactor shulex-gpt",
            reply_markup=ForceReply(selective=True),
        )
        forcereply_bridge.register(
            chat_id, prompt.message_id, forcereply_bridge.PendingKind.NEW_SESSION,
        )
        return

    try:
        prefix, idx_str = data.split(":", 1)
        idx = int(idx_str)
    except ValueError:
        await callback_query.answer("非法回调", show_alert=True)
        return

    if idx >= len(p.session_names):
        await callback_query.answer("面板已过期，请 🔃 刷新", show_alert=True)
        return

    name = p.session_names[idx]

    if prefix == "sw":
        try:
            session_store.switch_session(name)
            await callback_query.answer(f"切到 [{name}]")
        except KeyError:
            await callback_query.answer("会话不存在", show_alert=True)
        await refresh(bot, p)
        return

    if prefix == "kl":
        if task_manager.kill(name):
            await callback_query.answer(f"已终止 [{name}]")
        else:
            await callback_query.answer("该会话没有任务在跑")
        await refresh(bot, p)
        return

    if prefix == "dt":
        info = session_store.get_running(name)
        if info and info.get("message_id"):
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"📋 [{name}] 详情 ↑",
                    reply_to_message_id=info["message_id"],
                )
                await callback_query.answer()
            except Exception:
                await callback_query.answer("跳转失败（消息可能已删）", show_alert=True)
        else:
            await callback_query.answer("该会话当前无运行任务")
        return

    if prefix == "dr":
        if task_manager.is_running(name):
            await callback_query.answer("任务运行中，不能删除", show_alert=True)
            return
        p.pending_drop.add(idx)
        await callback_query.answer("再点一次 ⚠确认删 才真删")
        await refresh(bot, p)
        return

    if prefix == "dr2":
        p.pending_drop.discard(idx)
        if task_manager.is_running(name):
            await callback_query.answer("任务运行中，不能删除", show_alert=True)
            await refresh(bot, p)
            return
        session_store.drop_session(name)
        clear_session_error(name)
        await callback_query.answer(f"已删除 [{name}]")
        await refresh(bot, p)
        return

    await callback_query.answer("未知动作", show_alert=True)
```

- [ ] **Step 2: 跑全部测试，确认渲染测试仍过**

Run: `pytest tests/ -v`
Expected: progress_emitter 16 + forcereply 6 + panel 9 = 31 passed

- [ ] **Step 3: Commit**

```bash
git add panel.py
git commit -m "feat: panel refresh + broadcast + callback dispatch"
```

---

## Task 8: 改造 task_manager（事件驱动 + panel 广播）

**Files:**
- Modify: `task_manager.py`

- [ ] **Step 1: 替换整个 task_manager.py**

把 `task_manager.py` 整体替换为下面内容（删除时间节流，接入 progress_emitter 和 panel）：

```python
"""
后台任务管理：fire-and-forget 地跑 claude，事件驱动刷新详情消息，完成时主动推送。

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
import panel
from progress_emitter import (
    EmitterState, feed, maybe_heartbeat, EventKind,
)
from path_resolver import resolve
from text_utils import split_chunks

log = logging.getLogger(__name__)

MAX_MSG_LEN = 4096
HARD_LIMIT_SEC = 3600          # 1h 兜底
EVENT_WAIT_TICK_SEC = 30       # 等事件的内层 timeout，过期后跑一次心跳检查


@dataclass
class _TaskState:
    session_name: str
    task_id: str
    chat_id: int
    progress_msg_id: int
    started_at: float
    prompt: str
    tool_count: int = 0
    last_tool: str = ""           # 仅展示用，由 emitter 同步
    last_detail_text: str = ""
    asyncio_task: Optional[asyncio.Task] = field(default=None, repr=False)
    proc: Optional[asyncio.subprocess.Process] = field(default=None, repr=False)
    killed: bool = False


_running: dict[str, _TaskState] = {}


def is_running(session_name: str) -> bool:
    return session_name in _running


def list_running_names() -> list[str]:
    return list(_running.keys())


def get_state(session_name: str) -> Optional[_TaskState]:
    return _running.get(session_name)


def kill(session_name: str) -> bool:
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

    # 新任务开始，清掉旧的错误标记
    panel.clear_session_error(session_name)

    state.asyncio_task = asyncio.create_task(
        _run_task(bot, state, project_input, session_id, on_finish_update_sid),
        name=f"bgtask:{session_name}:{task_id}",
    )

    # 通知所有活面板：本会话刚开跑
    asyncio.create_task(panel.broadcast_change(bot, session_name))


async def _run_task(
    bot: Bot,
    state: _TaskState,
    project_input: str,
    session_id: Optional[str],
    on_finish_update_sid: bool,
) -> None:
    name = state.session_name
    project_path = resolve(project_input)

    emitter = EmitterState(started_at=state.started_at)
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
            tick = min(remaining, EVENT_WAIT_TICK_SEC)
            try:
                event = await asyncio.wait_for(agen.__anext__(), timeout=tick)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                # tick 到了但没事件 —— 检查心跳
                hb = maybe_heartbeat(emitter, now=time.time())
                if hb is not None:
                    await _edit_detail(bot, state, hb)
                    asyncio.create_task(panel.broadcast_change(bot, name))
                continue

            kind = event.get("kind")
            if kind == "tool_use":
                state.tool_count += 1
            if kind == "result":
                final_reply = event.get("reply", "")
                final_sid = event.get("session_id", "")
            elif kind == "error":
                error_msg = event.get("message", "") or error_msg
            elif kind == "done":
                returncode = event.get("returncode", 0)

            sem = feed(emitter, event, now=time.time())
            if sem is not None:
                state.last_tool = emitter.last_tool
                await _edit_detail(bot, state, sem)
                if sem.is_error:
                    panel.mark_session_error(name)
                asyncio.create_task(panel.broadcast_change(bot, name))

    except asyncio.CancelledError:
        state.killed = True
    except Exception as e:
        log.exception("后台任务异常 [%s]", name)
        error_msg = str(e)

    if on_finish_update_sid and final_sid:
        try:
            session_store.update_session_id(name, final_sid)
        except Exception:
            log.exception("update_session_id 失败 [%s]", name)

    elapsed = time.time() - state.started_at
    try:
        diff = await git_helper.get_diff_summary(project_path)
    except Exception:
        diff = ""

    if state.killed:
        header = f"🛑 [{name}] 已终止 ({_fmt_elapsed(elapsed)}, {state.tool_count} 工具)"
        panel.mark_session_error(name)
    elif hit_hard_limit:
        header = f"⏱ [{name}] 达到 1h 硬上限 ({_fmt_elapsed(elapsed)}, {state.tool_count} 工具)"
        panel.mark_session_error(name)
    elif error_msg and not final_reply:
        header = f"❌ [{name}] 失败 ({_fmt_elapsed(elapsed)}, {state.tool_count} 工具)"
        panel.mark_session_error(name)
    elif returncode != 0 and not final_reply:
        header = f"❌ [{name}] 退出码 {returncode} ({_fmt_elapsed(elapsed)}, {state.tool_count} 工具)"
        panel.mark_session_error(name)
    else:
        header = f"✅ [{name}] 完成 ({_fmt_elapsed(elapsed)}, {state.tool_count} 工具)"
        panel.clear_session_error(name)

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

    await _safe_edit(bot, state.chat_id, state.progress_msg_id, header)

    for chunk in split_chunks(full, MAX_MSG_LEN):
        try:
            await bot.send_message(chat_id=state.chat_id, text=chunk)
        except Exception:
            log.exception("发送完成消息失败 [%s]", name)

    _running.pop(name, None)
    try:
        session_store.clear_running(name)
    except Exception:
        log.exception("clear_running 失败 [%s]", name)

    # 终态：通知所有活面板状态已变
    asyncio.create_task(panel.broadcast_change(bot, name))


async def _edit_detail(bot: Bot, state: _TaskState, sem) -> None:
    """根据语义事件刷新详情消息。"""
    elapsed = time.time() - state.started_at
    lines = [
        f"⏳ [{state.session_name}] {sem.text}",
        f"├ ⏱ {_fmt_elapsed(elapsed)}",
        f"└ 🔧 {state.tool_count} 个工具",
    ]
    text = "\n".join(lines)
    if text == state.last_detail_text:
        return
    ok = await _safe_edit(bot, state.chat_id, state.progress_msg_id, text)
    if ok:
        state.last_detail_text = text


async def _safe_edit(bot: Bot, chat_id: int, message_id: int, text: str) -> bool:
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text[:MAX_MSG_LEN])
        return True
    except BadRequest as e:
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
```

- [ ] **Step 2: 跑所有测试，确认仍过**

Run: `pytest tests/ -v`
Expected: 31 passed（task_manager 不在测试范围内，但 panel/emitter/forcereply 仍 OK）

- [ ] **Step 3: 静态检查 import 不破**

Run: `python -c "import task_manager; import panel; import progress_emitter; import forcereply_bridge; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add task_manager.py
git commit -m "refactor(task_manager): event-driven progress + panel broadcast"
```

---

## Task 9: handler.py 集成（/panel · callback · ForceReply · /preview 按钮）

**Files:**
- Modify: `handler.py`

- [ ] **Step 1: 顶部加 import 和共用的 `_create_session` 辅助**

在 `handler.py` 顶部 `import task_manager` 之后追加：

```python
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup,
)
import panel
import forcereply_bridge
```

在 `_truncate` 函数下面新增一个共享的会话创建辅助函数（cmd_new 和 ForceReply 流程都用它）：

```python
async def _create_session(bot, chat_id: int, name: str, project_input: str) -> str:
    """
    在指定 chat 里创建会话；返回结果文案（成功/失败均返回字符串供调用方再发消息）。
    并不真发消息，由调用方决定 reply_text 还是 send_message。
    """
    _, existing = session_store.list_sessions()
    if name in existing:
        if task_manager.is_running(name):
            return f"❌ [{name}] 正在跑任务，先 /kill 再重建"
        return f"❌ 会话 [{name}] 已存在，先 /drop {name} 再重建"

    try:
        project_path = resolve(project_input)
    except ValueError as e:
        return f"❌ {e}"

    await bot.send_message(chat_id=chat_id, text=f"⏳ 正在建立会话 [{name}]...")

    sid = ""
    try:
        async for ev in claude_runner.run_async("你好，新会话开始", project_path):
            kind = ev.get("kind")
            if kind == "result":
                sid = ev.get("session_id", "") or sid
            elif kind == "error":
                msg = ev.get("message", "")
                if msg:
                    return f"❌ 创建会话失败：{msg[:500]}"
    except Exception as e:
        return f"❌ 创建会话失败：{e}"

    if not sid:
        return "❌ 创建会话失败：未获得 session_id"
    session_store.new_session(name, project_input, sid)
    return f"✅ 会话 [{name}] 已创建\n项目：{project_input}\n当前活跃会话：{name}"
```

- [ ] **Step 2: 让 `cmd_new` 改用新辅助**

替换 `cmd_new` 函数体为：

```python
async def cmd_new(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    args = ctx.args
    if len(args) < 2:
        await _send(update, "用法：/new <会话名> <项目路径>\n例：/new refactor shulex-gpt")
        return
    name, project_input = args[0], "/".join(args[1:])
    result = await _create_session(ctx.bot, update.effective_chat.id, name, project_input)
    await _send(update, result)
```

- [ ] **Step 3: 加 `/panel` 命令**

在 `cmd_help` 函数之后加：

```python
async def cmd_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    # 先发占位消息 → 注册 PanelRecord（拿到真实 msg_id 后才有可用 record） → refresh
    # 这样 render 才会在已注册的 record 上填 session_names，后续 callback 索引才对得上
    msg = await update.message.reply_text("🎛 面板初始化中…")
    rec = panel.register_panel(msg.chat_id, msg.message_id)
    await panel.refresh(ctx.bot, rec)
```

- [ ] **Step 4: 替换 `_start_preview`，给预览完成消息加按钮**

预览完成的【确认/取消】按钮在 `cmd_preview` 走完后挂在**预览结果消息**上。最简单的做法是在 `task_manager.start` 完成后由 handler 挂，但 task_manager 已经接管了消息生命周期。改成：在 `cmd_preview` 调用 `_start_preview` 时，**额外加一条带按钮的提示**作为入口。

直接修改 `_start_preview`：

```python
async def _start_preview(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    name: str,
    sess: dict,
) -> None:
    preview_prompt = (
        f"请先列出你打算做什么修改（不要实际修改任何文件），然后等待确认。需求：{prompt}"
    )
    pending_id = f"p-{int(time.time())}"
    session_store.set_pending_confirm(prompt, sess["project"], sess["session_id"])
    await _dispatch_bg(
        update, ctx, preview_prompt, sess["project"], sess["session_id"], name,
        header=f"⏳ [{name}] 预览生成中...（完成后请用下面按钮）",
    )
    # 紧跟一条带按钮的提示，按钮 callback_data 用 pending_id 关联
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ 确认执行", callback_data=f"cf:{pending_id}"),
        InlineKeyboardButton("❌ 取消", callback_data=f"cn:{pending_id}"),
    ]])
    await update.message.reply_text(
        f"⏸ [{name}] 预览待确认（完成后点按钮）",
        reply_markup=kb,
    )
```

- [ ] **Step 5: 新增 callback 入口和 ForceReply 处理**

在 `handler.py` 末尾加：

```python
async def _handle_preview_callback(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE, data: str,
) -> None:
    cq = update.callback_query
    if data.startswith("cn:"):
        session_store.clear_pending_confirm()
        await cq.answer("已取消")
        try:
            await cq.edit_message_text("❌ 已取消预览任务")
        except Exception:
            pass
        return
    # cf:
    pending = session_store.get_pending_confirm()
    if not pending:
        await cq.answer("没有待确认任务", show_alert=True)
        return
    name, _ = session_store.get_current()
    if not name:
        await cq.answer("无活跃会话", show_alert=True)
        return
    if task_manager.is_running(name):
        await cq.answer("当前会话有任务在跑", show_alert=True)
        return
    session_store.clear_pending_confirm()
    latest_sid = session_store.list_sessions()[1].get(name, {}).get("session_id")
    await cq.answer("开始执行")
    try:
        await cq.edit_message_text(f"✅ 已确认 [{name}]")
    except Exception:
        pass
    msg = await ctx.bot.send_message(
        chat_id=update.effective_chat.id, text=f"⏳ [{name}] 执行确认任务...",
    )
    await task_manager.start(
        bot=ctx.bot,
        session_name=name,
        prompt=pending["prompt"],
        project_input=pending["project"],
        session_id=latest_sid,
        chat_id=msg.chat_id,
        initial_msg_id=msg.message_id,
    )


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return
    cq = update.callback_query
    data = cq.data or ""
    if data.startswith("cf:") or data.startswith("cn:"):
        await _handle_preview_callback(update, ctx, data)
        return
    await panel.dispatch_callback(ctx.bot, cq)
```

- [ ] **Step 6: 修改 on_message 优先处理 ForceReply**

把 `on_message` 替换为：

```python
async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update): return

    # 1. 若是对 ForceReply 提示的回复，先尝试消费
    reply_to = getattr(update.message, "reply_to_message", None)
    if reply_to is not None:
        pending = forcereply_bridge.consume(
            chat_id=update.effective_chat.id,
            reply_to_msg_id=reply_to.message_id,
        )
        if pending is not None:
            await _consume_forcereply(update, ctx, pending)
            return

    # 2. 普通文本，走原逻辑
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


async def _consume_forcereply(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
    pending: forcereply_bridge.Pending,
) -> None:
    text = (update.message.text or "").strip()
    if pending.kind == forcereply_bridge.PendingKind.NEW_SESSION:
        parts = text.split()
        if len(parts) < 2:
            await _send(update, "❌ 格式不对，需要：<会话名> <项目路径>")
            return
        name = parts[0]
        project_input = "/".join(parts[1:])
        result = await _create_session(ctx.bot, update.effective_chat.id, name, project_input)
        await _send(update, result)
        # 通知所有活面板：会话列表变了
        await panel.broadcast_change(ctx.bot, name)
```

- [ ] **Step 7: 跑测试**

Run: `pytest tests/ -v`
Expected: 31 passed（handler.py 未补单测，全部通过 import OK 即可）

- [ ] **Step 8: 静态 import 检查**

Run: `python -c "import handler; print('ok')"`
Expected: `ok`

- [ ] **Step 9: Commit**

```bash
git add handler.py
git commit -m "feat(handler): /panel cmd + callback router + ForceReply pipeline"
```

---

## Task 10: bot.py 注册新命令和回调

**Files:**
- Modify: `bot.py`

- [ ] **Step 1: 加 import**

把 `bot.py` 中的：

```python
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters
)
```

替换为：

```python
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)
```

- [ ] **Step 2: 在 COMMANDS 列表里加 /panel**

把 COMMANDS 列表替换为：

```python
COMMANDS = [
    BotCommand("help",    "显示完整帮助"),
    BotCommand("panel",   "打开会话面板（按钮操作）"),
    BotCommand("new",     "新建会话  /new <名称> <项目路径>"),
    BotCommand("switch",  "切换会话  /switch <名称>"),
    BotCommand("list",    "列出所有会话"),
    BotCommand("drop",    "删除会话  /drop <名称>"),
    BotCommand("status",  "查看当前会话状态"),
    BotCommand("tasks",   "查看全部会话运行状态"),
    BotCommand("kill",    "终止当前(或指定)会话的任务"),
    BotCommand("run",     "执行任务  /run <需求描述>"),
    BotCommand("preview", "预览模式  /preview <需求描述>"),
    BotCommand("confirm", "确认预览并执行"),
    BotCommand("cancel",  "取消预览"),
    BotCommand("mode",    "切换模式  /mode auto|preview"),
]
```

- [ ] **Step 3: 在 main 函数中注册新 handler**

在现有 `app.add_handler(CommandHandler("kill", h.cmd_kill))` 之后加：

```python
    app.add_handler(CommandHandler("panel",  h.cmd_panel))
```

在 `app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, h.on_message))` 之后加：

```python
    app.add_handler(CallbackQueryHandler(h.on_callback))
```

- [ ] **Step 4: 静态 import 检查**

Run: `python -c "import bot; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add bot.py
git commit -m "feat(bot): register /panel command and CallbackQueryHandler"
```

---

## Task 11: 更新 /help 文案与 README

**Files:**
- Modify: `handler.py` (HELP_TEXT 常量)
- Modify: `README.md`

- [ ] **Step 1: 改 HELP_TEXT**

把 `handler.py` 中的 `HELP_TEXT = ...` 整段替换为：

```python
HELP_TEXT = """🤖 Telegram Claude Bot

━━ 推荐用法 ━━
/panel               打开会话面板（推荐，按钮操作）

━━ 会话管理 ━━
/new <名称> <项目>   新建会话，例：/new refactor shulex-gpt
/switch <名称>       切换当前会话
/list                列出所有会话（建议改用 /panel）
/drop <名称>         删除会话（不能删正在跑的）
/status              查看当前会话状态
/tasks               查看全部会话运行状态（建议改用 /panel）

━━ 任务执行 ━━
/run <需求>          直接执行
/preview <需求>      预览模式：先列计划，按钮 ✅ 确认 / ❌ 取消
/confirm             确认执行待确认任务
/cancel              取消待确认任务
/kill [名称]         终止当前（或指定）会话的任务
/mode auto|preview   切换默认模式（直接发文本走这个模式）

━━ 快捷 ━━
直接发文本 = /run 或 /preview（看模式）
回复 ForceReply 提示 = 完成对应按钮动作（如新建会话）

━━ 备注 ━━
• 项目路径支持 shulex 自动补前缀
• 单会话一次只能跑一个任务，多会话可并行
• 进度推送改为事件驱动：工具切换/首次写代码/首次测试/首次 git/出错时刷新；最长 2 分钟兜底心跳
• 硬上限 1h"""
```

- [ ] **Step 2: 更新 README.md 的命令表和"工作原理"段**

把 `README.md` 中 `## 命令` 那段代码块替换为：

```
/help               显示完整帮助
/panel              打开会话面板（推荐）
/new <名> <项目>    新建会话，例：/new refactor shulex-gpt
/switch <名>        切换会话
/list               列出所有会话
/drop <名>          删除会话（不能删正在跑的）
/status             当前会话状态
/tasks              全部任务运行状态
/kill [名]          终止当前（或指定）会话的任务
/run <需求>         直接执行
/preview <需求>     预览模式：先列计划
/confirm            确认执行预览过的任务
/cancel             取消预览
/mode auto|preview  默认模式（直接发文本走这个模式）
```

并在 `## 特性` 列表里：
- 把 `**后台执行 + 进度推送**：长任务（默认 1 小时硬上限）丢到后台跑，前 5 分钟每 4 秒刷新进度，之后每 2 分钟刷新一次，完成后主动推送结果` 改成 `**后台执行 + 事件驱动进度**：长任务（默认 1 小时硬上限）丢到后台跑，工具切换/首次写代码/首次测试/首次 git/报错时推送，最长 2 分钟兜底心跳`
- 在末尾加一行 `- **会话面板**：/panel 召出一条带按钮的面板，集成切换/终止/详情/删除/新建，单条消息看全局`

- [ ] **Step 3: Commit**

```bash
git add handler.py README.md
git commit -m "docs: refresh /help and README for panel + event-driven progress"
```

---

## Task 12: 手测 smoke + 收尾

**Files:** 无代码改动；本任务只跑流程

- [ ] **Step 1: 跑全部单测**

Run: `pytest tests/ -v`
Expected: 31 passed

- [ ] **Step 2: 启 bot**

Run: `python bot.py`
Expected: 输出 `Bot 启动，开始长轮询...` 无异常退出

- [ ] **Step 3: Telegram 端手测清单**

在 Telegram 客户端按下面顺序操作并核对预期：

- [ ] 发 `/help` —— 显示新版帮助（提到 `/panel`、事件驱动进度）
- [ ] 发 `/panel` —— 出现带按钮的面板，列出现有会话或"暂无会话"
- [ ] 点【➕ 新建】 —— bot 发 ForceReply 提示，回复 `tmp shulex-gpt` 后正常建会话，并自动刷新面板
- [ ] 在新会话发 `/run 列一下当前目录文件` —— 收到详情消息，应只在工具切换 / 首次执行时刷新，不再 4 秒一次
- [ ] 同时面板那一行变 🟢，工具名跟随刷新
- [ ] 点面板上该行 💀 —— 任务被终止，行变 🟡
- [ ] 点 🗑 —— 提示"再点一次"；再点 ⚠确认删 —— 会话被删除并自动刷新
- [ ] 发 `/preview 在 README 加一行` —— 跑完后收到带【✅确认 / ❌取消】按钮的消息；点确认正常执行
- [ ] 关闭面板【❌】—— 面板消息变成"🎛 面板已关闭"
- [ ] 老命令 `/list` `/tasks` `/new tmp2 shulex-gpt` `/run hello` `/kill` —— 全部仍能用

- [ ] **Step 4: 若有手测发现的小问题**

逐条以单独 commit 修复，不在本任务内打补丁。

- [ ] **Step 5: 最终 commit（如有遗留小改动）**

```bash
git status
git add -p   # 谨慎挑选
git commit -m "fix: smoke-test follow-ups"
```

---

## 验收清单（对应 spec §10 完成标准）

- [ ] `/panel` 召出符合 §2.1 样例的面板
- [ ] 行按钮覆盖切换 / 终止 / 详情跳转 / 删除（带二次确认）；全局按钮 ➕ ForceReply 新建 / 🔃 刷新 / ❌ 关闭
- [ ] `/preview` 输出消息带【✅ 确认 / ❌ 取消】按钮
- [ ] 5 分钟任务期间进度按 §3.2 触发，不再 4 秒一次无信息刷新
- [ ] 会话状态变化触发面板 5s 内自动刷新
- [ ] `pytest tests/` 全绿（≥31 passed）
- [ ] 老命令端到端仍能跑通
