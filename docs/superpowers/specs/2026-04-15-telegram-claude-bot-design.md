# Telegram Claude Bot 设计文档

**日期：** 2026-04-15  
**状态：** 已批准  

---

## 概述

通过 Telegram Bot 拉起本地电脑的 Claude CLI，实现远程自动写代码与多轮对话。Bot 本质上是一个**消息转发层**：将 Telegram 消息转发给本地 Claude CLI，把 Claude 的回复送回 Telegram。对话上下文完全由 Claude CLI 自身的会话机制管理，支持多个命名会话并行，随时切换。

**约束：**
- 仅限单用户（user_id 白名单）
- 本地运行，无需公网 IP 或云服务器
- 依赖本地已安装的 `claude` CLI

---

## 架构

```
手机 Telegram
     │  发送消息
     ▼
Telegram Bot API（长轮询）
     │
     ▼
本地 Python Bot 服务
     ├── 身份验证：校验 user_id 白名单
     ├── 命令解析：路由到会话管理 or 任务执行
     ├── 调用 claude CLI（subprocess，--resume <session_id>）
     └── 结果回复：对话回复 or 摘要 + git diff
```

---

## 目录结构

```
E:/workspace/telegram-claude-bot/
├── bot.py              # 主入口，Telegram 长轮询
├── handler.py          # 命令解析与路由
├── claude_runner.py    # 调用 claude CLI，捕获输出
├── git_helper.py       # git diff 格式化
├── session_store.py    # 命名会话持久化（JSON）
├── config.py           # 白名单、workspace 路径配置
├── sessions.json       # 会话名 → claude session_id 映射（运行时生成）
├── requirements.txt
└── .env                # BOT_TOKEN, ALLOWED_USER_ID（不提交 git）
```

---

## 会话模型

Bot 维护一张**命名会话表**，持久化到 `sessions.json`：

```json
{
  "current": "refactor",
  "sessions": {
    "refactor":  { "session_id": "abc123", "project": "shulex-gpt",       "created": "2026-04-15T10:00:00" },
    "debug":     { "session_id": "def456", "project": "qa-bot",           "created": "2026-04-15T11:00:00" },
    "feature-x": { "session_id": "ghi789", "project": "shulex-gpt-agents","created": "2026-04-15T12:00:00" }
  }
}
```

每次调用 Claude CLI 时，使用当前会话的 `session_id` 通过 `--resume` 恢复上下文，实现真正的多轮对话。

---

## 消息格式

### 会话管理命令

```
/new <name> <project_path>    # 新建命名会话并切换到它
/new refactor shulex-gpt
/new debug qa-bot

/switch <name>                # 切换当前会话
/switch debug

/list                         # 列出所有会话及当前活跃会话
/drop <name>                  # 删除指定会话

/status                       # 查看当前会话、项目、模式
```

### 任务命令（在当前会话下执行）

```
/run <需求描述>               # 在当前会话的项目下执行任务
/run 在 AgentService 里新增根据 ID 查询的方法

/preview <需求描述>           # 预览模式，先看计划再执行
/preview 重构 OrderService 分页逻辑

/mode auto                    # 切换默认为全自动模式
/mode preview                 # 切换默认为预览模式

/confirm                      # 预览后确认执行
/cancel                       # 预览后取消
```

### 自然语言式（快捷方式）

```
# 在当前会话里直接对话或发任务（无需命令前缀）
帮我分析一下 AgentService 的结构
继续刚才的思路，把 create 方法抽出来
```

无前缀的普通消息直接转发给当前活跃会话的 Claude，Bot 只是中继。

---

## Claude CLI 调用

```python
# claude_runner.py

def run(prompt: str, project_path: str, session_id: str | None = None) -> tuple[str, str]:
    """
    返回 (stdout, new_session_id)
    首次调用 session_id=None，后续用返回的 new_session_id --resume
    """
    cmd = ["claude", "--print", "-p", prompt]
    if session_id:
        cmd += ["--resume", session_id]

    result = subprocess.run(
        cmd,
        cwd=project_path,
        capture_output=True,
        text=True,
        timeout=300      # 5 分钟超时
    )
    # 从输出或 claude 本地存储中获取 session_id
    new_session_id = extract_session_id(result)
    return result.stdout, new_session_id
```

> **说明：** `--resume <session_id>` 恢复指定会话；首次建立会话后记录返回的 session_id 供后续使用。

### 预览模式

```python
preview_prompt = (
    f"请先列出你打算做什么修改（不要实际修改文件），"
    f"然后等待确认。需求：{user_prompt}"
)
```

用户 `/confirm` 后，以原始 prompt 在同一会话中继续执行真正修改。

---

## 项目路径解析

workspace 根目录为 `E:/workspace/`，路径拼接规则：

| 输入 | 解析路径 |
|------|---------|
| `qa-bot` | `E:/workspace/qa-bot` |
| `shulex-gpt` | `E:/workspace/shulex/shulex-gpt` |
| `shulex-gpt/shulex-gpt-agents` | `E:/workspace/shulex/shulex-gpt/shulex-gpt-agents` |
| `shulex-cloud/shulex-cloud-platform/plg-commerce-service` | `E:/workspace/shulex/shulex-cloud/shulex-cloud-platform/plg-commerce-service` |

`shulex` 下的项目自动补充 `shulex/` 前缀（通过扫描 workspace 目录动态匹配，不维护手动映射表）。路径不存在时直接报错提示。

---

## 结果回复格式

### 对话回复（纯对话消息）

```
Claude 的回复内容直接原文转发，无额外包装。
```

### 任务完成回复

```
✅ 执行完成 | shulex-gpt/shulex-gpt-agents [refactor]

📋 摘要：
新增了 AgentFactory 类，包含 create() 工厂方法，支持按类型动态实例化 Agent。

📁 变更文件：
  M  src/main/java/.../AgentService.java
  A  src/main/java/.../AgentFactory.java

📝 Git Diff（关键变更）：
+public class AgentFactory {
+    public Agent create(String type) { ... }
+}
```

- 消息超过 Telegram 4096 字符限制时自动分段发送
- git diff 超过 200 行时截断，附提示"完整 diff 请查看本地"

---

## 异常处理

| 场景 | 回复 |
|------|------|
| 非白名单用户 | 静默忽略，不回复 |
| 无活跃会话时发消息 | ❌ 没有活跃会话，请先用 /new 创建 |
| 项目路径不存在 | ❌ 找不到项目 `xxx`，请检查路径 |
| Claude 执行超时（5min） | ⏱ 执行超时，请缩小任务范围 |
| Claude 进程报错退出 | ❌ 执行失败 + stderr 内容 |
| 预览确认时无待确认任务 | ❌ 没有待确认的任务 |

---

## 配置

### `.env`

```env
BOT_TOKEN=your_telegram_bot_token
ALLOWED_USER_ID=your_telegram_user_id
WORKSPACE_ROOT=E:/workspace
DEFAULT_MODE=auto
```

### 依赖 `requirements.txt`

```
python-telegram-bot>=20.0
python-dotenv
```

---

## 部署

### 运行

```bash
pip install -r requirements.txt
python bot.py
```

### 开机自启（Windows 任务计划程序）

- 触发器：系统启动时
- 操作：`pythonw.exe E:/workspace/telegram-claude-bot/bot.py`
- 运行方式：后台无窗口，最高权限

---

## 不在范围内

- 多用户权限管理
- 云端中转或消息持久化
- Web UI 或其他触发渠道
- Claude 执行结果自动 commit/push
