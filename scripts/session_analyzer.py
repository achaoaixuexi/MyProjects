"""
Saving-tokens-skill — Session Analyzer (Phase 2)
=================================================
Analyzes Copilot session store data to identify runtime token waste patterns.
Cross-references with static analysis findings for comprehensive diagnostics.

This script is designed to be used BY the Copilot agent, not run standalone.
The agent queries session data via copilot_sessionStoreSql, then feeds the
results to this script for analysis.

Usage:
    python session_analyzer.py <session_data.json> [-o output.json]
                              [--static-result static_scan.json]
                              [--deep]

Input JSON format (what the agent should collect via copilot_sessionStoreSql):
{
    "backend": "local" | "cloud",
    "sessions": [...],       // from sessions table
    "turns": [...],          // from turns table (optional, for deep mode)
    "session_files": [...],  // from session_files table (optional)
    "checkpoints": [...],    // from checkpoints table (optional)
    "events": [...]          // from events table (cloud only, for token data)
}
"""

import json
import argparse
import sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from typing import Any

from common import safe_int, safe_float, safe_output_path


# ---------------------------------------------------------------------------
# Pattern detectors
# ---------------------------------------------------------------------------

class SessionFinding:
    """A runtime token waste finding."""
    def __init__(self, pattern_id: str, severity: str, detail: str,
                 session_id: str = "", tokens_wasted: int = 0,
                 suggestion: str = ""):
        self.id = pattern_id
        self.severity = severity
        self.detail = detail
        self.session_id = session_id
        self.tokens_wasted = tokens_wasted
        self.suggestion = suggestion

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "severity": self.severity,
            "detail": self.detail,
            "session_id": self.session_id,
            "tokens_wasted_est": self.tokens_wasted,
            "est_savings": f"~{self.tokens_wasted:,} tokens wasted" if self.tokens_wasted > 0 else "",
            "suggestion": self.suggestion,
        }


def detect_long_sessions_without_compaction(data: dict) -> list[SessionFinding]:
    """RP-01: Sessions with many turns but no compaction checkpoints."""
    findings = []
    sessions = data.get("sessions", [])
    checkpoints = data.get("checkpoints", [])
    turns = data.get("turns", [])

    # Build maps
    cp_session_ids = {c.get("session_id", "") for c in checkpoints}
    turn_count_by_session: dict[str, int] = {}
    for t in turns:
        sid = t.get("session_id", "")
        turn_count_by_session[sid] = turn_count_by_session.get(sid, 0) + 1

    for s in sessions:
        sid = s.get("id", "")
        turn_count = turn_count_by_session.get(sid, safe_int(s.get("turn_count", 0)))
        if turn_count >= 20 and sid not in cp_session_ids:
            # Estimate wasted tokens: long context without compaction
            est_waste = (turn_count - 10) * 2000  # rough: 2000 tokens per extra turn
            findings.append(SessionFinding(
                "RP-01", "high",
                f"会话共 {turn_count} 轮但从未执行 compaction，上下文持续膨胀",
                session_id=sid,
                tokens_wasted=est_waste,
                suggestion=f"在第 10-15 轮左右使用 /compact 或开启自动压缩"
            ))
    return findings


def detect_late_compaction(data: dict) -> list[SessionFinding]:
    """RP-02: Sessions where first compaction happened very late."""
    findings = []
    sessions = {s.get("id", ""): s for s in data.get("sessions", [])}
    checkpoints = data.get("checkpoints", [])
    turns = data.get("turns", [])

    turn_count_by_session: dict[str, int] = {}
    for t in turns:
        sid = t.get("session_id", "")
        turn_count_by_session[sid] = turn_count_by_session.get(sid, 0) + 1

    # Group checkpoints by session, find first checkpoint number
    first_cp: dict[str, dict] = {}
    for c in checkpoints:
        sid = c.get("session_id", "")
        cp_num = safe_int(c.get("checkpoint_number", 999))
        if sid not in first_cp or cp_num < safe_int(first_cp[sid].get("checkpoint_number", 999)):
            first_cp[sid] = c

    for sid, cp in first_cp.items():
        cp_num = safe_int(cp.get("checkpoint_number", 0))
        turn_count = turn_count_by_session.get(sid, 0)
        if turn_count > 0 and cp_num > turn_count * 0.6:
            est_waste = int((cp_num - turn_count * 0.3) * 1500)
            findings.append(SessionFinding(
                "RP-02", "medium",
                f"首次 compaction 在第 {cp_num} 轮（总 {turn_count} 轮），占比 {cp_num/turn_count*100:.0f}%，太晚了",
                session_id=sid,
                tokens_wasted=max(0, est_waste),
                suggestion="建议在第 25%-30% 轮次处触发首次 compaction"
            ))
    return findings


