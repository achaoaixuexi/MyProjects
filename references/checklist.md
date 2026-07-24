# Token 优化检查清单

在自动扫描完成后，使用此清单进行人工复查，确保无遗漏。

---

## 1. 上下文加载策略

- [ ] **applyTo 精确化**: 所有 instructions 文件的 `applyTo` 是否使用了精确的 glob 模式而非 `"**"`？
  - 如果某个 instruction 确实需要全局生效，考虑是否该用 always-on 的 `copilot-instructions.md` 代替。
- [ ] **Always-on 精简**: `copilot-instructions.md` / `AGENTS.md` 的每一行是否都是**每次任务都需要**的？
  - 每行 "可能有用" 的内容 → 考虑移除或移到场景化 `.instructions.md`
- [ ] **只有一份 Always-on**: 确认不存在 `copilot-instructions.md` 和 `AGENTS.md` 共存的情况

## 2. 渐进加载设计

- [ ] **SKILL.md 行数**: 每个 SKILL.md 是否 <200 行？
  - 200-500 行: 可接受但有优化空间
  - >500 行: 必须拆分
- [ ] **references/ 存在**: 每个 >150 行的 SKILL.md 是否有 `references/` 子目录？
- [ ] **引用而非内联**: 大段文档内容是否使用了引用链接而非直接复制？
  - ❌ `## API Reference` → 50 行 API 文档
  - ✅ `详见 [API 文档](./docs/api.md)`

## 3. Description 字段质量

- [ ] **关键词丰富**: 每个 `description` 是否包含足够的触发关键词？
  - 用 "Use when: ..." 格式，列举 3-5 个具体场景
- [ ] **长度适中**: description 是否在 50-500 字符之间？
  - <50 字符: 太短，缺少关键词
  - >500 字符: 太长，增加发现成本而信息密度低
- [ ] **排除否定场景**: description 中是否包含 "Do NOT use for..." 避免误触发？

## 4. Agent 设计

- [ ] **最小工具集**: 每个 Agent 的 `tools` 是否只包含必需的？
  - 只读分析: `tools: [read, search]`
  - 代码生成: `tools: [read, write, edit, search]`
- [ ] **单向 Handoff**: Agent 之间的委托关系是否为单向（无循环）？
- [ ] **user-invocable 正确**: 仅被其他 agent 调用的子 agent 是否设置了 `user-invocable: false`？

## 5. 运行时优化

- [ ] **Session Memory 利用**: 跨轮需要的信息是否存入了 `/memories/session/`？
- [ ] **子代理委托**: 复杂搜索任务是否使用了 `Explore` 子代理而非手动链式调用？
- [ ] **并行工具调用**: 独立操作是否尽可能并行化？

## 6. 定期维护

- [ ] **季度审查**: 每季度运行一次 scanner.py，检查新增配置是否符合规范
- [ ] **新增 Skill 审查**: 每次新建 SKILL.md / .instructions.md 时对照此清单检查
- [ ] **Session Store 分析**: 定期查看 token 消耗趋势，识别新出现的浪费模式

---

## 快速自查命令

```bash
# 运行扫描
python scripts/scanner.py . -o result.json

# 生成报告
python scripts/reporter.py result.json -o report.md

# 查看健康评分
python -c "import json; d=json.load(open('result.json')); print(f'健康评分: {d[\"summary\"][\"health_score\"]}/100')"
```

**目标**: 健康评分 ≥ 80 分。
