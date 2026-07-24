# Workbuddy ↔ Copilot 概念映射

Workbuddy（腾讯 AI 助手）与 VS Code Copilot 使用**相同的 SKILL.md 格式**，差异很小。

---

## 文件路径对比

| 概念 | Copilot 路径 | Workbuddy 路径 |
|------|-------------|---------------|
| 用户级 Skills | `~/.agents/skills/<name>/` | `~/.workbuddy/skills/<name>/` |
| 项目级 Skills | `.github/skills/<name>/` | 同 Copilot |
| 项目指令 | `.github/copilot-instructions.md` | 待确认 |
| Agents | `.github/agents/*.agent.md` | 待确认 |

---

## SKILL.md Frontmatter 差异

| 字段 | Copilot | Workbuddy | 备注 |
|------|:---:|:---:|------|
| `name` | ✅ 必填 | ✅ 必填 | 完全一致 |
| `description` | ✅ 必填 | ✅ 必填 | 完全一致 |
| `argument-hint` | ✅ 可选 | ✅ 可选 | 完全一致 |
| `allowed-tools` | ✅ 可选 | ✅ 可选 | 完全一致 |
| `version` | ❌ | ✅ 可选 | Workbuddy 特有，如 `1.0.0` |
| `tags` | ❌ | ✅ 可选 | Workbuddy 特有，标签数组 |
| `category` | ❌ | ✅ 可选 | Workbuddy 特有，分类名 |
| `compatibility` | ❌ | ✅ 可选 | 兼容性说明（非官方字段，但常用） |

---

## Workbuddy 特有文件

| 文件 | 用途 |
|------|------|
| `SKILL.md.fallback.bak` | 备份文件，扫描时应忽略 |
| `_bm_skillid_migration.json` | 内部迁移元数据，扫描时应忽略 |
| `IDENTITY.md` | Agent 身份定义（类似 Copilot 的 agent instructions） |
| `USER.md` | 用户偏好配置 |
| `MEMORY.md` | 持久记忆文件 |
| `SOUL.md` | Agent 核心行为定义 |
| `BOOTSTRAP.md` | 启动初始化配置 |

---

## Token 优化关注点（Workbuddy 特有）

### 应扫描的反模式

与 Copilot 共通的：
- AP-01 ~ AP-12 全部适用

Workbuddy 特有的：
- **WB-01: .fallback.bak 文件残留** — 备份文件可能被误加载
- **WB-02: IDENTITY.md / MEMORY.md 过大** — 等效于 Copilot 的 always-on instructions 反模式
- **WB-03: 多余 frontmatter 字段** — `version`、`tags`、`category` 虽然有用，但会增加 discovery token 消耗

---

## 扫描器适配

当 `--platform workbuddy` 时：
1. 额外扫描 `~/.workbuddy/skills/` 目录
2. 忽略 `.fallback.bak` 和 `_bm_*.json` 文件
3. 检测 `.workbuddy/` 下的 IDENTITY.md、MEMORY.md、BOOTSTRAP.md 尺寸
4. 检测 WB-01 ~ WB-03 特有反模式
