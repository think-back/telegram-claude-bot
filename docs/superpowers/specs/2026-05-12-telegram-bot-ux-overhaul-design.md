# Telegram Claude Bot · 体验改造 (UX Overhaul) 设计

- 日期: 2026-05-12
- 关联代码: `E:\workspace\telegram-claude-bot`
- 前置 spec: `docs/superpowers/specs/2026-04-15-telegram-claude-bot-design.md`
- 范围: 交互层重构，不动 `claude_runner` 与 `session_store` 的对外语义

## 1. 背景与目标

当前 bot 功能已覆盖多会话、预览/确认、后台任务、崩溃恢复。痛点集中在**手机端交互效率**：

- 所有操作靠 `/命令`，敲字累
- 进度推送按时间节流，关键事件和噪音事件等权重，长任务"看不到节点"
- 看一眼"哪几个会话在跑什么"要在 `/list`、`/status`、`/tasks` 三条消息之间跳

本次改造解决的三件事：

1. **B1 命令操作笨重** → 把核心操作做成 Inline 按钮
2. **B2 进度推送不够聪明** → 时间节流改成事件驱动 + 兜底心跳
3. **B5 多会话切换费力** → 引入合并面板替代散装命令

老命令全部保留，按钮只是新入口。

## 2. 核心抽象：会话面板

**按需召唤模式**：用户发 `/panel` 召唤一条带按钮的会话面板消息。面板**不 pin**、不持久化，靠 Telegram 自然消息流存在。面板生命周期内会随任务状态变化自动编辑刷新；超过 10 分钟无操作则停止接收广播刷新（避免泄漏 + 限流）。

### 2.1 面板渲染样例

```
🎛 会话面板  (2026-05-12 10:23)
─────────────────
🟢 refactor    · shulex-gpt · Edit 中 · 12m
   [🔄] [💀] [📋] [🗑]
⚪ docs        · my-docs    · idle
   [🔄] [💀] [📋] [🗑]
🟡 fix-bug     · shulex-api · 已结束·待回收
   [🔄] [💀] [📋] [🗑]
─────────────────
[➕ 新建] [🔃 刷新] [❌ 关闭]
```

状态指示灯：
- 🟢 运行中且无错误
- 🟡 运行中但出现过 error 事件 / 异常终止 / 待回收 (running 标记被清理后的过渡态)
- ⚪ idle

每行 4 个按钮含义：
- 🔄 切换为当前会话（同 `/switch`）
- 💀 终止任务（仅运行中触发，否则 alert 提示）
- 📋 跳转到该会话最近一条详情消息（用 message_id 做 reply）
- 🗑 删除会话（仅 idle，二次确认）

底部 3 个全局按钮：➕ 触发 ForceReply 要文字输入；🔃 立即刷新；❌ 编辑成 "面板已关闭"。

### 2.2 callback_data 编码

Telegram callback_data 上限 64 字节，会话名长度不可控（含中文按 UTF-8 3 字节/字）。**不直接用会话名**，而是面板渲染时建立一张 `panel_msg_id → [session_name, ...]` 的索引表，callback 用序号：

| code | 含义 |
|------|------|
| `sw:<idx>` | switch to session at index |
| `kl:<idx>` | kill task |
| `dt:<idx>` | detail jump |
| `dr:<idx>` | drop session (idle only, 二次确认) |
| `dr2:<idx>` | drop session 二次确认 |
| `new` | 新建会话 (触发 ForceReply) |
| `rf` | refresh 当前面板 |
| `cls` | close 当前面板 |
| `cf:<task_id>` | preview confirm |
| `cn:<task_id>` | preview cancel |

索引表随面板 TTL 一起回收。

### 2.3 全局按钮与文本输入桥 (ForceReply)

`➕ 新建` 和未来可能补的 "在该会话开新任务" 都需要文字输入。用 Telegram 自带的 `ForceReply`：bot 发一条提示消息附 `force_reply=True`，用户的下一条 reply 被 `MessageHandler` 抓到。

