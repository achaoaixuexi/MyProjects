"""
Saving-tokens-skill — Benchmark Orchestrator
=============================================
Defines standardized test tasks and guides the token-saving benchmark process.

Workflow:
  1. Define test tasks (this script)
  2. For each task: run WITHOUT Saving-tokens-skill (control), record session ID
  3. For each task: run WITH Saving-tokens-skill (experiment), record session ID
  4. Extract token data from session store
  5. Run benchmark_reporter.py to generate BENCHMARK_REPORT.md

Usage:
    python benchmark.py list                    # List all test tasks
    python benchmark.py plan -o plan.md         # Generate test plan for manual execution
    python benchmark.py record <task_id> <mode> <session_id>  # Record a session result
"""

import json
import os
import argparse
import sys
from pathlib import Path
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Test Task Definitions
# ---------------------------------------------------------------------------

TASKS = [
    {
        "id": "T1",
        "name": "简单代码生成",
        "complexity": "简单",
        "prompt": "写一个 Python 函数，接收一个字符串参数，返回反转后的字符串。包含类型注解和 docstring。",
        "expected_turns": "1-2 轮",
        "category": "代码生成",
    },
    {
        "id": "T2",
        "name": "代码审查",
        "complexity": "简单",
        "prompt": "审查以下代码的质量，指出潜在问题和改进建议：\n```python\ndef process_data(items):\n    result = []\n    for i in range(len(items)):\n        if items[i] != None:\n            result.append(items[i].strip())\n    return result\n```",
        "expected_turns": "2-3 轮",
        "category": "代码审查",
    },
    {
        "id": "T3",
        "name": "Bug 修复",
        "complexity": "中等",
        "prompt": "以下代码运行时报 KeyError，请找出 bug 并修复：\n```python\nconfig = {\"host\": \"localhost\", \"port\": 8080}\nprint(f\"Connecting to {config['host']}:{config['database']}\")\n```",
        "expected_turns": "3-4 轮",
        "category": "调试修复",
    },
    {
        "id": "T4",
        "name": "多文件重构",
        "complexity": "中等",
        "prompt": "我有一个 Python 项目，所有模块都用 `print()` 做日志输出。请写一个方案，把项目中所有 `print()` 替换为 `logging` 模块调用。需要说明具体步骤和注意事项。",
        "expected_turns": "3-5 轮",
        "category": "重构",
    },
    {
        "id": "T5",
        "name": "项目初始化",
        "complexity": "复杂",
        "prompt": "请帮我创建一个 React + TypeScript 的待办事项 (Todo) 应用，包含：添加、删除、标记完成、筛选（全部/已完成/未完成）功能。使用函数组件和 hooks。",
        "expected_turns": "5-8 轮",
        "category": "项目初始化",
    },
    {
        "id": "T6",
        "name": "跨文件分析",
        "complexity": "复杂",
        "prompt": "分析当前项目的 API 调用模式：找出所有 HTTP 请求的位置、使用的库、请求方法、是否有统一错误处理。生成一份 API 调用清单文档。",
        "expected_turns": "4-6 轮",
        "category": "代码分析",
    },
    {
        "id": "T7",
        "name": "复杂调试",
        "complexity": "复杂",
        "prompt": "我的 Node.js 项目 `npm run build` 失败了，报错信息是 'Module not found: Error: Can\\'t resolve \"@/components/Button\"'。请帮我分析可能的原因，并给出排查步骤和修复方案。",
        "expected_turns": "5-10 轮",
        "category": "调试修复",
    },
    {
        "id": "T8",
        "name": "长对话压力测试",
        "complexity": "高复杂",
        "prompt": "我有一个 2000 行的 Python 数据处理脚本，性能很差。请帮我：1) 分析性能瓶颈 2) 提出优化方案 3) 实现关键优化 4) 添加单元测试 5) 添加类型注解。分步骤执行，每步确认后再继续。",
        "expected_turns": "10+ 轮",
        "category": "长对话",
    },
]


def list_tasks():
    """Print all test tasks."""
    print(f"\n{'='*70}")
    print(f"  Saving-tokens-skill 基准测试任务 ({len(TASKS)} 个)")
    print(f"{'='*70}\n")
    for t in TASKS:
        print(f"  [{t['id']}] {t['name']} ({t['complexity']})")
        print(f"       类别: {t['category']} | 预计: {t['expected_turns']}")
        print(f"       Prompt: {t['prompt'][:80]}...")
        print()


