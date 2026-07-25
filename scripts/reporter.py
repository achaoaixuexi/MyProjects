"""
Saving-tokens-skill — Report Generator
=======================================
将 scanner.py 的 JSON 输出转换为可读的 Markdown 诊断报告。

Usage:
    python reporter.py scan_result.json [-o report.md]
"""

import json
import argparse
import sys
from pathlib import Path
from datetime import datetime
from typing import Any

from common import safe_output_path


# ---------------------------------------------------------------------------
# Severity display helpers
# ---------------------------------------------------------------------------

SEVERITY_ICON = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🟢",
}

SEVERITY_LABEL = {
    "critical": "严重",
    "high": "高",
    "medium": "中",
    "low": "低",
}

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def sort_findings(findings: list[dict]) -> list[dict]:
    """Sort by severity then by file path."""
    return sorted(findings, key=lambda f: (SEVERITY_ORDER.get(f.get("severity", "low"), 99), f.get("file", "")))


def health_bar(score: int) -> str:
    """Visual health bar."""
    if score >= 90:
        return f"🟢 优秀 ({score}/100)"
    elif score >= 70:
        return f"🟡 良好 ({score}/100)"
    elif score >= 50:
        return f"🟠 需改进 ({score}/100)"
    else:
        return f"🔴 较差 ({score}/100)"


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(data: dict) -> str:
    """Generate Markdown report from scan data."""
    if "error" in data:
        return f"# ❌ 扫描失败\n\n**错误**: {data['error']}"

    summary = data.get("summary", {})
    findings = data.get("findings", [])
    target = data.get("target", "未知")
    scan_time = data.get("scan_time", "")

    sorted_findings = sort_findings(findings)
    by_severity = summary.get("by_severity", {})

    lines: list[str] = []

    # ---- Header ----
    lines.append("# 🔍 Token 消耗诊断报告")
    lines.append("")
    lines.append(f"**扫描目标**: `{target}`  ")
    lines.append(f"**扫描时间**: {scan_time}  ")
    lines.append(f"**平台**: VS Code Copilot  ")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ---- Summary Dashboard ----
    lines.append("## 📊 概览")
    lines.append("")

    total = summary.get("total_findings", 0)
    health = summary.get("health_score", 100)
    files = summary.get("files_scanned", {})

    lines.append("| 指标 | 值 |")
    lines.append("|------|----|")
    lines.append(f"| 🔍 发现问题 | **{total}** 个 |")
    lines.append(f"| 🔴 严重 | {by_severity.get('critical', 0)} |")
    lines.append(f"| 🟠 高优先级 | {by_severity.get('high', 0)} |")
    lines.append(f"| 🟡 中优先级 | {by_severity.get('medium', 0)} |")
    lines.append(f"| 🟢 低优先级 | {by_severity.get('low', 0)} |")
    lines.append(f"| 📁 扫描文件 | {sum(files.values())} 个配置 |")
    lines.append(f"| 🏥 健康评分 | {health_bar(health)} |")
    lines.append("")

    # File scan breakdown
    lines.append("<details>")
    lines.append("<summary>📁 扫描文件明细</summary>")
    lines.append("")
    lines.append("| 类型 | 数量 |")
    lines.append("|------|:----:|")
    for k, v in files.items():
        label = {"skills": "Skills", "instructions": "Instructions", "agents": "Agents",
                 "prompts": "Prompts", "always_on": "Always-on"}.get(k, k)
        lines.append(f"| {label} | {v} |")
    lines.append("")
    lines.append("</details>")
    lines.append("")

    # ---- No findings ----
    if total == 0:
        lines.append("## ✅ 未发现问题")
        lines.append("")
        lines.append("恭喜！当前项目配置健康，未检测到已知的 token 浪费反模式。")
        lines.append("")
        lines.append("定期复查建议：")
        lines.append("- 新增 SKILL.md 时确保 <200 行并拆分配置")
        lines.append("- description 使用 keyword-rich 的 \"Use when\" 模式")
        lines.append("- 审查 `applyTo` 是否使用精确 glob")
        return "\n".join(lines)

    # ---- Findings by severity ----
    lines.append("---")
    lines.append("")
    lines.append("## 📋 问题详情")
    lines.append("")

    current_severity = None
    finding_num = 0

    for f in sorted_findings:
        sev = f.get("severity", "low")
        if sev != current_severity:
            current_severity = sev
            icon = SEVERITY_ICON.get(sev, "⚪")
            label = SEVERITY_LABEL.get(sev, sev)
            lines.append(f"### {icon} {label}优先级")
            lines.append("")

        finding_num += 1
        ap_id = f.get("id", "??")
        file_path = f.get("file", "")
        detail = f.get("detail", "")
        suggestion = f.get("suggestion", "")
        est_savings = f.get("est_savings", "")

        try:
            rel_path = Path(file_path).name if file_path else ""
        except Exception:
            rel_path = file_path

        lines.append(f"#### {finding_num}. [{ap_id}] {rel_path}")
        lines.append("")
        lines.append(f"**文件**: `{file_path}`  ")
        lines.append(f"**问题**: {detail}  ")
        if est_savings:
            lines.append(f"**预估节省**: {est_savings}  ")
        lines.append(f"**建议**: {suggestion}  ")
        lines.append("")

    # ---- Recommendations ----
    lines.append("---")
    lines.append("")
    lines.append("## 🎯 优化建议汇总")
    lines.append("")

    sorted_findings_local = sorted_findings
    all_ids = {f["id"] for f in sorted_findings_local}

    rec_num = 0

    if "AP-01" in all_ids:
        rec_num += 1
        lines.append(f"{rec_num}. **修复 applyTo 全量匹配** — 将 `applyTo: '**'` 改为精确的 glob 模式，避免无关文件操作时加载 Instructions")

    if "AP-02" in all_ids:
        rec_num += 1
        lines.append(f"{rec_num}. **拆分大型 SKILL.md** — 将 >500 行的 SKILL.md 拆分为核心流程 + references/ 子文件，利用渐进加载机制")

    if "AP-03" in all_ids:
        rec_num += 1
        lines.append(f"{rec_num}. **合并重复 Instructions** — 删除 AGENTS.md 或 copilot-instructions.md 中的冗余文件")

    if "AP-04" in all_ids:
        rec_num += 1
        lines.append(f"{rec_num}. **优化 description 字段** — 使用 'Use when: ...' 格式，添加具体触发场景关键词")

    if "AP-05" in all_ids:
        rec_num += 1
        lines.append(f"{rec_num}. **精简 Agent tools** — 只保留角色必需的工具，避免 Swiss-army agent 模式")

    if "AP-06" in all_ids:
        rec_num += 1
        lines.append(f"{rec_num}. **精简 always-on Instructions** — 将 >200 行的 instructions 拆分为场景化的 .instructions.md")

    if "AP-07" in all_ids:
        rec_num += 1
        lines.append(f"{rec_num}. **为 SKILL.md 添加渐进加载** — 创建 references/ 目录，拆分详细内容")

    if "AP-08" in all_ids:
        rec_num += 1
        lines.append(f"{rec_num}. **精简 SKILL.md** — 将 200-500 行的 SKILL.md 中非核心内容移入 references/")

    if "AP-12" in all_ids:
        rec_num += 1
        lines.append(f"{rec_num}. **精简 description** — 将 >500 字符的 description 缩短到 200 字符以内，保留核心关键词")

    if rec_num == 0:
        lines.append("无需额外操作，当前项目配置整体健康。")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"*报告由 Saving-tokens-skill 生成 | {datetime.now().strftime('%Y-%m-%d %H:%M')}*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Saving-tokens-skill — 生成 Markdown 诊断报告"
    )
    parser.add_argument("input", help="scanner.py 或 session_analyzer.py 输出的 JSON 文件路径")
    parser.add_argument("-o", "--output", help="输出 Markdown 文件路径（默认输出到 stdout）")
    parser.add_argument("--runtime", help="session_analyzer.py 输出的运行时 JSON（合并生成深度报告）")
    args = parser.parse_args()

    # Validate output path
    if args.output:
        try:
            safe_output_path(args.output, base_dir=str(Path.cwd()))
        except ValueError as e:
            print(f"错误: {e}", file=sys.stderr)
            sys.exit(1)

    try:
        with open(args.input, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"错误: 文件不存在 — {args.input}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"错误: JSON 解析失败 — {e}", file=sys.stderr)
        sys.exit(1)

    runtime_data = None
    if args.runtime:
        try:
            with open(args.runtime, "r", encoding="utf-8") as f:
                runtime_data = json.load(f)
        except Exception as e:
            print(f"警告: 无法读取运行时数据 — {e}", file=sys.stderr)

    # Detect data type
    is_runtime = "backend" in data

    if runtime_data:
        report = generate_deep_report(data, runtime_data)
    elif is_runtime:
        report = generate_runtime_report(data)
    else:
        report = generate_report(data)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"报告已生成: {args.output}")
    else:
        print(report)