def detect_input_output_imbalance(data: dict) -> list[SessionFinding]:
    """RP-03: Sessions where input tokens vastly outnumber output tokens."""
    findings = []
    events = data.get("events", [])
    if not events:
        return findings  # local backend, no token data

    # Group by session
    session_tokens: dict[str, dict] = {}
    for e in events:
        if e.get("type") != "assistant.usage":
            continue
        sid = e.get("session_id", "")
        if sid not in session_tokens:
            session_tokens[sid] = {"input": 0, "output": 0}
        session_tokens[sid]["input"] += safe_int(e.get("usage_input_tokens", 0))
        session_tokens[sid]["output"] += safe_int(e.get("usage_output_tokens", 0))

    for sid, tokens in session_tokens.items():
        inp = tokens["input"]
        out = tokens["output"]
        if inp > 0 and out > 0 and inp / out > 10:
            findings.append(SessionFinding(
                "RP-03", "high",
                f"输入/输出 token 比 {inp/out:.1f}:1，上下文严重膨胀",
                session_id=sid,
                tokens_wasted=inp - out * 5,
                suggestion="精简单次会话的任务范围，或使用 /compact 压缩上下文"
            ))
    return findings


def detect_repeated_file_reads(data: dict) -> list[SessionFinding]:
    """RP-04: Same file read many times in one session."""
    findings = []
    session_files = data.get("session_files", [])

    # Group by (session_id, file_path)
    from collections import defaultdict
    file_groups: dict[tuple, list] = defaultdict(list)
    for f in session_files:
        key = (f.get("session_id", ""), f.get("file_path", ""))
        file_groups[key].append(f)

    for (sid, fpath), entries in file_groups.items():
        if len(entries) >= 5:
            findings.append(SessionFinding(
                "RP-04", "medium",
                f"文件 `{fpath}` 在同一会话中被读取 {len(entries)} 次",
                session_id=sid,
                tokens_wasted=(len(entries) - 2) * 500,
                suggestion="将频繁读取的文件内容缓存到 session memory 或一次性读取大范围"
            ))
    return findings


def detect_oversized_user_messages(data: dict) -> list[SessionFinding]:
    """RP-05: Excessively long user messages that should be file references."""
    findings = []
    turns = data.get("turns", [])

    for t in turns:
        msg = t.get("user_message", "") or t.get("user_content", "")
        if len(msg) > 3000:
            findings.append(SessionFinding(
                "RP-05", "medium",
                f"用户消息过长（{len(msg)} 字符），建议使用文件引用替代",
                session_id=t.get("session_id", ""),
                tokens_wasted=len(msg) // 2,  # rough estimate
                suggestion="将大段代码/文本保存为文件后使用 @file 引用，而非直接粘贴"
            ))
    return findings[:10]  # Limit to avoid overwhelming


def detect_token_heavy_sessions(data: dict) -> list[SessionFinding]:
    """RP-06: Sessions with exceptionally high token consumption."""
    findings = []
    events = data.get("events", [])
    if not events:
        return findings

    session_tokens: dict[str, int] = {}
    for e in events:
        if e.get("type") != "assistant.usage":
            continue
        sid = e.get("session_id", "")
        session_tokens[sid] = session_tokens.get(sid, 0) + safe_int(e.get("usage_input_tokens", 0)) + safe_int(e.get("usage_output_tokens", 0))

    if not session_tokens:
        return findings

    avg_tokens = sum(session_tokens.values()) / len(session_tokens)
    for sid, total in session_tokens.items():
        if total > avg_tokens * 3:
            findings.append(SessionFinding(
                "RP-06", "high",
                f"会话消耗 {total:,} tokens，是平均值的 {total/avg_tokens:.1f} 倍",
                session_id=sid,
                tokens_wasted=max(0, total - int(avg_tokens * 2)),
                suggestion="考虑将此会话拆分为多个小会话，或使用子代理分担复杂任务"
            ))
    return findings


# ---------------------------------------------------------------------------
# Cross-reference with static findings
# ---------------------------------------------------------------------------