def generate_plan(output_file: str | None = None):
    """Generate a test plan Markdown file for manual execution."""
    lines = [
        f"# Saving-tokens-skill 基准测试计划",
        f"",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**测试任务**: {len(TASKS)} 个",
        f"",
        f"---",
        f"",
        f"## 测试方法",
        f"",
        f"### 对照组（不使用 Saving-tokens-skill）",
        f"1. 开启一个新的 Copilot 对话",
        f"2. 直接输入测试 prompt",
        f"3. 完成对话，记录最终的 session ID",
        f"4. 使用 `copilot_sessionStoreSql` 查询该 session 的 token 消耗",
        f"",
        f"### 实验组（使用 Saving-tokens-skill）",
        f"1. 开启一个新的 Copilot 对话",
        f"2. 先输入 `/Saving-tokens-skill` 触发 skill 诊断",
        f"3. 再输入相同的测试 prompt",
        f"4. 完成对话，记录最终的 session ID",
        f"5. 使用 `copilot_sessionStoreSql` 查询该 session 的 token 消耗",
        f"",
        f"### 注意事项",
        f"- 对照组和实验组必须使用**完全相同**的测试 prompt",
        f"- 实验组中 Saving-tokens-skill 自身的 token 消耗需计入总消耗",
        f"- 每个任务完成后记录 session ID 到 `benchmark_results.json`",
        f"",
        f"---",
        f"",
        f"## 测试任务列表",
        f"",
        f"| # | ID | 任务 | 复杂度 | 类别 | 预计轮数 |",
        f"|----|----|------|:------:|------|:------:|",
    ]

    for t in TASKS:
        lines.append(f"| {TASKS.index(t)+1} | {t['id']} | {t['name']} | {t['complexity']} | {t['category']} | {t['expected_turns']} |")

    lines.extend([
        "",
        "---",
        "",
        "## 每个任务的详细 Prompt",
        "",
    ])

    for t in TASKS:
        lines.extend([
            f"### {t['id']}: {t['name']}",
            "",
            "```",
            t['prompt'],
            "```",
            "",
        ])

    content = "\n".join(lines)

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"测试计划已生成: {output_file}")
    else:
        print(content)


# Session results storage — configurable via env var or CLI
RESULTS_FILE = os.environ.get("BENCHMARK_RESULTS_FILE", "benchmark_results.json")


def load_results() -> dict:
    """Load existing benchmark results."""
    if Path(RESULTS_FILE).exists():
        with open(RESULTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "test_date": datetime.now().strftime("%Y-%m-%d"),
        "methodology": "对照实验：相同任务 × 2 次执行（对照组 vs 实验组）",
        "results": {},
    }


def save_results(data: dict):
    """Save benchmark results."""
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def record_result(task_id: str, mode: str, session_id: str):
    """Record a test session result."""
    valid_ids = {t["id"] for t in TASKS}
    if task_id not in valid_ids:
        print(f"错误: 无效的任务 ID — {task_id}. 有效值: {', '.join(sorted(valid_ids))}", file=sys.stderr)
        sys.exit(1)

    if mode not in ("control", "experiment"):
        print(f"错误: 无效的模式 — {mode}. 使用 'control' 或 'experiment'", file=sys.stderr)
        sys.exit(1)

    data = load_results()
    if task_id not in data["results"]:
        task = next(t for t in TASKS if t["id"] == task_id)
        data["results"][task_id] = {
            "name": task["name"],
            "complexity": task["complexity"],
            "prompt": task["prompt"],
            "control": {},
            "experiment": {},
        }

    data["results"][task_id][mode] = {
        "session_id": session_id,
        "recorded_at": datetime.now().isoformat(),
    }

    save_results(data)
    completed = sum(1 for r in data["results"].values() if r["control"] and r["experiment"])
    print(f"已记录 {task_id} ({mode}). 已完成 {completed}/{len(TASKS)} 个任务的配对数据。")


def main():
    parser = argparse.ArgumentParser(description="Saving-tokens-skill 基准测试编排器")
    sub = parser.add_subparsers(dest="command")

    # list
    sub.add_parser("list", help="列出所有测试任务")

    # plan
    plan_parser = sub.add_parser("plan", help="生成测试计划")
    plan_parser.add_argument("-o", "--output", help="输出 Markdown 文件路径")

    # record
    rec_parser = sub.add_parser("record", help="记录一次测试会话")
    rec_parser.add_argument("task_id", help="任务 ID (T1-T8)")
    rec_parser.add_argument("mode", choices=["control", "experiment"], help="对照组或实验组")
    rec_parser.add_argument("session_id", help="Copilot session ID")

    args = parser.parse_args()

    if args.command == "list":
        list_tasks()
    elif args.command == "plan":
        generate_plan(args.output)
    elif args.command == "record":
        record_result(args.task_id, args.mode, args.session_id)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
