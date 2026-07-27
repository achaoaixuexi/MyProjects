"""
Saving-tokens-skill — Auto-Fix Engine
======================================
Reads scanner findings and applies safe, deterministic fixes.
Dangerous operations require --force or generate manual-fix suggestions.

Safety rules:
  - --dry-run: preview only, no changes
  - Default: only fix LOW severity + deterministic patterns
  - --interactive: prompt before each fix
  - --force: apply all safe fixes without prompt

Usage:
    python fixer.py scan_result.json [--dry-run] [--interactive] [--force]
"""

import json
import argparse
import re
import sys
import shutil
import os
from pathlib import Path
from datetime import datetime
from typing import Any

from common import safe_output_path


# ---------------------------------------------------------------------------
# Smart description truncation helpers (used by fix_long_description)
# ---------------------------------------------------------------------------

# Entities that should be preserved when truncating descriptions
# ── P0-2: Chinese entities + P1-3: precompiled patterns ──
_ENTITY_PATTERNS: list[tuple["re.Pattern[str]", str]] = [
    # ── English / ASCII entities ──
    (re.compile(r'\b\d{4}-\d{2}-\d{2}\b'), 'date'),                # 2026-07-23
    (re.compile(r'\b\d{2}/\d{2}/\d{4}\b'), 'date'),                 # 07/23/2026
    (re.compile(r'https?://[^\s,;.!?)\]}<>"]+'), 'url'),
    (re.compile(r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b'), 'email'),
    (re.compile(r'`[^`]+`'), 'code'),
    (re.compile(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b'), 'camel'),     # CamelCase
    (re.compile(r'\b[A-Z]{2,}(?:_[A-Z]{2,})*\b'), 'acronym'),
    (re.compile(r'\bversion\s+\d+\.\d+(?:\.\d+)?\b'), 'version'),
    # ── P0-2: Chinese entities ──
    (re.compile(r'\d{4}年\d{1,2}月\d{1,2}日'), 'cn_date'),         # 2026年7月24日
    (re.compile(r'第\d+(?:\.\d+)*版'), 'cn_version'),               # 第3版, 第2.0版
    (re.compile(r'[「「]([^」」]+)[」」]'), 'cn_quote_term'),          # 「诊断优化」
    (re.compile(r'v\d+\.\d+(?:\.\d+)?'), 'cn_version_v'),           # v2.0.0
    (re.compile(r'[《]([^》]+)[》]'), 'cn_book_title'),               # 《SKILL.md规范》
    # ── Issue2-Fix: technical detail patterns ──
    (re.compile(r'\b\d{2,6}\s*(?:ms|s|sec|min|h|hour)s?\b'), 'timeout'),  # 5000ms, 30s, 5min
    (re.compile(r'\b(?:max|min|pool|timeout|retry|limit|size|ttl|port)\w*\s*[=:]\s*\d+\b'), 'config'),  # pool_size=20
    (re.compile(r'\b\d+\s*x\b'), 'multiplier'),  # 3x faster
]

# ── P0-1: code-fence / structured-data bracket safety ──
_STRUCT_PAIRS: list[tuple[str, str, str]] = [
    ('(', ')', 'paren'),
    ('[', ']', 'bracket'),
    ('{', '}', 'brace'),
]
_DEEP_STRUCT_PAIRS: list[tuple[str, str]] = [
    ('```', '```'),   # code fence
    ('$$', '$$'),     # display LaTeX
]


def _find_safe_cut(text: str, cut_pos: int, min_pos: int) -> int:
    """P0-1: Walk backward from *cut_pos* to avoid cutting inside
    code-fences, LaTeX display math, or other permanently-unbalanced
    structural markers."""
    # ── Code fence check ──
    fence_count = text[:cut_pos].count('```')
    if fence_count % 2 != 0:
        opening = text.rfind('```', min_pos, cut_pos)
        if opening > min_pos:
            before = text.rfind('\n', min_pos, opening)
            return before if before > min_pos else opening
    # ── Display LaTeX $$...$$ ──
    for op, cl in _DEEP_STRUCT_PAIRS:
        prefix = text[:cut_pos]
        if prefix.count(op) != prefix.count(cl):
            opening_pos = text.rfind(op, min_pos, cut_pos)
            if opening_pos > min_pos:
                space_before = text.rfind(' ', min_pos, opening_pos)
                return space_before if space_before > min_pos else opening_pos
    return cut_pos


# ── P1-2: adaptive max_len ──
def _adaptive_max_len(text_len: int, base: int = 180) -> int:
    """Return a context-appropriate max truncation length."""
    if text_len <= base:
        return text_len
    if text_len < 300:
        return base
    if text_len < 600:
        return min(base + 40, text_len - 20)   # medium: 220 chars
    return min(base + 80, text_len - 40)        # long: 260 chars


# ── P2-1: content-type detection & adaptive compression mode ──

_CODE_FENCE_RE = re.compile(r'```[\s\S]*?```')
_JSON_BRACE_RE = re.compile(r'[{[].*?[}\]]')
_LATEX_MATH_RE = re.compile(r'\$[^$]+\$')


def _detect_content_type(text: str) -> str:
    """Classify description text to choose the safest truncation mode.

    Returns one of: 'conservative' (code/JSON), 'math' (LaTeX), 'balanced'."""
    # Code fences present → conservative (preserve code block integrity)
    if _CODE_FENCE_RE.search(text):
        return 'conservative'
    # JSON-like structures dominate → conservative (preserve {} [] pairing)
    brace_content = len(_JSON_BRACE_RE.findall(text))
    if brace_content >= 2 and brace_content / max(len(text.split()), 1) > 0.05:
        return 'conservative'
    # LaTeX math delimiters present → math mode (space-only trimming)
    math_delims = text.count('$')
    if math_delims >= 2 and math_delims % 2 == 0:
        return 'math'
    return 'balanced'


def _smart_truncate(text: str, max_len: int | None = None) -> str:
    """Truncate description text at a smart boundary.

    P0-1: code-fence / JSON-brace safety via _find_safe_cut.
    P0-2: Chinese entity patterns in _ENTITY_PATTERNS.
    P1-1: secondary boundary search in _rescue_entities.
    P1-2: adaptive max_len based on original length.
    P1-3: precompiled regex + early exit + tightened windows.
    P2-1: content-type detection → conservative / math / balanced modes.
    """
    # ── P1-3: early exit ──
    if not text:
        return ""

    # ── P1-2: adaptive length ──
    if max_len is None:
        max_len = _adaptive_max_len(len(text))

    if len(text) <= max_len:
        return text

    # ── P2-1: content-type detection ──
    mode = _detect_content_type(text)

    # ── Math mode: space-only trimming, never cut inside $...$ ──
    if mode == 'math':
        # Find a safe space boundary near max_len, avoiding $ delimiters
        cut = text.rfind(' ', 0, max_len)
        if cut < int(max_len * 0.55):
            cut = max_len
        candidate = text[:cut]
        if candidate.count('$') % 2 != 0:
            # Inside math — extend to closing $
            closing = text.find('$', cut)
            if closing > 0 and closing - cut < 40:
                cut = closing + 1
        return text[:cut].rstrip() + "..."
    # ── Conservative mode: wider margin, skip boundary refinement ──
    if mode == 'conservative':
        max_len = min(max_len + max_len // 5, len(text) - 10)
    # ── Balanced mode (default): current optimised logic ──

    min_pos = int(max_len * 0.55)

    # ── 1) Baseline word-boundary cut ──
    best_cut = text.rfind(' ', 0, max_len)
    if best_cut < min_pos:
        best_cut = max_len

    # ── 2) P0-1: Structural safety ──
    best_cut = _find_safe_cut(text, best_cut, min_pos)

    # ── 3) Refine backward (P2-1: conservative skips refinement) ──
    if mode != 'conservative':
        search_start = max(best_cut - 20, min_pos)
        for sep in ('. ', '! ', '? '):
            pos = text.rfind(sep, search_start, best_cut)
            if pos > 0:
                candidate = text[:pos + 1]
                if candidate.count('(') <= candidate.count(')'):
                    best_cut = pos + 1
                    break
        if best_cut == text.rfind(' ', 0, max_len) or best_cut >= max_len:
            for sep in (', ', '; ', ': '):
                pos = text.rfind(sep, search_start, best_cut)
                if pos > 0:
                    best_cut = pos + 1
                    break

    # ── 4) Bracket safety — extend to matching close for all pair types ──
    candidate = text[:best_cut]
    for op, cl, _name in _STRUCT_PAIRS:
        depth = candidate.count(op) - candidate.count(cl)
        if depth > 0:
            search = best_cut
            while depth > 0 and search < len(text):
                ch = text[search]
                if ch == op:
                    depth += 1
                elif ch == cl:
                    depth -= 1
                search += 1
            if depth == 0:
                best_cut = search

    result = text[:best_cut].rstrip() + "..."

    # ── 5) Entity rescue ──
    result = _rescue_entities(text, result, max_len)

    return result


def _rescue_entities(original: str, truncated: str, max_len: int) -> str:
    """Extend truncated text if a key entity straddles the cut point.

    P1-1: After rescue, secondary boundary search within 20 chars.
    P1-3: Tightened windows (80→60 rescue, 40→20 boundary, 80→60 ext)."""
    base = truncated.rstrip(".")
    base_len = len(base)

    for pattern, _etype in _ENTITY_PATTERNS:
        for m in pattern.finditer(original):
            entity = m.group()
            ent_start = m.start()
            ent_end = m.end()

            # P1-3: tightened rescue window 80→60
            if base_len <= ent_start < base_len + 60:
                if entity not in base:
                    extended_end = ent_end

                    # P1-1: secondary boundary search (tightened 40→20)
                    remaining = original[ent_end:]
                    for sep in ('. ', '! ', '? ', ', ', '; ', ': '):
                        next_boundary = remaining.find(sep)
                        if 0 <= next_boundary < 20:
                            extended_end = ent_end + next_boundary + 1
                            break

                    if extended_end == ent_end:
                        next_space = original.find(' ', ent_end)
                        if 0 <= next_space - ent_end < 20:
                            extended_end = next_space

                    extended = original[:extended_end].rstrip()

                    while extended and not extended[-1].isalnum():
                        if extended[-1] in ('.', '!', '?', ',', ';', ':'):
                            break
                        extended = extended[:-1]

                    # P1-3: tightened max extension 80→60
                    if extended and len(extended) - base_len < 60:
                        return extended + "..."

    return truncated


def _fidelity_check(original: str, truncated: str) -> tuple[bool, str]:
    """Lightweight check: does the truncated description retain the core intent?

    Returns (pass, reason).
    Checks: 1) trigger-word preservation  2) entity retention rate
    3) minimum length safety.
    """
    trigger_words = [
        "use when", "使用", "diagnose", "诊断", "optimize", "优化",
        "search", "搜索", "generate", "生成", "analyze", "分析"
    ]
    orig_lower = original.lower()
    trunc_lower = truncated.lower()

    # Check 1: did we lose ALL trigger words?
    orig_triggers = [t for t in trigger_words if t in orig_lower]
    trunc_triggers = [t for t in orig_triggers if t in trunc_lower]
    if orig_triggers and not trunc_triggers:
        return False, f"所有触发词丢失: {orig_triggers}"

    # Check 2 (Issue3-Fix): entity retention rate
    orig_entity_count = 0
    trunc_entity_count = 0
    for pattern, _ in _ENTITY_PATTERNS:
        orig_entity_count += len(pattern.findall(original))
        trunc_entity_count += len(pattern.findall(truncated))
    if orig_entity_count > 0 and trunc_entity_count / orig_entity_count < 0.5:
        return False, f"实体保留率过低 ({trunc_entity_count}/{orig_entity_count})"

    # Check 3: is the truncated text extremely short compared to original?
    if len(truncated.rstrip(".")) < min(30, len(original) * 0.15):
        return False, "截断后文本过短，可能丢失核心语义"

    return True, "ok"


# ---------------------------------------------------------------------------
# Fix definitions
# ---------------------------------------------------------------------------

class FixResult:
    def __init__(self, finding_id: str, action: str, detail: str, success: bool = True):
        self.finding_id = finding_id
        self.action = action
        self.detail = detail
        self.success = success


def fix_duplicate_instructions(findings: list[dict], dry_run: bool = False) -> list[FixResult]:
    """AP-03: Remove one of the duplicate instructions files."""
    results = []
    ap03_findings = [f for f in findings if f["id"] == "AP-03"]

    if not ap03_findings:
        return results

    # Find copilot-instructions.md vs AGENTS.md
    copilot_files = [f for f in ap03_findings if "copilot-instructions.md" in f.get("file", "")]
    agents_files = [f for f in ap03_findings if "AGENTS.md" in f.get("file", "")]

    if agents_files:
        for f in agents_files:
            filepath = f["file"]
            if dry_run:
                results.append(FixResult("AP-03", "[DRY-RUN] 将删除", filepath))
            else:
                try:
                    # Rename to .bak instead of deleting
                    backup = filepath + ".bak"
                    shutil.move(filepath, backup)
                    results.append(FixResult("AP-03", "已重命名为 .bak", filepath))
                except (OSError, PermissionError, FileNotFoundError) as e:
                    results.append(FixResult("AP-03", f"修复失败: {e}", filepath, success=False))

    return results


def fix_long_description(findings: list[dict], dry_run: bool = False, interactive: bool = False) -> list[FixResult]:
    """AP-12: Shorten overly long descriptions with entity-aware truncation.

    Uses _smart_truncate() to preserve sentence/clause boundaries, avoid
    bracket cuts, and rescue key entities (dates, URLs, code terms, acronyms).
    A lightweight _fidelity_check() verifies that core trigger-words survive.
    Falls back to conservative truncation on fidelity failure.
    """
    results = []
    ap12_findings = [f for f in findings if f["id"] == "AP-12"]

    for f in ap12_findings[:5]:  # Limit to 5 files
        filepath = f["file"]
        if not filepath.endswith("SKILL.md") and not filepath.endswith(".md"):
            continue

        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                content = fh.read()

            # Find the description in frontmatter
            fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
            if not fm_match:
                continue

            fm = fm_match.group(1)
            # Try to extract the description — capture full line(s) for safe replacement
            #   - inline string:  description: "text"\n
            #   - block scalar:   description: |\n  Line one\n  Line two\n
            desc_line = re.search(
                r'(description:\s*["\']?)(.+?)(["\']?\s*\n)', fm)
            is_block = False
            if not desc_line:
                desc_line = re.search(
                    r'(description:\s*[|>][-+]?\s*\n)((?:\s{2,}.+\n?)+)', fm)
                is_block = True
            if not desc_line:
                continue

            preamble = desc_line.group(1)      # 'description: "' or 'description: |\n'
            old_desc = desc_line.group(2).strip()
            trailer = '' if is_block else desc_line.group(3)  # '"\n' or ''

            old_full = desc_line.group(0)       # full 'description: "old text"\n'
            if len(old_desc) <= 200:
                continue

            # ── Smart truncation ──
            new_desc = _smart_truncate(old_desc)

            # ── Fidelity check ──
            passed, reason = _fidelity_check(old_desc, new_desc)
            if not passed:
                # Fall back to conservative: keep first 250 chars at word boundary
                fallback = old_desc[:250].rsplit(" ", 1)[0] + "..."
                results.append(FixResult("AP-12",
                    f"⚠️ 保真度校验未通过({reason})，回退到保守截断: {len(old_desc)}→{len(fallback)} 字符",
                    filepath))
                new_desc = fallback

            if dry_run:
                results.append(FixResult("AP-12",
                    f"[DRY-RUN] 将精简 description: {len(old_desc)}→{len(new_desc)} 字符",
                    filepath))
            else:
                new_full = preamble + new_desc + trailer
                new_content = content.replace(old_full, new_full, 1)
                # Verify replacement succeeded (Issue4-Fix)
                if new_content == content:
                    results.append(FixResult("AP-12",
                        "修复失败: 替换未命中（description 文本在全文中不唯一或格式不匹配）",
                        filepath, success=False))
                    continue
                with open(filepath, "w", encoding="utf-8") as fh:
                    fh.write(new_content)
                results.append(FixResult("AP-12",
                    f"已精简 description: {len(old_desc)}→{len(new_desc)} 字符",
                    filepath))
        except (OSError, PermissionError, FileNotFoundError) as e:
            results.append(FixResult("AP-12", f"修复失败: {e}", filepath, success=False))

    return results


def generate_manual_fix_suggestions(findings: list[dict]) -> str:
    """Generate a manual fix guide for findings that can't be auto-fixed."""
    lines = ["# 手动修复建议", "",
              f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}", "",
              "以下问题无法自动修复，请手动处理：", ""]

    by_id: dict[str, list] = {}
    for f in findings:
        fid = f["id"]
        if fid not in by_id:
            by_id[fid] = []
        by_id[fid].append(f)

    if "AP-01" in by_id:
        lines.append("## AP-01: applyTo 全量匹配")
        lines.append("")
        lines.append("将 `applyTo: '**'` 改为精确的 glob 模式。")
        lines.append("```yaml")
        lines.append("# 修改前")
        lines.append("applyTo: \"**\"")
        lines.append("")
        lines.append("# 修改后（示例）")
        lines.append("applyTo: \"**/*.py\"         # 只匹配 Python 文件")
        lines.append("applyTo: [\"src/api/**\", \"src/models/**\"]  # 只匹配特定目录")
        lines.append("```")
        lines.append("")
        for f in by_id["AP-01"]:
            lines.append(f"- `{f['file']}`")
        lines.append("")

    if "AP-02" in by_id:
        lines.append("## AP-02: 拆分大型 SKILL.md")
        lines.append("")
        lines.append("将 >500 行的 SKILL.md 按章节拆分为 references/ 子文件。")
        lines.append("```")
        lines.append("skill-name/")
        lines.append("├── SKILL.md          # <200 行，核心流程")
        lines.append("└── references/")
        lines.append("    ├── advanced.md   # 高级用法")
        lines.append("    └── examples.md   # 示例")
        lines.append("```")
        lines.append("")
        for f in by_id["AP-02"]:
            lines.append(f"- `{f['file']}`")
        lines.append("")

    if "AP-04" in by_id:
        lines.append("## AP-04: 优化 description 字段")
        lines.append("")
        lines.append("使用 'Use when: ...' 格式重写 description，添加触发关键词。")
        lines.append("")
        for f in by_id["AP-04"][:5]:
            lines.append(f"- `{f['file']}`")
        lines.append("")

    if "AP-05" in by_id:
        lines.append("## AP-05: 精简 Agent tools")
        lines.append("")
        lines.append("只保留 Agent 角色必需的工具，移除不必要的 tools。")
        lines.append("")
        for f in by_id["AP-05"]:
            lines.append(f"- `{f['file']}`")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Saving-tokens-skill — 自动修复引擎"
    )
    parser.add_argument("scan_result", help="scanner.py 输出的 JSON 文件")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际修改文件")
    parser.add_argument("--interactive", action="store_true", help="交互模式，每次修改前确认")
    parser.add_argument("--force", action="store_true", help="强制执行所有安全修复")
    parser.add_argument("--manual-guide", type=str, help="生成手动修复指南文件路径")
    args = parser.parse_args()

    try:
        with open(args.scan_result, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"错误: 文件不存在 — {args.scan_result}", file=sys.stderr)
        sys.exit(1)

    findings = data.get("findings", [])
    if not findings:
        print("✅ 未发现问题，无需修复。")
        sys.exit(0)

    auto_fixable = sum(1 for f in findings if f["id"] in ("AP-03", "AP-12"))
    total = len(findings)

    print(f"发现 {total} 个问题，其中 {auto_fixable} 个可自动修复，{total - auto_fixable} 个需手动处理。")
    print()

    if args.dry_run:
        print("🔍 预览模式 — 不会修改任何文件\n")

    all_results: list[FixResult] = []

    # Auto-fix AP-03 (duplicate instructions)
    results = fix_duplicate_instructions(findings, dry_run=args.dry_run)
    all_results.extend(results)

    # Auto-fix AP-12 (long description) - only with --force or --interactive
    if args.force or args.interactive:
        results = fix_long_description(findings, dry_run=args.dry_run, interactive=args.interactive)
        all_results.extend(results)

    # Print results
    if all_results:
        success_count = sum(1 for r in all_results if r.success)
        print(f"\n修复结果: {success_count}/{len(all_results)} 成功\n")
        for r in all_results:
            icon = "✅" if r.success else "❌"
            print(f"  {icon} [{r.finding_id}] {r.action}")
            print(f"     文件: {r.detail}")
    else:
        print("没有自动修复被执行。使用 --force 或 --interactive 来执行更多修复。")

    # Generate manual fix guide
    if args.manual_guide:
        try:
            out = safe_output_path(args.manual_guide, base_dir=str(Path.cwd()))
        except ValueError as e:
            print(f"错误: {e}", file=sys.stderr)
            sys.exit(1)
        manual_findings = [f for f in findings if f["id"] not in ("AP-03",)]
        if manual_findings:
            guide = generate_manual_fix_suggestions(manual_findings)
            with open(str(out), "w", encoding="utf-8") as f:
                f.write(guide)
            print(f"\n手动修复指南已生成: {args.manual_guide}")

    print(f"\n💡 提示: 使用 --manual-guide fix_guide.md 生成手动修复指南")


if __name__ == "__main__":
    main()