**状态映射**：`forcereply_bridge` 维护 `{(chat_id, prompt_msg_id) → PendingAction}`：
- `PendingAction.NEW_SESSION` —— 解析为 `/new <name> <project>` 语义
- 未来扩展：`PendingAction.RUN_IN(session)` / `PendingAction.PREVIEW_IN(session)`

**TTL**：每条 pending 5 分钟，过期自动清除；用户没 reply 而是发普通消息，按现有 `on_message` 流程走。

## 3. 进度事件模型 (B2)

### 3.1 模块划分

新增 `progress_emitter.py`：消费 `claude_runner` 已有的 stream-json 事件，吐出"语义事件" Stream。`task_manager` 订阅语义事件来决定**是否编辑详情消息** 与 **是否广播到活面板**。

`claude_runner` 本身不动 —— 它继续吐原始事件，新模块在 `task_manager` 那一层挂上。

### 3.2 语义事件表

| 事件类型 | 触发条件 | 详情消息文案模板 |
|---------|---------|----------------|
| `tool_switch` | 本次 tool name ≠ 上次 tool name | `🛠 切到 {tool}: {target}` |
| `first_write` | 本次任务首次出现 Write/Edit/MultiEdit | `✍️ 开始改代码 (首个文件: {path})` |
| `first_test` | 首次 Bash 命令含 `pytest` / `npm test` / `go test` / `mvn test` / `cargo test` | `🧪 跑测试中` |
| `first_git` | 首次 Bash 命令以 `git ` 开头 | `📦 git 操作: {cmd_summary}` |
| `error` | tool_result `is_error=true` 或 stream 异常 | `❌ 工具出错: {snippet}` |
| `heartbeat` | 上面都没触发且距上次编辑 ≥ 120s | `⏳ 仍在运行 · 已 {minutes} 分` |
| `terminal` | `completed` / `failed` / `killed` | 编辑成最终摘要 + 单独发 git diff |

`first_*` 是 **per-task 一次性**，避免反复触发；`tool_switch` 同 tool 反复进出不算切换（同一工具 push 阶段不重复触发，要换到别的工具再回来才算）。

### 3.3 与面板的关系

每个会话在面板里显示**最近一次 `tool_switch` 后的 tool 名 + 任务耗时**。`error` 事件让那一行变 🟡。`terminal` 让那一行变 ⚪ 或 🟡。

详情消息保持现有 "header + 最近文本" 结构，但 header 改由语义事件决定，不再每 4 秒刷一次。

## 4. 改造清单

| 文件 | 状态 | 改动 |
|------|------|------|
| `panel.py` | **新增** | 面板渲染、callback 路由、活面板登记表、按 panel_msg_id 索引会话 |
| `progress_emitter.py` | **新增** | 把 stream-json 事件转语义事件；纯函数风格，便于单测 |
| `forcereply_bridge.py` | **新增** | ForceReply pending 状态机 + TTL |
| `task_manager.py` | **改** | 取消时间节流；订阅 `progress_emitter`；运行状态变更回调 `panel.broadcast_change` |
| `handler.py` | **改** | 新增 `/panel` 命令；`/preview` 完成后挂【✅ 确认 / ❌ 取消】按钮；新增 `on_callback_query`；老命令保留不动 |
| `bot.py` | **改** | 注册 `CallbackQueryHandler` + `/panel` |
| `session_store.py` | 不变 | — |
| `claude_runner.py` | 不变 | — |
| `path_resolver.py` / `git_helper.py` / `text_utils.py` / `config.py` | 不变 | — |
| `tests/test_progress_emitter.py` | **新增** | 喂模拟事件序列，断言语义事件触发时点 |
| `tests/test_panel.py` | **新增** | 面板渲染快照、callback_data 解码、不可用按钮提示 |
| `requirements.txt` | 改 | 加 `pytest`、`pytest-asyncio` |

## 5. 数据流

