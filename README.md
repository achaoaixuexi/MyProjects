# 🔍 Saving-tokens-skill

诊断并优化 AI 智能体的 token 消耗 —— 支持 **VS Code Copilot** 和 **Workbuddy（腾讯 AI 助手）**。

## 快速开始

```bash
# 扫描当前项目
python scripts/scanner.py . -o result.json --pretty

# 生成诊断报告
python scripts/reporter.py result.json -o report.md

# Workbuddy 平台
python scripts/scanner.py . --platform workbuddy -o result.json
```

## 核心能力

| 模块 | 功能 | 检测项 |
|------|------|--------|
| `scanner.py` | 静态配置扫描 | 12 种反模式（AP-01 ~ AP-12） |
| `session_analyzer.py` | 运行时数据分析 | 6 种行为模式（RP-01 ~ RP-06） |
| `reporter.py` | 多模式报告 | 静态 / 运行时 / 深度综合 |
| `fixer.py` | 自动修复 | AP-03、AP-12 安全自动修复 |
| `benchmark.py` | 基准测试 | 8 任务对照实验框架 |

## 支持的平台

| 平台 | 静态分析 | 运行时分析 |
|------|:---:|:---:|
| VS Code Copilot | ✅ | ✅ |
| Workbuddy（腾讯 AI 助手） | ✅ | 🔜 |

## 检测的反模式

### 静态配置（AP 系列）

| ID | 名称 | 严重等级 |
|----|------|:------:|
| AP-01 | `applyTo: "**"` 全量匹配 | 🔴 Critical |
| AP-02 | Monolithic SKILL.md（>500行） | 🔴 Critical |
| AP-03 | 重复 Instructions 文件 | 🔴 Critical |
| AP-04 | 模糊 description 字段 | 🟠 High |
| AP-05 | Swiss-army Agent（tools 过多） | 🟠 High |
| AP-06 | 冗余 always-on Instructions | 🟡 Medium |
| AP-07 | 缺少渐进加载拆分 | 🟡 Medium |
| AP-08 | SKILL.md 200-500 行 | 🟡 Medium |
| AP-10 | Agent 未声明 tools | 🟢 Low |
| AP-12 | description 超过 500 字符 | 🟢 Low |

### 运行时行为（RP 系列）

| ID | 名称 | 严重等级 |
|----|------|:------:|
| RP-01 | 长会话未使用 compaction | 🟠 High |
| RP-02 | Compaction 触发过晚 | 🟡 Medium |
| RP-03 | 输入/输出 token 比例失衡 | 🟠 High |
| RP-04 | 同一文件被重复读取 | 🟡 Medium |
| RP-05 | 用户消息过长 | 🟡 Medium |
| RP-06 | Token 消耗异常会话 | 🟠 High |

## 项目结构

```
Saving-tokens-skill/
├── SKILL.md                    # Skill 入口（中英文触发词）
├── BENCHMARK_REPORT.md         # 基准测试报告
├── BENCHMARK_PLAN.md           # 测试计划
├── README.md                   # 本文件
├── scripts/
│   ├── scanner.py              # 静态扫描器（双平台）
│   ├── reporter.py             # 报告生成器（三种模式）
│   ├── session_analyzer.py     # 运行时分析器
│   ├── benchmark.py            # 基准测试编排
│   ├── benchmark_reporter.py   # 对比报告生成
│   └── fixer.py                # 自动修复引擎
└── references/
    ├── anti-patterns.md        # 反模式完整目录
    ├── checklist.md            # 人工优化检查清单
    └── workbuddy-mapping.md    # Workbuddy↔Copilot 映射
```

## 使用场景

### 场景 1：日常诊断

```bash
# 一键诊断
python scripts/scanner.py . -o result.json && \
python scripts/reporter.py result.json -o token_report.md

# 查看健康评分
python -c "import json; d=json.load(open('result.json')); print(f'健康评分: {d[\"summary\"][\"health_score\"]}/100')"
```

### 场景 2：深度分析（需要 Cloud Sync）

在 Copilot 对话中触发深度分析：
1. Agent 使用 `copilot_sessionStoreSql` 查询 session 数据
2. 保存为 `session_data.json`
3. 运行：
```bash
python scripts/session_analyzer.py session_data.json -o runtime.json --static-result result.json
python scripts/reporter.py result.json --runtime runtime.json -o deep_report.md
```

### 场景 3：自动修复

```bash
# 预览修复
python scripts/fixer.py result.json --dry-run

# 执行安全修复
python scripts/fixer.py result.json --force

# 生成手动修复指南
python scripts/fixer.py result.json --manual-guide fix_guide.md
```

### 场景 4：基准测试

```bash
# 查看测试计划
python scripts/benchmark.py list

# 生成测试计划文档
python scripts/benchmark.py plan -o test_plan.md

# 记录测试结果
python scripts/benchmark.py record T1 control sess-abc123
python scripts/benchmark.py record T1 experiment sess-def456

# 全部完成后生成报告
python scripts/benchmark_reporter.py benchmark_results.json session_data.json -o BENCHMARK_REPORT.md
```

## 安装

### 作为 Copilot Skill

将整个目录放入 skills 路径：

```bash
# VS Code Copilot
cp -r Saving-tokens-skill ~/.agents/skills/

# Workbuddy
cp -r Saving-tokens-skill ~/.workbuddy/skills/
```

### 直接使用脚本

```bash
git clone https://github.com/your-org/Saving-tokens-skill.git
cd Saving-tokens-skill
pip install pyyaml  # 可选，用于更好的 YAML 解析
```

## 触发关键词

在 Copilot 对话中，以下任意说法都会触发此 Skill：

| 中文 | 英文 |
|------|------|
| 分析 token 消耗 | token analysis |
| 检查上下文浪费 | check token waste |
| 优化 prompt | optimize context |
| token 诊断 | save tokens |
| 节省 token | reduce context |

## 基准测试数据

| 复杂度 | 预估节省率 |
|:------|:-----:|
| 简单任务 | ~5-23% |
| 中等任务 | ~24-30% |
| 复杂任务 | ~34-42% |
| **平均** | **~29%** |

> ⚠️ 以上为演示数据。真实数据请在运行对照实验后查看 `BENCHMARK_REPORT.md`。

## 许可证

MIT
