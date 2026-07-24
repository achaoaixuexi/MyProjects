"""
Saving-tokens-skill — Benchmark Reporter
=========================================
Generates the token-savings comparison report from benchmark results and session data.

Input: benchmark_results.json (from benchmark.py record) + session data JSON (from copilot_sessionStoreSql)
Output: BENCHMARK_REPORT.md

Usage:
    python benchmark_reporter.py benchmark_results.json session_data.json [-o BENCHMARK_REPORT.md]
"""

import json
import argparse
import sys
from pathlib import Path
from datetime import datetime
from typing import Any

from common import safe_int, safe_output_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def extract_session_tokens(session_data: dict, session_id: str) -> dict:
    """Extract token stats for a specific session from session data."""
    result = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "turn_count": 0,
        "found": False,
    }

    # Check events table (cloud backend)
    events = session_data.get("events", [])
    for e in events:
        sid = e.get("session_id", "")
        if sid != session_id:
            continue
        if e.get("type") == "assistant.usage":
            result["input_tokens"] += safe_int(e.get("usage_input_tokens", 0))
            result["output_tokens"] += safe_int(e.get("usage_output_tokens", 0))
            result["found"] = True

    # Check turns table (for turn count)
    turns = session_data.get("turns", [])
    for t in turns:
        sid = t.get("session_id", "")
        if sid == session_id:
            result["turn_count"] += 1

    result["total_tokens"] = result["input_tokens"] + result["output_tokens"]

    # If no event data (local backend), estimate from turn count
    if not result["found"] and result["turn_count"] > 0:
        # Rough estimate: ~1000 tokens per turn
        result["total_tokens"] = result["turn_count"] * 1000
        result["input_tokens"] = int(result["total_tokens"] * 0.7)
        result["output_tokens"] = int(result["total_tokens"] * 0.3)
        result["estimated"] = True

    return result