```
[用户点按钮]
   │
   ▼
CallbackQueryHandler
   │   (callback_data 解码)
   ▼
panel.dispatch(msg_id, code, idx)
   │
   ├─ session/task 操作 → session_store / task_manager
   │
   └─ panel.refresh(msg_id)
        │
        ▼
   bot.edit_message_text(...)


[用户 reply ForceReply]
   │
   ▼
MessageHandler (filters.REPLY)
   │
   ▼
forcereply_bridge.consume(reply_to_msg_id)
   │  匹配到 PendingAction.NEW_SESSION 等
   ▼
等价于走 /new 等命令的逻辑


[claude_runner stream 事件]
   │
   ▼
progress_emitter.feed(raw_event) → 0/1 个语义事件
   │
   ▼
task_manager 处理语义事件:
   ├─ terminal → 编辑详情消息为最终摘要 + 发 git diff
   ├─ error/first_*/tool_switch → 编辑详情消息 header
   ├─ heartbeat → 编辑详情消息 (兜底)
   └─ 任意事件 → panel.broadcast_change(session)
                    │
                    ▼ (50ms debounce 合并连发)
                 panel.refresh(每个活面板 msg_id)
```

## 6. 错误处理与边界

| 场景 | 处理 |
|------|------|
| Telegram edit 限流 (429 Flood) | `panel.broadcast_change` 内 try/except；退避 1s 重试 ≤3 次；超阈值放弃，等下一次事件 |
| 面板消息被删 / 太老 / chat 不存在 | callback 时 BadRequest 捕获，`answer_callback_query("面板已过期，请重发 /panel")`，并把这个 panel_msg_id 从活面板表移除 |
| ForceReply 用户没 reply，直接发别的文本 | TTL 5 分钟，过期 GC；正常文本走原 `on_message` |
| 同会话多个面板同时打开 | 都登记，事件都广播；PTB 内置 rate limiter + 我们的 1s 退避兜底 |
| Bot 重启遗留 stale running | 复用现有 `session_store.clear_all_running()`，首次 `/panel` 时 stale 显示为 🟡 |
| 按钮触发的状态变化与任务终态竞争 (kill 时刚好任务自然结束) | callback 内统一捕获，结果都触发一次 `panel.refresh` 强同步真实状态 |
| 会话名含 emoji 或特殊字符 | 用面板内序号 (`sw:0` 形式) 规避 callback_data 字节限制 |

## 7. 测试

| 测试文件 | 范围 |
|---------|------|
| `tests/test_progress_emitter.py` | 喂多组模拟 stream-json 序列：纯 Read / Read→Edit→Bash / 含 error / 含 pytest / 兜底 heartbeat 触发时点。是这次改造里**逻辑密度最高**的一块，必测 |
| `tests/test_panel.py` | 面板渲染：0 会话 / 1 idle / N 混合状态；callback_data 编解码；不可用按钮的 alert 文案 |

`task_manager` / `handler` 的端到端路径由手测覆盖（个人项目，性价比够了）。CI 暂不引入。

## 8. 非目标 (Out of Scope)

- **不**改 `claude_runner` 的对外接口和 stream-json 解析逻辑
- **不**改 `session_store` 持久化结构（仅新增/读取已有字段）
- **不**碰白名单/鉴权/`path_resolver`/`git_helper`
- **不**加 i18n / 多用户支持 / 远程触发
- **不** pin 面板、**不**搞常驻 dashboard（已评估过限流和滚动问题，方案 ② 胜出）

## 9. 兼容性

所有现有命令 (`/new` `/switch` `/list` `/drop` `/status` `/tasks` `/kill` `/run` `/preview` `/confirm` `/cancel` `/mode`) 保留语义不动。`/list` 和 `/tasks` 在 `/help` 文案里改成"建议改用 /panel"，但本身仍可用。

## 10. 完成标准

- `/panel` 召出符合 2.1 样例的面板
- 面板按钮覆盖切换 / 终止 / 详情跳转 / 删除（带二次确认）/ 新建（ForceReply）/ 刷新 / 关闭
- `/preview` 输出消息带【✅ 确认 / ❌ 取消】按钮
- 一个 5 分钟的任务运行期间：进度事件按 §3.2 的表准确触发，**不再有 4 秒一次的"无信息刷新"**
- 任意会话状态变化触发面板 5s 内自动刷新（无需手动 🔃）
- `pytest tests/` 全绿
- 老命令端到端仍能跑通 (`/new` `/run` `/kill` `/drop` 走一遍)
