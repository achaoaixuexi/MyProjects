# 🔍 Saving-tokens-skill

诊断并优化 AI 智能体的 token 消耗。覆盖 **配置诊断**、**运行时分析**、**编程项目优化** 三大场景。
支持 **VS Code Copilot** 和 **Workbuddy（腾讯 AI 助手）**。

---

## 安装

### 方式一：作为 Copilot Skill（推荐）

```bash
# 克隆仓库
git clone https://github.com/achaoaixuexi/MyProjects.git
cd MyProjects/Saving-tokens-skill

# VS Code Copilot — 安装为全局 skill
cp -r . ~/.agents/skills/Saving-tokens-skill/

# Workbuddy — 安装为全局 skill
cp -r . ~/.workbuddy/skills/Saving-tokens-skill/
```

安装后在 Copilot 对话中输入 `token诊断` 或 `分析 token 消耗` 即可触发。

### 方式二：直接使用脚本

```bash
git clone https://github.com/achaoaixuexi/MyProjects.git
cd MyProjects/Saving-tokens-skill
pip install pyyaml  # 可选，更好的 YAML 解析
```

### 验证安装

```bash
python scripts/scanner.py --help       # 应显示 18 项反模式检测
python scripts/project_analyzer.py --help  # 应显示项目分析选项
python -m pytest tests/ -q             # 119 个测试应全部通过
```

---

## 快速开始

```bash
# 一键诊断
python scripts/scanner.py . -o result.json --pretty

# 生成 Markdown 报告
python scripts/reporter.py result.json -o token_report.md

# 编程项目分析
python scripts/project_analyzer.py . -o project_result.json --pretty

# 启用学习型阈值（自适应收紧，减少误报）
python scripts/scanner.py . --learn -o result.json
```

---

## 核心能力

| 模块 | 功能 | 检测项 |
|------|------|:---:|
| `scanner.py` | 静态配置 + 源码扫描 | 18 项反模式 (AP-01~AP-18) |
| `session_analyzer.py` | 运行时 Session 分析 | 12 项行为模式 (RP-01~RP-12) |
| `project_analyzer.py` | 编程项目级分析 | 大文件/目录/依赖膨胀 |
| `reporter.py` | 多模式 Markdown 报告 | 静态 / 运行时 / 深度 / 编程 |
| `fixer.py` | 智能修复引擎 | 3 种压缩模式 + 13 组实体正则 |
| `cache.py` | 增量缓存 | 文件 mtime 缓存 + Session 去重 |
| `benchmark.py` | 对照实验框架 | 12 任务 (含 4 个编程专项) |

---

## 检测覆盖

### 静态反模式 — 18 项

| 等级 | 数量 | 示例 |
|:---:|:---:|------|
| 🔴 Critical | 4 | `applyTo: "**"`、Monolithic SKILL.md、重复 Instructions、无 .gitignore |
| 🟠 High | 5 | Swiss-army Agent、大型代码块 (>50行)、单体源文件 (>1000行) |
| 🟡 Medium | 6 | 冗余 always-on、缺渐进加载、内联文档、重复 import 指令 |
| 🟢 Low | 3 | description 过长、注释占比过高、硬编码配置重复 |

### 运行时反模式 — 12 项

| 等级 | 数量 | 示例 |
|:---:|:---:|------|
| 🔴 High | 3 | 输入/输出比失衡、token 异常会话、大文件/小修改比 |
| 🟡 Medium | 8 | 重复文件读取、工具串行调用、未用 @file 引用、Session Memory 未缓存 |
| 🟢 Low | 1 | 冗余代码输出 |

---

## 支持的平台

| 平台 | 静态分析 | 运行时分析 | 编程项目分析 | `--learn` 自适应 |
|------|:---:|:---:|:---:|:---:|
| VS Code Copilot | ✅ | ✅ | ✅ | ✅ |
| Workbuddy（腾讯） | ✅ | 🔜 | ✅ | ✅ |

---

## 触发关键词

在 Copilot 对话中，以下任意说法都会触发此 Skill：

| 中文 | 英文 |
|------|------|
| 分析 token 消耗 | token analysis |
| 检查上下文浪费 | check token waste |
| 优化 prompt | optimize context |
| token 诊断 | save tokens |
| 分析项目 token 浪费 | analyze project tokens |
| 检查代码项目效率 | check code project efficiency |