def generate_report(benchmark_data: dict, session_data: dict) -> str:
    """Generate the benchmark comparison report."""
    results = benchmark_data.get("results", {})
    test_date = benchmark_data.get("test_date", datetime.now().strftime("%Y-%m-%d"))

    lines: list[str] = []
    lines.append("# 📊 Saving-tokens-skill 基准测试报告")
    lines.append("")
    lines.append(f"**测试日期**: {test_date}  ")
    lines.append(f"**测试方法**: 对照实验 — 同一任务 × 2 次（对照组 vs 实验组）  ")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ---- Methodology ----
    lines.append("## 🔬 实验设计")
    lines.append("")
    lines.append("| 组别 | 说明 |")
    lines.append("|------|------|")
    lines.append("| **对照组** | 不加载 Saving-tokens-skill，直接执行标准任务 |")
    lines.append("| **实验组** | 先加载 `/Saving-tokens-skill` 诊断，再执行相同的标准任务 |")
    lines.append("")
    lines.append("**公平性约束**: 实验组中 Saving-tokens-skill 自身的 token 消耗已计入总消耗。")
    lines.append("")

    # ---- Per-task comparison ----
    lines.append("---")
    lines.append("")
    lines.append("## 📋 逐任务对比")
    lines.append("")

    # Table header
    lines.append("| # | 任务 | 复杂度 | 对照组 (tokens) | 实验组 (tokens) | 节省量 | 节省% |")
    lines.append("|---|------|:------:|:---:|:---:|:---:|:---:|")

    task_rows = []
    total_control = 0
    total_experiment = 0
    completed_tasks = 0
    savings_list: list[float] = []

    # Sort by task ID
    sorted_tasks = sorted(results.items(), key=lambda x: x[0])

    for task_id, task_data in sorted_tasks:
        control_info = task_data.get("control", {})
        experiment_info = task_data.get("experiment", {})

        if not control_info or not experiment_info:
            continue

        control_sid = control_info.get("session_id", "")
        experiment_sid = experiment_info.get("session_id", "")

        if not control_sid or not experiment_sid:
            continue

        ctrl_tokens = extract_session_tokens(session_data, control_sid)
        expr_tokens = extract_session_tokens(session_data, experiment_sid)

        ctrl_total = ctrl_tokens["total_tokens"]
        expr_total = expr_tokens["total_tokens"]

        if ctrl_total == 0 and expr_total == 0:
            continue

        saved = ctrl_total - expr_total
        pct = (saved / ctrl_total * 100) if ctrl_total > 0 else 0

        total_control += ctrl_total
        total_experiment += expr_total
        completed_tasks += 1
        savings_list.append(pct)

        name = task_data.get("name", task_id)
        complexity = task_data.get("complexity", "?")

        est_marker = " ⚠️" if (ctrl_tokens.get("estimated") or expr_tokens.get("estimated")) else ""
        pct_str = f"{pct:+.1f}%"

        task_rows.append(f"| {completed_tasks} | {name}{est_marker} | {complexity} | {_format_tokens(ctrl_total)} | {_format_tokens(expr_total)} | {_format_tokens(saved)} | {pct_str} |")

    lines.extend(task_rows)

    if not task_rows:
        lines.append("| - | *暂无数据* | - | - | - | - | - |")

    lines.append("")

    # ---- Summary ----
    lines.append("---")
    lines.append("")
    lines.append("## 📊 汇总统计")
    lines.append("")

    avg_savings = 0.0
    if completed_tasks > 0:
        avg_savings = sum(savings_list) / len(savings_list) if savings_list else 0
        max_savings = max(savings_list) if savings_list else 0
        min_savings = min(savings_list) if savings_list else 0

        total_saved = total_control - total_experiment
        overall_pct = (total_saved / total_control * 100) if total_control > 0 else 0

        lines.append("| 指标 | 值 |")
        lines.append("|------|----|")
        lines.append(f"| 完成配对任务 | **{completed_tasks}/{len(results)}** |")
        lines.append(f"| 对照组总消耗 | **{_format_tokens(total_control)}** tokens |")
        lines.append(f"| 实验组总消耗 | **{_format_tokens(total_experiment)}** tokens |")
        lines.append(f"| 总节省量 | **{_format_tokens(total_saved)}** tokens |")
        lines.append(f"| 总体节省率 | **{overall_pct:.1f}%** |")
        lines.append(f"| 平均节省率 | **{avg_savings:.1f}%** |")
        lines.append(f"| 最高节省率 | **{max_savings:.1f}%** |")
        lines.append(f"| 最低节省率 | **{min_savings:.1f}%** |")
        lines.append("")

        # Per-complexity breakdown
        lines.append("### 按复杂度分组")
        lines.append("")
        lines.append("| 复杂度 | 任务数 | 对照组 | 实验组 | 节省% |")
        lines.append("|--------|:----:|:---:|:---:|:---:|")

        for comp in ["简单", "中等", "复杂", "高复杂"]:
            comp_tasks = [(tid, td) for tid, td in sorted_tasks if td.get("complexity") == comp]
            if not comp_tasks:
                continue
            comp_ctrl = 0
            comp_expr = 0
            count = 0
            for tid, td in comp_tasks:
                ci = td.get("control", {}).get("session_id", "")
                ei = td.get("experiment", {}).get("session_id", "")
                if ci and ei:
                    ct = extract_session_tokens(session_data, ci)
                    et = extract_session_tokens(session_data, ei)
                    comp_ctrl += ct["total_tokens"]
                    comp_expr += et["total_tokens"]
                    count += 1
            if count > 0:
                cpct = ((comp_ctrl - comp_expr) / comp_ctrl * 100) if comp_ctrl > 0 else 0
                lines.append(f"| {comp} | {count} | {_format_tokens(comp_ctrl)} | {_format_tokens(comp_expr)} | {cpct:.1f}% |")

    else:
        lines.append("⚠️ 尚未收集到足够的配对数据。请运行更多测试任务。")

    lines.append("")
    lines.append("---")
    lines.append("")

    # ---- Conclusions ----
    lines.append("## 🎯 结论与建议")
    lines.append("")

    if avg_savings > 30:
        lines.append(f"✅ **显著有效**: 使用 Saving-tokens-skill 平均节省 **{avg_savings:.1f}%** token。强烈推荐在所有项目中集成。")
    elif avg_savings > 15:
        lines.append(f"✅ **有效**: 使用 Saving-tokens-skill 平均节省 **{avg_savings:.1f}%** token。建议在复杂任务中优先使用。")
    elif avg_savings > 5:
        lines.append(f"📈 **有一定效果**: 使用 Saving-tokens-skill 平均节省 **{avg_savings:.1f}%** token。在复杂/长对话任务中效果更明显。")
    elif completed_tasks > 0:
        lines.append(f"🔍 **效果待进一步验证**: 当前数据显示节省 **{avg_savings:.1f}%**，需要更多测试数据确认。")
    else:
        lines.append("🔍 **待测试**: 基准测试数据尚未收集，请运行测试任务后更新此报告。")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"*报告由 Saving-tokens-skill 生成 | {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    lines.append("")
    lines.append(f"*测试平台: VS Code Copilot | 数据来源: copilot_sessionStoreSql*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Saving-tokens-skill — 基准测试报告生成器"
    )
    parser.add_argument("benchmark_json", help="benchmark.py record 生成的 benchmark_results.json")
    parser.add_argument("session_json", help="copilot_sessionStoreSql 导出的 session 数据 JSON")
    parser.add_argument("-o", "--output", help="输出 Markdown 报告路径（默认 stdout）")
    args = parser.parse_args()

    try:
        with open(args.benchmark_json, "r", encoding="utf-8") as f:
            benchmark_data = json.load(f)
    except FileNotFoundError:
        print(f"错误: 文件不存在 — {args.benchmark_json}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(args.session_json, "r", encoding="utf-8") as f:
            session_data = json.load(f)
    except FileNotFoundError:
        print(f"错误: 文件不存在 — {args.session_json}", file=sys.stderr)
        sys.exit(1)

    report = generate_report(benchmark_data, session_data)

    if args.output:
        try:
            out = safe_output_path(args.output, base_dir=str(Path.cwd()))
        except ValueError as e:
            print(f"错误: {e}", file=sys.stderr)
            sys.exit(1)
        with open(str(out), "w", encoding="utf-8") as f:
            f.write(report)
        print(f"基准测试报告已生成: {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
