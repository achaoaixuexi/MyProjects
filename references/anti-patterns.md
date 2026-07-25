# Token 浪费反模式目录

本文档列举所有已知的智能体 token 浪费模式，供 scanner.py 自动检测和人工审查参考。

---

## 反模式索引

| ID | 名称 | 严重等级 | 类别 |
|----|------|:------:|------|
| AP-01 | applyTo 全量匹配 | 🔴 Critical | 上下文加载 |
| AP-02 | Monolithic SKILL.md | 🔴 Critical | 渐进加载 |
| AP-03 | 重复 Instructions 文件 | 🔴 Critical | 冗余配置 |
| AP-04 | 模糊 description 字段 | 🟠 High | 发现效率 |
| AP-05 | Swiss-army Agent | 🟠 High | Agent 设计 |
| AP-06 | 冗余 always-on Instructions | 🟡 Medium | 上下文加载 |
| AP-07 | 缺少渐进加载拆分 | 🟡 Medium | 渐进加载 |
| AP-08 | SKILL.md 超过推荐行数 | 🟡 Medium | 渐进加载 |
| AP-09 | 内联大段文档内容 | 🟡 Medium | 内容冗余 |
| AP-10 | 工具调用未限制 | 🟢 Low | Agent 设计 |
| AP-11 | 循环 Handoff 风险 | 🟢 Low | Agent 设计 |
| AP-12 | 过长的 description | 🟢 Low | 发现效率 |

---

## AP-01: applyTo 全量匹配 🔴

**检测**：YAML frontmatter 中 `applyTo: "**"` 或 `applyTo: **`

**原因**：`applyTo: "**"` 意味着该 instructions 文件会在**每次文件操作**时被加载到上下文中，无论是否相关。单个文件可能数百行（数千 token），每次对话加载即为纯浪费。

**修复**：将 `applyTo` 改为精确的 glob 模式：
```yaml
# ❌ 坏
applyTo: "**"

# ✅ 好
applyTo: "**/*.py"
applyTo: ["src/api/**", "src/models/**"]
```

**预估节省**：每次对话 500-3000 token（取决于 instruction 文件大小）

**检测正则**：`applyTo:\s*"?\*\*"?\s*$`

---

## AP-02: Monolithic SKILL.md 🔴

**检测**：SKILL.md 文件超过 500 行，且同级目录下无 `references/` 文件夹

**原因**：VS Code Copilot 的渐进加载机制允许 SKILL.md 将详细内容拆分到 `references/` 子文件中。Monolithic 写法导致即使只需要部分信息，也必须加载全部内容。

**修复**：将详细章节拆分到 `references/` 目录：
```
skill-name/
├── SKILL.md          # <200 行，核心流程
└── references/
    ├── advanced.md   # 高级用法
    └── examples.md   # 示例
```
在 SKILL.md 中用相对路径引用：`详见 [高级用法](./references/advanced.md)`

**预估节省**：每次加载 2000-5000 token

**检测方式**：`SKILL.md` 行数 > 500 且 `references/` 目录不存在

---

## AP-03: 重复 Instructions 文件 🔴

**检测**：同一目录下同时存在 `copilot-instructions.md` 和 `AGENTS.md`

**原因**：Copilot 会加载两者，内容大概率重复。VS Code 官方明确建议**只用其一**。

**修复**：删除其中一个，保留内容更完整的版本。

**预估节省**：消除 100% 的重复内容加载

**检测方式**：检查 `.github/` 或根目录下两文件是否共存

---

## AP-04: 模糊 description 字段 🟠

**检测**：description 字段缺少关键词、过于笼统

**原因**：description 是 agent 发现 skill/instruction 的**唯一入口**。模糊的描述导致 agent 无法匹配到正确的 skill，转而使用通用方式处理，消耗更多 token 且效果更差。

**示例**：
```yaml
# ❌ 模糊 — agent 无法判断何时使用
description: "A helpful skill for coding"

# ✅ 关键词丰富 — agent 能准确匹配
description: "Use when writing database migrations, schema changes, or data transformations."
```

**修复**：使用 "Use when..." 模式，列举具体触发场景和关键词。

**预估节省**：间接节省（避免 agent 走弯路），每次 500-2000 token

**检测方式**：description 长度 < 50 字符，或不包含领域关键词

---

## AP-05: Swiss-army Agent 🟠

**检测**：Agent 的 `tools` 字段包含 6+ 个工具别名

**原因**：工具过多会分散 agent 注意力，导致它在选择工具时消耗更多推理 token，且容易选错工具产生额外轮次。

**修复**：只保留角色必需的工具：
```yaml
# ❌ Swiss-army
tools: [read, write, edit, search, execute, web, agent, todo]

# ✅ 聚焦
tools: [read, search]  # 只读研究型 agent
```