def generate_project_section(project_data: dict) -> str:
    """Generate a programming-project analysis section for the Markdown report."""
    summary = project_data.get("summary", {})
    savings = project_data.get("savings_estimate", {})

    lines: list[str] = []
    lines.append("---")
    lines.append("")
    lines.append("## 💻 编程项目分析")
    lines.append("")

    # Project overview
    lines.append("### 项目概况")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|------|----|")
    lines.append(f"| 大型源文件 (>500行) | **{summary.get('large_source_files', 0)}** 个 |")
    lines.append(f"| 最大文件行数 | **{summary.get('largest_file_lines', 0)}** 行 |")
    lines.append(f"| 未排除目录 | **{summary.get('unprotected_dirs', 0)}** 个 |")
    lines.append(f"| 依赖膨胀文件数 | **{summary.get('bloat_file_count', 0)}** 个 |")
    lines.append("")

    # Token savings estimate
    if savings:
        lines.append("### Token 节省率预估")
        lines.append("")
        lines.append("| 指标 | 值 |")
        lines.append("|------|----|")
        lines.append(f"| 预估浪费总量 | **{savings.get('est_waste_total', 0):,}** tokens |")
        lines.append(f"| 每会话预估节省 | **{savings.get('est_savings_per_session', 0):,}** tokens |")
        lines.append(f"| 节省比例 | **{savings.get('est_savings_pct', 'N/A')}** |")
        lines.append(f"| 估算说明 | {savings.get('note', '')} |")
        lines.append("")

    # Large files list
    large_files = project_data.get("large_files", [])
    if large_files:
        lines.append("### 大型源文件 TOP 5")
        lines.append("")
        lines.append("| 文件 | 行数 | 预估 token/次 |")
        lines.append("|------|:---:|:---:|")
        for lf in large_files[:5]:
            lines.append(f"| `{lf.get('path', '')}` | {lf.get('lines', 0)} | {lf.get('est_tokens_per_read', 0):,} |")
        lines.append("")

    # Unprotected dirs
    dirs_info = project_data.get("directories", {})
    unprotected = dirs_info.get("unprotected", [])
    if unprotected:
        lines.append("### 未排除目录")
        lines.append("")
        lines.append(f"以下目录未被 `.gitignore` 排除，Agent 扫描时会遍历其中文件：")
        lines.append("")
        for d in unprotected:
            lines.append(f"- `{d}/`")
        lines.append("")
        lines.append("**建议**: 在 `.gitignore` 中添加上述目录以提升扫描效率。")

    return "\n".join(lines)
    """Generate Markdown report from runtime analysis data."""
    backend = data.get("backend", "unknown")
    findings = data.get("findings", [])
    total = data.get("total_findings", 0)
    by_sev = data.get("by_severity", {})
    tokens_wasted = data.get("total_tokens_wasted_est", 0)
    sessions = data.get("sessions_analyzed", 0)
    turns = data.get("turns_analyzed", 0)
    cross = data.get("cross_references", [])

    lines: list[str] = []
    lines.append("# 🔍 Token 消耗深度诊断报告")
    lines.append("")
    lines.append(f"**数据来源**: Session Store ({backend})  ")
    lines.append(f"**分析时间**: {data.get('analysis_time', '')}  ")
    lines.append(f"**分析范围**: {sessions} 个会话, {turns} 轮对话  ")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Summary
    lines.append("## 📊 概览")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|------|----|")
    lines.append(f"| 🔍 发现运行时问题 | **{total}** 个 |")
    lines.append(f"| 🔴 严重 | {by_sev.get('critical', 0)} |")
    lines.append(f"| 🟠 高优先级 | {by_sev.get('high', 0)} |")
    lines.append(f"| 🟡 中优先级 | {by_sev.get('medium', 0)} |")
    lines.append(f"| 🟢 低优先级 | {by_sev.get('low', 0)} |")
    lines.append(f"| 💸 预估浪费 | **{tokens_wasted:,} tokens** |")
    lines.append("")
    lines.append("---")
    lines.append("")

    if total == 0:
        lines.append("## ✅ 未发现运行时问题")
        lines.append("")
        lines.append("会话数据中未检测到已知的运行时 token 浪费模式。")
        return "\n".join(lines)

    # Findings
    lines.append("## 📋 运行时问题详情")
    lines.append("")
    for i, f in enumerate(sort_findings(findings), 1):
        sev = f.get("severity", "low")
        sev_icon = SEVERITY_ICON.get(sev, "⚪")
        lines.append(f"#### {i}. {sev_icon} [{f.get('id', '??')}] {f.get('detail', '')}")
        lines.append("")
        if f.get("session_id"):
            lines.append(f"**会话**: `{f['session_id']}`  ")
        if f.get("tokens_wasted_est", 0) > 0:
            lines.append(f"**预估浪费**: {f['tokens_wasted_est']:,} tokens  ")
        if f.get("suggestion"):
            lines.append(f"**建议**: {f['suggestion']}  ")
        lines.append("")

    # Cross references
    if cross:
        lines.append("---")
        lines.append("## 🔗 交叉对比发现")
        lines.append("")
        for c in cross:
            lines.append(f"- {c.get('detail', '')}")
        lines.append("")

    lines.append("---")
    lines.append(f"*报告由 Saving-tokens-skill 生成 | {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    return "\n".join(lines)


def generate_deep_report(static_data: dict, runtime_data: dict) -> str:
    """Generate combined static + runtime deep report."""
    static_findings = static_data.get("findings", [])
    runtime_findings = runtime_data.get("findings", [])
    static_summary = static_data.get("summary", {})
    runtime_by_sev = runtime_data.get("by_severity", {})
    tokens_wasted = runtime_data.get("total_tokens_wasted_est", 0)
    cross = runtime_data.get("cross_references", [])

    lines: list[str] = []
    lines.append("# 🔍 Token 消耗深度诊断报告（静态 + 运行时）")
    lines.append("")

    # Combined summary
    total_static = static_summary.get("total_findings", 0)
    total_runtime = runtime_data.get("total_findings", 0)
    total_combined = total_static + total_runtime

    lines.append("## 📊 综合概览")
    lines.append("")
    lines.append("| 维度 | 发现问题 |")
    lines.append("|------|:------:|")
    lines.append(f"| 📁 静态配置 | {total_static} |")
    lines.append(f"| ⚡ 运行时行为 | {total_runtime} |")
    lines.append(f"| **合计** | **{total_combined}** |")
    if tokens_wasted > 0:
        lines.append(f"| 💸 预估 token 浪费 | **{tokens_wasted:,}** |")
    lines.append("")

    # Static section
    if total_static > 0:
        lines.append("---")
        lines.append("## 📁 静态配置问题")
        lines.append("")
        sorted_s = sort_findings(static_findings)
        for i, f in enumerate(sorted_s, 1):
            sev = f.get("severity", "low")
            icon = SEVERITY_ICON.get(sev, "⚪")
            fname = Path(f.get("file", "")).name
            lines.append(f"#### {i}. {icon} [{f.get('id', '??')}] {fname}")
            lines.append(f"**问题**: {f.get('detail', '')}  ")
            if f.get("est_savings"):
                lines.append(f"**预估节省**: {f.get('est_savings', '')}  ")
            lines.append(f"**建议**: {f.get('suggestion', '')}  ")
            lines.append("")
    else:
        lines.append("## 📁 静态配置")
        lines.append("")
        lines.append("✅ 未检测到静态配置问题。")
        lines.append("")

    # Runtime section
    if total_runtime > 0:
        lines.append("---")
        lines.append("## ⚡ 运行时行为问题")
        lines.append("")
        sorted_r = sort_findings(runtime_findings)
        for i, f in enumerate(sorted_r, 1):
            sev = f.get("severity", "low")
            icon = SEVERITY_ICON.get(sev, "⚪")
            lines.append(f"#### {i}. {icon} [{f.get('id', '??')}] {f.get('detail', '')}")
            if f.get("session_id"):
                lines.append(f"**会话**: `{f['session_id']}`  ")
            if f.get("tokens_wasted_est", 0) > 0:
                lines.append(f"**预估浪费**: {f['tokens_wasted_est']:,} tokens  ")
            if f.get("suggestion"):
                lines.append(f"**建议**: {f['suggestion']}  ")
            lines.append("")
    else:
        lines.append("## ⚡ 运行时行为")
        lines.append("")
        lines.append("✅ 未检测到运行时 token 浪费模式。")
        lines.append("")

    # Cross references
    if cross:
        lines.append("---")
        lines.append("## 🔗 交叉对比发现")
        lines.append("")
        for c in cross:
            lines.append(f"- {c.get('detail', '')}")
        lines.append("")

    lines.append("---")
    lines.append(f"*报告由 Saving-tokens-skill 生成 | {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