---

## 优化特性

| 特性 | 说明 | 版本 |
|------|------|:---:|
| 智能实体救援 | 13 组正则 (含中文 5 组)，日期/URL/CamelCase 完整保留 | P0 |
| 代码/JSON 括号保护 | `{}` `[]` `` ``` `` 结构性安全，结构化括号 100% | P0 |
| 3 种压缩模式 | balanced / conservative / math，按文本类型自动切换 | P2 |
| 自适应截断长度 | 短文本 180 / 中文本 220 / 长文本 260 | P1 |
| 学习型阈值 | `--learn` 基于项目中位数自动收紧 5 项检测阈值 | P3 |
| 增量缓存 | 文件 mtime + Session ID 去重，重复扫描加速 60-90% | — |
| 保真度校验 | ROUGE-L + 综合保真度评分，截断质量可量化 | — |

---

## 基准测试数据

| 指标 | 旧版 (盲截断) | 新版 (全优化) | 提升 |
|------|:---:|:---:|:---:|
| 实体保留率 | 79.6% | **88.8%** | +9.2pp |
| 括号安全率 | 89.2% | **95.4%** | +6.2pp |
| ROUGE-L 相似度 | 0.810 | **0.832** | +0.022 |
| 综合保真度 | 0.680 | **0.713** | +0.033 |
| 编程项目预估节省 | — | **25.5%** / 会话 | 新增 |

> 基于 65 个用例、12 类文本的大规模基准测试。详见 `BENCHMARK_REPORT.md`。

---

## 项目结构

```
Saving-tokens-skill/
├── SKILL.md                       # Skill 入口定义
├── README.md                      # 本文件
├── BENCHMARK_PLAN.md              # 基准测试计划 (12 任务)
├── BENCHMARK_REPORT.md            # 基准测试报告
├── scripts/
│   ├── scanner.py                 # 静态扫描器 (18 AP + 学习型阈值)
│   ├── session_analyzer.py        # 运行时分析器 (12 RP + Session 缓存)
│   ├── project_analyzer.py        # 编程项目分析 (大文件/目录/膨胀)
│   ├── fixer.py                   # 智能修复引擎 (3 模式 + 13 实体)
│   ├── reporter.py                # Markdown 报告生成
│   ├── benchmark.py               # 基准测试编排 (12 任务)
│   ├── benchmark_reporter.py      # 对比报告 + ROUGE-L 质量评估
│   ├── cache.py                   # 文件 mtime + Session ID 缓存
│   └── common.py                  # 公共工具库
├── tests/
│   ├── test_scanner.py            # scanner 单元测试
│   ├── test_session_analyzer.py   # session_analyzer 单元测试 (含 Phase 1-2)
│   ├── test_fixer.py              # fixer 单元测试
│   ├── test_common.py             # common 单元测试
│   ├── conftest.py                # 共享 fixtures
│   ├── benchmark_truncation.py    # 截断质量基准 (15 用例)
│   ├── comprehensive_benchmark.py # 综合基准 (60+ 用例)
│   └── final_benchmark.py         # 最终基准 (含 token 节省率)
└── references/
    ├── anti-patterns.md           # 完整反模式目录 (AP-01~AP-18 + RP-01~RP-12)
    ├── checklist.md               # 人工复查清单
    └── workbuddy-mapping.md       # Workbuddy ↔ Copilot 映射
```

---

## 常见使用场景

```bash
# 场景 1：一键诊断
python scripts/scanner.py . -o result.json --learn && \
python scripts/reporter.py result.json -o report.md

# 场景 2：深度分析（需 session store 数据）
python scripts/session_analyzer.py session_data.json -o runtime.json \
    --static-result result.json && \
python scripts/reporter.py result.json --runtime runtime.json -o deep_report.md

# 场景 3：编程项目分析
python scripts/project_analyzer.py . -o project.json --pretty

# 场景 4：自动修复（预览）
python scripts/fixer.py result.json --dry-run
python scripts/fixer.py result.json --force  # 执行修复

# 场景 5：基准测试
python scripts/benchmark.py list             # 查看 12 个任务
python scripts/benchmark.py plan -o plan.md  # 生成测试计划

# 场景 6：质量验证
python -m pytest tests/ -q                   # 119 个单元测试
python tests/final_benchmark.py              # 性能基准
```

---

## 许可证

MIT