**预估节省**：每次调用节省 200-500 token（减少推理开销）

**检测方式**：YAML frontmatter 中 `tools:` 数组长度 >= 6

---

## AP-06: 冗余 always-on Instructions 🟡

**检测**：`copilot-instructions.md` 或 `AGENTS.md` 内容超过 200 行

**原因**：always-on instructions 在每次对话中都加载。超过 200 行意味着大量内容可能对当前任务无用，却持续占用上下文窗口。

**修复**：
1. 精简到 100 行以内，只保留**每次任务都需要**的规则
2. 将特定场景的规则拆分到 `.github/instructions/*.instructions.md`
3. 引用外部文档而非内联：`详见 docs/TESTING.md`

**预估节省**：每次对话 500-2000 token

**检测方式**：文件行数 > 200

---

## AP-07: 缺少渐进加载拆分 🟡

**检测**：SKILL.md > 150 行但无 `references/` 子目录

**原因**：与 AP-02 类似但阈值更低。即使不超过 500 行，超过 150 行的 SKILL.md 也应该考虑拆分，以利用渐进加载机制。

**修复**：同 AP-02。

**预估节省**：每次加载 500-1500 token

**检测方式**：SKILL.md 行数 > 150 且 `references/` 不存在

---

## AP-08: SKILL.md 超过推荐行数 🟡

**检测**：SKILL.md 行数在 200-500 之间

**原因**：官方建议 SKILL.md 保持 <500 行。200-500 行虽可接受，但仍有优化空间。

**修复**：审查内容，将非核心流程的章节移入 `references/`。

**预估节省**：每次加载 200-1000 token

---

## AP-09: 内联大段文档内容 🟡

**检测**：instructions/skill 文件中包含大段（>20 行连续）的文档内容（如 API 参考、配置说明）

**原因**：这些内容通常已有独立的文档文件。内联复制导致重复维护和 token 浪费。

**修复**：用引用链接替代内联内容：
```markdown
<!-- ❌ 内联 50 行 API 文档 -->
## API Reference
...50 lines of API docs...

<!-- ✅ 引用链接 -->
API 文档详见 [docs/api.md](./docs/api.md)
```

**预估节省**：按内联内容大小计算

**检测方式**：检测连续非指令性文本块 > 20 行

---

## AP-10: 工具调用未限制 🟢

**检测**：Agent frontmatter 未声明 `tools` 字段

**原因**：未声明 tools 时使用默认工具集。对于只读分析型 agent，默认工具集可能包含 `edit`、`execute` 等不需要的工具。

**修复**：显式声明最小工具集：
```yaml
tools: [read, search]
```

**预估节省**：每次调用 50-200 token

---

## AP-11: 循环 Handoff 风险 🟢

**检测**：两个 Agent 互相在 `agents` 字段中引用对方

**原因**：A agent 可调用 B agent，B agent 也可调用 A agent → 可能产生无限循环，消耗大量 token。

**修复**：确保 handoff 关系是单向的（DAG 而非循环图）：
```yaml
# Agent A
agents: [agent-b]  # A 可委托 B

# Agent B
agents: []         # B 不可反委托 A
```

**预估节省**：防止灾难性消耗

**检测方式**：构建 agent 引用图，检测环路

---

## AP-12: 过长的 description 🟢

**检测**：description 字段超过 500 字符

**原因**：description 在 Discovery 阶段加载（~100 tokens）。过长的 description 增加发现成本，但信息密度低。

**修复**：精简到 200 字符以内，聚焦关键词：
```yaml
# ❌ 过长
description: "This skill helps you with all kinds of database operations including migrations, schema design, query optimization, indexing strategies..."

# ✅ 精简
description: "Database migrations, schema design, and query optimization. Use when: writing SQL, designing schemas, optimizing queries."
```

**预估节省**：每次发现阶段 20-50 token

**检测方式**：description 长度 > 500 字符


---

## AP-13: 内联超大代码块 🟠 (Phase 2)