def cross_reference(runtime_findings: list[dict], static_findings: list[dict]) -> list[dict]:
    """Cross-reference runtime findings with static anti-patterns."""
    insights = []

    # If static scan found applyTo wildcard issues
    static_ids = {f.get("id") for f in static_findings}
    runtime_ids = {f.get("id") for f in runtime_findings}

    if "AP-01" in static_ids and "RP-03" in runtime_ids:
        insights.append({
            "type": "cross_reference",
            "detail": "静态扫描发现 applyTo: '**'，运行时确认输入 token 膨胀。修复 applyTo 可能显著改善。",
            "static_finding": "AP-01",
            "runtime_finding": "RP-03",
        })

    if "AP-06" in static_ids and "RP-01" in runtime_ids:
        insights.append({
            "type": "cross_reference",
            "detail": "always-on instructions 过大 + 未使用 compaction，双重上下文膨胀。精简 instructions 并启用压缩。",
            "static_finding": "AP-06",
            "runtime_finding": "RP-01",
        })

    return insights


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def _filter_sessions(data: dict, session_ids: list[str]) -> dict:
    """Return a copy of *data* containing only the listed session_ids."""
    sid_set = set(session_ids)
    return {
        **data,
        "sessions": [s for s in data.get("sessions", [])
                      if s.get("id", "") in sid_set],
        "turns": [t for t in data.get("turns", [])
                   if t.get("session_id", "") in sid_set],
        "session_files": [f for f in data.get("session_files", [])
                           if f.get("session_id", "") in sid_set],
        "checkpoints": [c for c in data.get("checkpoints", [])
                         if c.get("session_id", "") in sid_set],
        "events": [e for e in data.get("events", [])
                    if e.get("session_id", "") in sid_set],
    }


def analyze(data: dict, static_findings: list[dict] | None = None,
            use_cache: bool = True) -> dict:
    """Run all runtime analyses and return structured results."""
    backend = data.get("backend", "unknown")
    all_findings: list[dict] = []

    # ── Session-level cache: skip already-analysed sessions ──
    sessions = data.get("sessions", [])
    if use_cache and sessions:
        from cache import SessionCache
        sc = SessionCache(Path.cwd())
        all_ids = [s.get("id", "") for s in sessions]
        new_ids = [sid for sid in all_ids if not sc.is_analyzed(sid)]
        if not new_ids and all_ids:
            # All sessions already analysed
            return {
                "backend": backend,
                "analysis_time": datetime.now().isoformat(),
                "findings": [],
                "total_findings": 0,
                "by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0},
                "total_tokens_wasted_est": 0,
                "cross_references": [],
                "sessions_analyzed": len(all_ids),
                "turns_analyzed": len(data.get("turns", [])),
                "events_analyzed": len(data.get("events", [])),
                "cached": True,
            }
        # Filter data for new sessions only
        if new_ids and len(new_ids) < len(all_ids):
            data = _filter_sessions(data, new_ids)
        sc.mark_analyzed_batch(all_ids)

    detectors = [
        detect_long_sessions_without_compaction,
        detect_late_compaction,
        detect_input_output_imbalance,
        detect_repeated_file_reads,
        detect_oversized_user_messages,
        detect_token_heavy_sessions,
    ]

    for detector in detectors:
        results = detector(data)
        all_findings.extend(r.to_dict() for r in results)

    # Severity summary
    severity_count = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in all_findings:
        sev = f.get("severity", "low")
        severity_count[sev] = severity_count.get(sev, 0) + 1

    total_wasted = sum(f.get("tokens_wasted_est", 0) for f in all_findings)

    # Cross-reference
    cross = []
    if static_findings:
        cross = cross_reference(all_findings, static_findings)

    return {
        "backend": backend,
        "analysis_time": datetime.now().isoformat(),
        "findings": all_findings,
        "total_findings": len(all_findings),
        "by_severity": severity_count,
        "total_tokens_wasted_est": total_wasted,
        "cross_references": cross,
        "sessions_analyzed": len(data.get("sessions", [])),
        "turns_analyzed": len(data.get("turns", [])),
        "events_analyzed": len(data.get("events", [])),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Saving-tokens-skill — 运行时 Session 数据分析"
    )
    parser.add_argument("input", help="session 数据 JSON 文件")
    parser.add_argument("-o", "--output", help="输出 JSON 文件路径")
    parser.add_argument("--static-result", help="静态扫描结果 JSON（用于交叉对比）")
    parser.add_argument("--pretty", action="store_true", help="格式化输出")
    args = parser.parse_args()

    try:
        with open(args.input, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"错误: 文件不存在 — {args.input}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"错误: JSON 解析失败 — {e}", file=sys.stderr)
        sys.exit(1)

    static_findings = None
    if args.static_result:
        try:
            with open(args.static_result, "r", encoding="utf-8") as f:
                static_data = json.load(f)
            static_findings = static_data.get("findings", [])
        except Exception:
            pass

    result = analyze(data, static_findings)
    indent = 2 if args.pretty else None

    if args.output:
        try:
            out = safe_output_path(args.output, base_dir=str(Path.cwd()))
        except ValueError as e:
            print(f"错误: {e}", file=sys.stderr)
            sys.exit(1)
        with open(str(out), "w", encoding="utf-8") as f:
            json.dump(result, f, indent=indent, ensure_ascii=False)
        print(f"分析完成。发现 {result['total_findings']} 个运行时问题。结果已保存到 {args.output}")
    else:
        print(json.dumps(result, indent=indent, ensure_ascii=False))


if __name__ == "__main__":
    main()
