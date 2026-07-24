---
name: Saving-tokens-skill
description: |
  诊断并优化 AI 智能体的 token 消耗。诊断并优化 AI 智能体的 token 消耗。
  Use when: token诊断、上下文优化、skill配置分析、prompt精简。
  支持 VS Code Copilot 和 Workbuddy 平台。
allowed-tools: Read, Write, Bash, Grep, Glob
---

# Saving Tokens Skill

诊断智能体的 token 浪费问题，生成优化报告。支持 VS Code Copilot 和 Workbuddy（腾讯 AI 助手）。

## 快速开始

```bash
# VS Code Copilot — 静态分析
python scripts/scanner.py <项目目录> -o scan_result.json

# Workbuddy — 静态分析
python scripts/scanner.py <项目目录> --platform workbuddy -o scan_result.json

# 生成 Markdown 诊断报告
python scripts/reporter.py scan_result.json -o token_report.md

# 一步到位
python scripts/scanner.py . -o scan_result.json && python scripts/reporter.py scan_result.json -o token_report.md
```

## 工作流程

### Step 1: 静态扫描
运行 [scanner.py](./scripts/scanner.py) 扫描项目配置，检测已知反模式：
- `applyTo: "**"` 全量加载
- Monolithic SKILL.md（>500 行）
- 重复的 instructions 文件
- 模糊的 description 字段
- tools 配置冗余（Swiss-army agent）
- 缺少渐进加载拆分

详见 [反模式目录](./references/anti-patterns.md)。

### Step 2: 生成报告
运行 [reporter.py](./scripts/reporter.py) 将扫描结果转为 Markdown 报告，按严重等级排序，含修复建议和预估节省量。

### Step 3: 深度分析（运行时数据）
结合 session store 运行时数据，检测实际 token 消耗中的浪费：

**Step 3a: 收集 Session 数据（由 Agent 执行）**
使用 `copilot_sessionStoreSql` 工具查询 session 数据。根据后端类型运行以下查询：

*Cloud 后端 (DuckDB) — 有 token 级别数据:*
```sql
-- 最近的 VS Code Chat sessions
SELECT id, agent_name, created_at, updated_at
FROM sessions
WHERE agent_name = 'VS Code Chat'
  AND updated_at >= now() - INTERVAL '7 day'
ORDER BY updated_at DESC
LIMIT 20;

-- Token 消耗详情
SELECT e.session_id, e.usage_input_tokens, e.usage_output_tokens, e.usage_model
FROM events e
JOIN sessions s ON s.id = e.session_id
WHERE s.agent_name = 'VS Code Chat'
  AND e.type = 'assistant.usage'
  AND s.updated_at >= now() - INTERVAL '7 day';

-- Session checkpoints (compaction history)
SELECT session_id, checkpoint_number, created_at
FROM checkpoints
ORDER BY created_at DESC
LIMIT 50;

-- Session files (repeated reads)
SELECT session_id, file_path
FROM session_files
ORDER BY session_id;

-- Turns (user message size)
SELECT session_id, user_message
FROM turns;
```

*Local 后端 (SQLite) — 无 token 数据:*
```sql
-- 最近的 GitHub Copilot Chat sessions
SELECT id, agent_name, created_at, updated_at
FROM sessions
WHERE agent_name = 'GitHub Copilot Chat'
  AND updated_at >= datetime('now', '-7 day')
ORDER BY updated_at DESC
LIMIT 20;

-- Turns
SELECT session_id, user_message FROM turns;

-- Checkpoints
SELECT session_id, checkpoint_number, created_at FROM checkpoints;

-- Session files
SELECT session_id, file_path FROM session_files;
```

将查询结果组织为 JSON，保存为 `session_data.json`。

**Step 3b: 运行分析**
```bash
python scripts/session_analyzer.py session_data.json -o runtime_result.json --static-result scan_result.json --pretty
```

**Step 3c: 生成综合报告**
将静态 + 运行时结果合并生成报告：
```bash
python scripts/reporter.py runtime_result.json -o deep_report.md
```

检测的运行时反模式：
- RP-01: 长会话未使用 compaction
- RP-02: Compaction 触发过晚
- RP-03: 输入/输出 token 比例失衡
- RP-04: 同一文件被重复读取
- RP-05: 用户消息过长（应使用文件引用）
- RP-06: Token 消耗异常的会话

### Step 4: 按清单复查
参考 [优化检查清单](./references/checklist.md) 手动复查，确保无遗漏。

## 触发场景

| 用户意图 | 典型问法 |
|----------|---------|
| 诊断 token 消耗 | "帮我分析 token 消耗"、"检查上下文浪费" |
| 优化配置 | "怎么减少 token 使用"、"优化 skill 配置" |
| 生成报告 | "生成 token 使用报告" |
| 检查单个文件 | "检查这个 SKILL.md 的 token 效率" |

## 平台支持

| 平台 | 静态分析 | 运行时分析 | 参数 |
|------|:---:|:---:|------|
| VS Code Copilot | ✅ | ✅ | 默认 |
| Workbuddy（腾讯） | ✅ | 🔜 | `--platform workbuddy` |

## 注意事项

- 静态分析估算基于文件大小和反模式计数，非精确 token 数
- 运行时分析依赖 session store 数据，需在 Copilot 环境中触发
- 修复建议需人工审核，`--fix` 模式仅处理安全操作