**检测**：SKILL.md / .instructions.md 中 ` ``` ` 围栏内代码 >50 行

**原因**：大型代码示例直接嵌入配置文件中，每次加载 skill 都会带入，但 Agent 通常只需要引用而非全文。

**修复**：将大型代码示例保存为独立文件，在 SKILL.md 中用相对路径引用

**预估节省**：每次加载 1000-5000 token

---

## AP-14: 冗余 import/安装指令 🟡 (Phase 2)

**检测**：文件内出现 ≥5 处 `pip install` / `import ` / `require(` 等指令

**原因**：多个文件中重复出现相同的安装/导入说明，增加冗余 token。

**修复**：将安装说明集中到一处，instruction 中用引用链接替代

**预估节省**：每次加载 200-1000 token

---

## AP-15: 注释行占比过高 🟢 (Phase 2)

**检测**：`#` / `//` / `<!--` / `>` 开头的注释行占比 >40%

**原因**：过度的解释性注释虽有助于人类阅读，但对 Agent 而言是上下文浪费。

**修复**：精简解释性注释，非必要背景信息移至 references/

**预估节省**：每次加载 100-500 token

---

## AP-16: 大型单体源文件 🟠 (Phase 3 — 编程场景)

**检测**：.py / .ts / .go 等源文件 >1000 行

**原因**：Agent 在读取文件时经常全量加载，大文件意味着大量无关 token。

**修复**：拆分为模块（<300 行/文件）或提供 API 摘要文件供 Agent 读取

**预估节省**：每次加载 2000-5000 token

---

## AP-17: 未排除的重量级目录 🔴 (Phase 3 — 编程场景)

**检测**：node_modules / .venv / dist 等目录未被 .gitignore 排除

**原因**：Agent 扫描项目时遍历所有文件，包括依赖和构建产物，造成极大浪费。

**修复**：在 .gitignore 中添加 node_modules/ .venv/ dist/ 等

**预估节省**：每次扫描 500-8000 token

---

## AP-18: 硬编码配置值跨文件重复 🟢 (Phase 3 — 编程场景)

**检测**：URL / 密码 / 密钥等硬编码值在 ≥3 个配置文件中重复出现

**原因**：同一配置值在多个 skill 描述中重复，Agent 多次加载相同信息。

**修复**：提取到单一配置文件或环境变量，用引用替代重复

**预估节省**：每次加载 200-500 token


---

# 运行时反模式 (RP — Runtime Patterns)

以下反模式通过 `session_analyzer.py` 在 session store 数据中检测。

## RP-01: 长会话未使用 Compaction 🔴

**检测**：会话 >20 轮但无 checkpoint 记录

**修复**：在第 10-15 轮使用 /compact 或开启自动压缩

**预估浪费**：(轮数 − 10) × 2000 tokens

---

## RP-02: Compaction 触发过晚 🟡

**检测**：首次 compaction 发生在 >60% 轮次处

**修复**：在 25%-30% 轮次处触发首次 compaction

**预估浪费**：1500-5000 tokens

---

## RP-03: 输入/输出 Token 比例失衡 🔴

**检测**：input/output token 比 >10:1

**修复**：精简单次会话任务范围或压缩上下文

---

## RP-04: 同一文件被重复读取 🟡

**检测**：同一文件在同一会话中被读取 ≥5 次

**修复**：缓存到 session memory 或一次性读取大范围

---

## RP-05: 用户消息过长 🟡

**检测**：用户消息 >3000 字符

**修复**：将大段代码保存为文件后使用 @file 引用

---

## RP-06: Token 消耗异常会话 🔴

**检测**：会话 token 消耗 >平均值 3 倍

**修复**：拆分多会话或使用子代理

---

## RP-07: 全文件读取/小修改比失衡 🔴 (Phase 1 — 编程场景)

**检测**：读取 >500 行但仅修改极小范围

**修复**：使用 read_file(startLine, endLine) 精确范围

**预估浪费**：(读取行 − 50) × 3 tokens

---

## RP-08: 工具调用串行化 🟡 (Phase 1 — 编程场景)

**检测**：连续 ≥3 个独立 read_file/grep_search 调用未并行化

**修复**：将无依赖的独立调用合并为并行执行

**预估浪费**：(N − 1) × 500 tokens

---

## RP-09: 内联代码未使用 @file 引用 🟡 (Phase 2 — 编程场景)

**检测**：消息中含 >500 字符代码块但无 @file 引用

**修复**：保存代码为文件后用 @file 引用

**预估浪费**：代码字符数 ÷ 3 tokens

---

## RP-10: 重复读取未变更文件 🟡 (Phase 1 — 编程场景)

**检测**：同一文件跨轮读取 ≥3 次且 mtime 未变

**修复**：缓存至 /memories/session/

**预估浪费**：(N − 1) × 500 tokens

---

## RP-11: 冗余代码输出 🟢 (Phase 2 — 编程场景)

**检测**：Agent 输出中 >60% 行重叠的代码块出现 ≥2 次

**修复**：引用前次输出而非重新生成

**预估浪费**：重复次数 × 300 tokens

---

## RP-12: 未使用 Session Memory 缓存 🟡 (Phase 2 — 编程场景)

**检测**：≥3 个关键术语跨 ≥3 轮重复查询

**修复**：将频繁查询的信息写入 /memories/session/

**预估浪费**：重复次数 × 200 tokens