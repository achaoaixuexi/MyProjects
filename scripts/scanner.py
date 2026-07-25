"""
Saving-tokens-skill — Static Scanner
=====================================
Scans project directories for token-wasting anti-patterns in
VS Code Copilot / Workbuddy configuration files.

Usage:
    python scanner.py <target_dir> [-o output.json] [--platform copilot|workbuddy]
"""

import os
import re
import json
import sys
import argparse
from collections import defaultdict
from pathlib import Path
from datetime import datetime
from typing import Any

# Import shared utilities from common.py
from common import (
    safe_int, safe_float, count_lines, parse_frontmatter, safe_output_path
)

# count_total_lines still needed locally
def count_total_lines(filepath: str) -> int:
    """Count lines including blanks."""
    return count_lines(filepath, include_blank=True)


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------
# Directories to search for skills/agents/instructions
# NOTE: only top-level dirs — **/ glob covers subdirectories naturally
SEARCH_DIRS = [
    ".github",
    ".agents/skills",
    ".claude/skills",
]

WORKBUDDY_DIRS = [
    ".workbuddy/skills",
    ".workbuddy",
]

ALWAYS_ON_FILES = ["copilot-instructions.md", "AGENTS.md"]
WORKBUDDY_ALWAYS_ON = ["IDENTITY.md", "MEMORY.md", "SOUL.md", "BOOTSTRAP.md", "USER.md"]

# Files to ignore during scanning
IGNORE_PATTERNS = [".fallback.bak", "_bm_skillid_migration.json"]


def discover_files(root: Path, platform: str = "copilot",
                   max_depth: int = 5, max_files: int = 1000) -> dict[str, list[str]]:
    """Walk root and discover all relevant configuration files."""
    dirs = SEARCH_DIRS[:]
    if platform == "workbuddy":
        dirs.extend(WORKBUDDY_DIRS)

    # Use sets internally to avoid duplicates from overlapping globs
    found_sets: dict[str, set[str]] = {
        "skills": set(),
        "instructions": set(),
        "agents": set(),
        "prompts": set(),
        "always_on": set(),
    }

    for dirname in dirs:
        search_path = root / dirname
        if not search_path.exists():
            continue

        for rglob_pattern, key in [
            ("**/SKILL.md", "skills"),
            ("**/*.instructions.md", "instructions"),
            ("**/*.agent.md", "agents"),
            ("**/*.prompt.md", "prompts"),
        ]:
            for f in search_path.glob(rglob_pattern):
                fpath = str(f)
                # Depth filter — count path parts relative to root
                try:
                    rel = Path(fpath).relative_to(root)
                    if len(rel.parts) > max_depth:
                        continue
                except ValueError:
                    pass  # not relative to root — accept
                if any(pat in fpath for pat in IGNORE_PATTERNS):
                    continue
                found_sets[key].add(fpath)  # set ensures no duplicates

    # Always-on files
    always_on = ALWAYS_ON_FILES[:]
    if platform == "workbuddy":
        always_on = WORKBUDDY_ALWAYS_ON

    found_sets["always_on"] = set()
    for fname in always_on:
        for loc in [root / fname, root / ".github" / fname, root / ".workbuddy" / fname]:
            if loc.exists():
                found_sets["always_on"].add(str(loc))

    found = {}
    for k, v in found_sets.items():
        found[k] = sorted(v)[:max_files]
    return found


# ---------------------------------------------------------------------------
# Detection rules
# ---------------------------------------------------------------------------

class Finding:
    """A single anti-pattern finding."""
    def __init__(self, anti_pattern_id: str, severity: str, file_path: str,
                 line: int = 0, detail: str = "", suggestion: str = "",
                 est_savings: str = ""):
        self.id = anti_pattern_id
        self.severity = severity
        self.file = file_path
        self.line = line
        self.detail = detail
        self.suggestion = suggestion
        self.est_savings = est_savings

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "detail": self.detail,
            "suggestion": self.suggestion,
            "est_savings": self.est_savings,
            "tokens_wasted_est": 0,  # unified: runtime companion field
        }


def check_apply_to_wildcard(frontmatter: dict, filepath: str) -> Finding | None:
    """AP-01: applyTo: '**' or applyTo: **"""
    apply_to = frontmatter.get("applyTo")
    if apply_to is None:
        return None
    values = [apply_to] if isinstance(apply_to, str) else (apply_to if isinstance(apply_to, list) else [])
    for v in values:
        if isinstance(v, str) and v.strip() == "**":
            return Finding(
                "AP-01", "critical", filepath,
                detail="applyTo 设置为 '**'，该文件在每次文件操作时都会被加载到上下文",
                suggestion="改为精确的 glob 模式，如 '**/*.py' 或 ['src/api/**', 'src/models/**']",
                est_savings="每次对话 500-3000 token"
            )
    return None


def check_monolithic_skill(filepath: str) -> Finding | None:
    """AP-02: SKILL.md > threshold lines — always flag regardless of references."""
    if not filepath.endswith("SKILL.md"):
        return None
    line_count = count_total_lines(filepath)
    threshold = _thresholds.monolithic_skill_lines
    if line_count <= threshold:
        return None
    return Finding(
        "AP-02", "critical", filepath,
        detail=f"SKILL.md 共 {line_count} 行（超过 {threshold} 行阈值）",
        suggestion="将详细章节移入 references/ 子目录，SKILL.md 保留 <200 行的核心流程",
        est_savings="每次加载 2000-5000 token"
    )


def check_duplicate_instructions(found: dict) -> list[Finding]:
    """AP-03: Both copilot-instructions.md and AGENTS.md exist."""
    findings = []
    always_on = [Path(f) for f in found["always_on"]]
    has_copilot = any(p.name == "copilot-instructions.md" for p in always_on)
    has_agents = any(p.name == "AGENTS.md" for p in always_on)
    if has_copilot and has_agents:
        for p in always_on:
            if p.name in ("copilot-instructions.md", "AGENTS.md"):
                findings.append(Finding(
                    "AP-03", "critical", str(p),
                    detail="重复的 instructions 文件 — 与另一个文件共存导致内容重复加载",
                    suggestion="删除其中一个。推荐保留 copilot-instructions.md（VS Code 官方推荐）",
                    est_savings="消除 100% 重复内容"
                ))
    return findings


def check_vague_description(frontmatter: dict, filepath: str) -> Finding | None:
    """AP-04: Vague description field."""
    desc = frontmatter.get("description", "")
    if not desc or not isinstance(desc, str):
        return Finding(
            "AP-04", "high", filepath,
            detail="缺少 description 字段，agent 无法自动发现此配置",
            suggestion='添加 keyword-rich description，使用 "Use when..." 模式',
            est_savings="间接节省 500-2000 token/次"
        )
    if len(desc) < 50:
        return Finding(
            "AP-04", "high", filepath,
            detail=f"description 过短（{len(desc)} 字符），缺少触发关键词",
            suggestion='扩展 description，加入 "Use when: ..." 和具体场景关键词',
            est_savings="间接节省 500-2000 token/次"
        )
    desc_lower = desc.lower()
    has_use_when = "use when" in desc_lower or "使用" in desc
    has_keywords = len(desc.split()) >= 8
    if not has_use_when and not has_keywords:
        return Finding(
            "AP-04", "medium", filepath,
            detail="description 缺少 'Use when' 引导模式和足够的触发关键词",
            suggestion='使用 "Use when: doing X, handling Y" 格式',
            est_savings="间接节省 200-500 token/次"
        )
    return None


def check_swiss_army_agent(frontmatter: dict, filepath: str) -> Finding | None:
    """AP-05: tools list has 6+ entries."""
    tools = frontmatter.get("tools")
    if not tools or not isinstance(tools, list):
        return None
    if len(tools) >= 6:
        return Finding(
            "AP-05", "high", filepath,
            detail=f"tools 列表包含 {len(tools)} 个工具别名，Swiss-army agent 反模式",
            suggestion=f"精简 tools 到最小必要集合。当前: {tools}",
            est_savings="每次调用节省 200-500 token"
        )
    return None


def check_bloated_always_on(filepath: str) -> Finding | None:
    """AP-06: always-on instructions > threshold lines."""
    line_count = count_total_lines(filepath)
    threshold = _thresholds.bloated_always_on_lines
    if line_count > threshold:
        return Finding(
            "AP-06", "medium", filepath,
            detail=f"always-on instructions 共 {line_count} 行（>{threshold}），每次对话都会加载",
            suggestion="精简到 100 行以内，将场景规则拆分到 .github/instructions/*.instructions.md",
            est_savings="每次对话 500-2000 token"
        )
    return None


def check_no_progressive_loading(filepath: str) -> Finding | None:
    """AP-07: SKILL.md > threshold lines but no references/ dir."""
    if not filepath.endswith("SKILL.md"):
        return None
    line_count = count_total_lines(filepath)
    threshold = _thresholds.no_progressive_lines
    if line_count <= threshold:
        return None
    ref_dir = Path(filepath).parent / "references"
    if ref_dir.exists():
        return None
    return Finding(
        "AP-07", "medium", filepath,
        detail=f"SKILL.md 共 {line_count} 行（>{threshold}），建议拆分以利用渐进加载",
        suggestion="将非核心章节移入 references/ 子目录",
        est_savings="每次加载 500-1500 token"
    )


def check_large_skill(filepath: str) -> Finding | None:
    """AP-08: SKILL.md >= threshold lines."""
    if not filepath.endswith("SKILL.md"):
        return None
    line_count = count_total_lines(filepath)
    threshold = _thresholds.large_skill_lines
    if line_count >= threshold:
        return Finding(
            "AP-08", "medium", filepath,
            detail=f"SKILL.md 共 {line_count} 行（>={threshold}），在推荐范围内但仍有优化空间",
            suggestion="审查内容，将非核心流程移入 references/",
            est_savings="每次加载 200-1000 token"
        )
    return None


def check_missing_tools(frontmatter: dict, filepath: str) -> Finding | None:
    """AP-10: Agent with no tools declared."""
    if not filepath.endswith(".agent.md"):
        return None
    tools = frontmatter.get("tools")
    if tools is None:
        return Finding(
            "AP-10", "low", filepath,
            detail="Agent 未声明 tools 字段，使用默认工具集",
            suggestion="显式声明最小工具集，如 tools: [read, search]",
            est_savings="每次调用 50-200 token"
        )
    return None


def check_long_description(frontmatter: dict, filepath: str) -> Finding | None:
    """AP-12: description > threshold chars."""
    desc = frontmatter.get("description", "")
    threshold = _thresholds.long_description_chars
    if isinstance(desc, str) and len(desc) > threshold:
        return Finding(
            "AP-12", "low", filepath,
            detail=f"description 共 {len(desc)} 字符（>{threshold}），增加发现阶段 token 消耗",
            suggestion="精简到 200 字符以内，聚焦关键词",
            est_savings="每次发现阶段 20-50 token"
        )
    return None


def check_inline_code_blocks(filepath: str) -> Finding | None:
    """AP-13: Inline code blocks > 50 lines without external file reference."""
    if not (filepath.endswith(".md") or filepath.endswith(".instructions.md")):
        return None
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as fh:
            content = fh.read()
    except (FileNotFoundError, PermissionError):
        return None

    code_blocks = re.findall(r'```[\s\S]*?```', content)
    huge_blocks = [b for b in code_blocks if b.count('\n') > 50]
    if huge_blocks:
        return Finding(
            "AP-13", "high", filepath,
            detail=f"发现 {len(huge_blocks)} 个超大代码块（>50行），建议移至外部文件引用",
            suggestion="将大型代码示例保存为独立文件，在 SKILL.md 中用相对路径引用",
            est_savings="每次加载 1000-5000 token"
        )
    return None


def check_redundant_imports(filepath: str) -> Finding | None:
    """AP-14: Redundant import/installation instructions in multiple places."""
    if not (filepath.endswith(".md") or filepath.endswith(".instructions.md")):
        return None
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as fh:
            content = fh.read()
    except (FileNotFoundError, PermissionError):
        return None

    install_patterns = [r'pip install', r'npm install', r'go get', r'cargo install',
                        r'gem install', r'conda install', r'brew install',
                        r'import ', r'from .+ import', r'require\(']
    count = 0
    for pat in install_patterns:
        count += len(re.findall(pat, content, re.IGNORECASE))
    if count >= 5:
        return Finding(
            "AP-14", "medium", filepath,
            detail=f"发现 {count} 处 import/install 指令，可能存在冗余依赖说明",
            suggestion="将安装说明集中到一处（如 README.md 或单独的 SETUP.md），instruction 中用引用链接替代",
            est_savings="每次加载 200-1000 token"
        )
    return None


def check_excessive_comment_ratio(filepath: str) -> Finding | None:
    """AP-15: Comment lines ratio > 40% in instruction/skill files."""
    if not (filepath.endswith(".md") or filepath.endswith(".instructions.md")):
        return None
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as fh:
            lines = fh.readlines()
    except (FileNotFoundError, PermissionError):
        return None

    if len(lines) < 20:
        return None
    comment_lines = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('#') or stripped.startswith('//') or stripped.startswith('<!--'):
            comment_lines += 1
        elif stripped.startswith('>') and len(stripped) > 1:
            comment_lines += 1
    total_content = sum(1 for l in lines if l.strip())
    if total_content > 0 and comment_lines / total_content > 0.4:
        return Finding(
            "AP-15", "low", filepath,
            detail=f"注释行占比 {comment_lines/total_content*100:.0f}%（>40%），可能存在冗余解释",
            suggestion="将详细的解释性注释精简为关键说明，非必要的背景信息移至 references/",
            est_savings="每次加载 100-500 token"
        )
    return None


# ---------------------------------------------------------------------------
# Phase 3: Programming-project static anti-patterns  (AP-16 ~ AP-18)
# ---------------------------------------------------------------------------


def check_inline_documentation(filepath: str) -> Finding | None:
    """AP-09: Large inline documentation blocks in skill/instruction files."""
    if not (filepath.endswith(".md") or filepath.endswith(".instructions.md")):
        return None
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as fh:
            content = fh.read()
    except (FileNotFoundError, PermissionError):
        return None
    code_blocks = re.findall(r'```[\s\S]*?```', content)
    large_blocks = [b for b in code_blocks if b.count('\n') > 20]
    if len(large_blocks) >= 2:
        return Finding(
            "AP-09", "medium", filepath,
            detail=f"发现 {len(large_blocks)} 个大型代码块（>20行），可能存在内联文档冗余",
            suggestion="将大型文档/代码示例移入 references/ 或外部文档，使用链接引用",
            est_savings="按内联内容大小计算，每次加载 500-3000 token"
        )
    return None


_SOURCE_EXTS = {'.py', '.ts', '.tsx', '.js', '.jsx', '.go', '.rs', '.java',
                '.cs', '.cpp', '.c', '.rb', '.php', '.swift', '.kt'}


def check_monolithic_source(filepath: str) -> Finding | None:
    """AP-16: Single source file >1000 lines without modular split."""
    ext = Path(filepath).suffix
    if ext not in _SOURCE_EXTS:
        return None
    lc = count_total_lines(filepath)
    if lc > 1000:
        pct_str = f" ({lc/1000:.1f}x 推荐上限)"
        return Finding(
            "AP-16", "high", filepath,
            detail=f"单体源文件 {lc} 行" + pct_str + "，Agent 每次加载大量无关代码",
            suggestion="拆分为模块（<300 行/文件）或为 Agent 提供 API 摘要文件",
            est_savings="每次加载 2000-5000 token"
        )
    return None


def check_missing_gitignore_entries(root: Path) -> list[Finding]:
    """AP-17: Heavy directories not in .gitignore wasting agent scan time."""
    findings = []
    HEAVY_DIRS = ['node_modules', '.venv', 'venv', '__pycache__', 'dist',
                  'build', '.next', 'target', 'vendor', '.turbo', '.cache']
    gi = root / '.gitignore'
    if not gi.exists():
        present = [d for d in HEAVY_DIRS if (root / d).exists()]
        if present:
            findings.append(Finding(
                "AP-17", "critical", str(root),
                detail=f"项目无 .gitignore，Agent 将扫描 {len(present)} 个重量级目录",
                suggestion=f"创建 .gitignore 并添加: {', '.join(present[:5])}",
                est_savings="每次扫描 2000-8000 token"
            ))
        return findings

    try:
        ignored_content = gi.read_text(encoding='utf-8', errors='ignore')
    except (OSError, PermissionError):
        return findings
    missing = [d for d in HEAVY_DIRS if (root / d).exists() and d not in ignored_content]
    if missing:
        findings.append(Finding(
            "AP-17", "medium", str(gi),
            detail=f"重量级目录未被 .gitignore 排除: {missing}，Agent 会扫描这些目录",
            suggestion=f"在 .gitignore 中添加: {', '.join(missing)}",
            est_savings="每次扫描 500-3000 token"
        ))
    return findings


def check_config_duplication(found: dict) -> list[Finding]:
    """AP-18: Hard-coded config values repeated across multiple source files."""
    findings = []
    HARDCODE_RE = re.compile(
        r'(?:https?://[^\s"\')\]]+|(?:localhost|127\.0\.0\.1|0\.0\.0\.0):\d+'
        r'|(?:password|secret|api_key|token)\s*[:=]\s*["\'][^"\']{6,}["\'])',
        re.IGNORECASE)

    # Only scan source-code files (skills + instructions already covered by AP-09)
    candidates = found.get("skills", []) + found.get("instructions", []) + found.get("agents", [])
    value_files: dict[str, list[str]] = defaultdict(list)

    for fpath in candidates:
        ext = Path(fpath).suffix
        # For md files, extract code blocks
        if ext == '.md':
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as fh:
                    content = fh.read()
            except (FileNotFoundError, PermissionError):
                continue
            code_blocks = re.findall(r'```[\s\S]*?```', content)
            combined = '\n'.join(code_blocks)
        else:
            continue  # MD-only for now

        for m in HARDCODE_RE.finditer(combined):
            val = m.group()
            value_files[val].append(fpath)

    duplicated = {v: fs for v, fs in value_files.items() if len(fs) >= 2}
    if len(duplicated) >= 3:
        examples = list(duplicated.keys())[:3]
        findings.append(Finding(
            "AP-18", "low", "",
            detail=f"发现 {len(duplicated)} 个硬编码值在多个文件中重复（如 {', '.join(examples)}）",
            suggestion="将重复的配置值提取到单一配置文件或环境变量",
            est_savings="每次加载 200-500 token"
        ))
    return findings
    """AP-09: Large inline documentation blocks in skill/instruction files."""
    if not (filepath.endswith(".md") or filepath.endswith(".instructions.md")):
        return None
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as fh:
            content = fh.read()
    except (FileNotFoundError, PermissionError):
        return None

    # Detect code blocks (>20 lines) that look like documentation
    code_blocks = re.findall(r'```[\s\S]*?```', content)
    large_blocks = [b for b in code_blocks if b.count('\n') > 20]
    if len(large_blocks) >= 2:
        return Finding(
            "AP-09", "medium", filepath,
            detail=f"发现 {len(large_blocks)} 个大型代码块（>20行），可能存在内联文档冗余",
            suggestion="将大型文档/代码示例移入 references/ 或外部文档，使用链接引用",
            est_savings="按内联内容大小计算，每次加载 500-3000 token"
        )
    return None


def check_circular_handoff(found: dict) -> list[Finding]:
    """AP-11: Detect circular agent handoff references."""
    findings = []
    agent_refs: dict[str, set[str]] = {}

    for fpath in found.get("agents", []):
        fm = parse_frontmatter(fpath)
        agents_list = fm.get("agents", [])
        if isinstance(agents_list, list):
            agent_refs[fpath] = set(agents_list)

    # Check for mutual references (A→B and B→A)
    checked: set[tuple] = set()
    for a_path, a_refs in agent_refs.items():
        for b_path, b_refs in agent_refs.items():
            if a_path >= b_path:
                continue
            pair = (a_path, b_path)
            if pair in checked:
                continue
            checked.add(pair)

            a_name = Path(a_path).stem
            b_name = Path(b_path).stem
            a_refs_b = b_name in a_refs
            b_refs_a = a_name in b_refs

            if a_refs_b and b_refs_a:
                findings.append(Finding(
                    "AP-11", "high", a_path,
                    detail=f"Agent {a_name} 与 {b_name} 形成循环 handoff（互相引用）",
                    suggestion=f"解除循环：将其中一方的 agents 字段移除对方引用",
                    est_savings="防止灾难性循环消耗"
                ))
    return findings


# ---------------------------------------------------------------------------
# Workbuddy-specific checks
# ---------------------------------------------------------------------------

def check_workbuddy_fallback_bak(root: Path) -> list[Finding]:
    """WB-01: .fallback.bak residue files that may be loaded accidentally."""
    findings = []
    workbuddy_dir = root / ".workbuddy"
    if not workbuddy_dir.exists():
        return findings

    bak_files = list(workbuddy_dir.rglob("*.fallback.bak"))
    if len(bak_files) > 10:
        findings.append(Finding(
            "WB-01", "low", str(workbuddy_dir),
            detail=f"发现 {len(bak_files)} 个 .fallback.bak 备份文件，可能被误加载",
            suggestion="清理不需要的 .fallback.bak 文件以减小索引范围",
            est_savings="每次扫描/加载 50-200 token"
        ))
    return findings


def check_workbuddy_identity_bloat(filepath: str) -> Finding | None:
    """WB-02: IDENTITY.md / MEMORY.md / SOUL.md too large."""
    fname = Path(filepath).name
    if fname not in ("IDENTITY.md", "MEMORY.md", "SOUL.md", "BOOTSTRAP.md", "USER.md"):
        return None
    line_count = count_total_lines(filepath)
    if line_count > 100:
        return Finding(
            "WB-02", "high", filepath,
            detail=f"{fname} 共 {line_count} 行（>100），等效于 always-on instructions 反模式",
            suggestion=f"精简 {fname}，只保留每次对话都需要的核心信息",
            est_savings="每次对话 500-3000 token"
        )
    return None


def check_workbuddy_extra_frontmatter(frontmatter: dict, filepath: str) -> Finding | None:
    """WB-03: Extra Workbuddy frontmatter fields adding token overhead."""
    extra_fields = ["version", "tags", "category"]
    extras = [k for k in extra_fields if k in frontmatter]
    if extras:
        # Only flag if description is also long (compound issue)
        desc = frontmatter.get("description", "")
        if isinstance(desc, str) and len(desc) > 300:
            return Finding(
                "WB-03", "low", filepath,
                detail=f"Workbuddy 特有字段 ({', '.join(extras)}) + 长 description 叠加消耗",
                suggestion="考虑将 tags/category 信息整合到 description 中，减少重复字段",
                est_savings="每次发现阶段 10-30 token"
            )
    return None


# ---------------------------------------------------------------------------
# P3: Learning-based adaptive thresholds
# ---------------------------------------------------------------------------

class Thresholds:
    """Adjustable detection thresholds.  Defaults are the standard values.

    When *tighten()* is called with project baselines, thresholds are
    lowered (never raised) to better match the actual project norms,
    reducing false positives while keeping all true detections."""

    def __init__(self):
        self.monolithic_skill_lines = 500       # AP-02
        self.bloated_always_on_lines = 200      # AP-06
        self.no_progressive_lines = 150         # AP-07
        self.large_skill_lines = 200            # AP-08
        self.long_description_chars = 500       # AP-12
        self.skill_median_lines: float = 0.0
        self.desc_median_chars: float = 0.0
        self.learned = False

    def tighten(self, skill_median: float, desc_median: float,
                always_on_median: float) -> dict:
        """Tighten thresholds based on project-specific baselines.

        Only lowers thresholds — never raises above defaults.
        Returns a dict of changed values for reporting."""
        changes: dict[str, tuple[int, int]] = {}

        if skill_median > 0:
            # AP-02: monolithic = median * 3, capped at default
            new_ap02 = max(100, min(int(skill_median * 3), self.monolithic_skill_lines))
            if new_ap02 < self.monolithic_skill_lines:
                changes['AP-02'] = (self.monolithic_skill_lines, new_ap02)
                self.monolithic_skill_lines = new_ap02
            # AP-07: progressive = median * 1.5, capped at default
            new_ap07 = max(50, min(int(skill_median * 1.5), self.no_progressive_lines))
            if new_ap07 < self.no_progressive_lines:
                changes['AP-07'] = (self.no_progressive_lines, new_ap07)
                self.no_progressive_lines = new_ap07
            # AP-08: large = median * 2, capped at default
            new_ap08 = max(80, min(int(skill_median * 2), self.large_skill_lines))
            if new_ap08 < self.large_skill_lines:
                changes['AP-08'] = (self.large_skill_lines, new_ap08)
                self.large_skill_lines = new_ap08

        if always_on_median > 0:
            # AP-06: bloated always-on = median * 2, capped at default
            new_ap06 = max(60, min(int(always_on_median * 2), self.bloated_always_on_lines))
            if new_ap06 < self.bloated_always_on_lines:
                changes['AP-06'] = (self.bloated_always_on_lines, new_ap06)
                self.bloated_always_on_lines = new_ap06

        if desc_median > 0:
            # AP-12: long desc = median * 3, capped at default
            new_ap12 = max(100, min(int(desc_median * 3), self.long_description_chars))
            if new_ap12 < self.long_description_chars:
                changes['AP-12'] = (self.long_description_chars, new_ap12)
                self.long_description_chars = new_ap12

        if changes:
            self.learned = True
            self.skill_median_lines = skill_median
            self.desc_median_chars = desc_median
        return changes


def _compute_project_baselines(found: dict) -> dict:
    """Compute median file-line and description-length statistics from
    discovered files.  Used by adaptive-threshold tightening."""
    skill_lines = []
    always_on_lines = []
    desc_lengths = []

    for fpath in found.get("skills", []):
        lc = count_total_lines(fpath)
        if lc > 0:
            skill_lines.append(lc)
        fm = parse_frontmatter(fpath)
        desc = fm.get("description", "")
        if isinstance(desc, str) and desc:
            desc_lengths.append(len(desc))

    for fpath in found.get("always_on", []):
        lc = count_total_lines(fpath)
        if lc > 0:
            always_on_lines.append(lc)

    for fpath in found.get("instructions", []) + found.get("agents", []):
        fm = parse_frontmatter(fpath)
        desc = fm.get("description", "")
        if isinstance(desc, str) and desc:
            desc_lengths.append(len(desc))

    def _median(vals: list[int]) -> float:
        if not vals:
            return 0.0
        s = sorted(vals)
        n = len(s)
        if n % 2 == 0:
            return (s[n // 2 - 1] + s[n // 2]) / 2.0
        return float(s[n // 2])

    return {
        "skill_median": _median(skill_lines),
        "always_on_median": _median(always_on_lines),
        "desc_median": _median(desc_lengths),
    }


# ── Instantiate module-level thresholds ──
_thresholds = Thresholds()

def scan(target_dir: str, platform: str = "copilot",
         max_depth: int = 5, max_files: int = 1000,
         use_cache: bool = True, learn: bool = False) -> dict:
    """Run all checks and return structured results."""
    root = Path(target_dir).resolve()
    if not root.is_dir():
        return {"error": f"目录不存在: {target_dir}", "findings": [], "summary": {}}

    found = discover_files(root, platform, max_depth=max_depth, max_files=max_files)

    # ── P3: Learning-based threshold tightening ──
    threshold_info: dict | None = None
    if learn:
        baselines = _compute_project_baselines(found)
        changes = _thresholds.tighten(
            baselines["skill_median"],
            baselines["desc_median"],
            baselines["always_on_median"],
        )
        threshold_info = {
            "baselines": {k: round(v, 1) for k, v in baselines.items()},
            "adjusted_thresholds": {k: f"{old}→{new}" for k, (old, new) in changes.items()},
            "thresholds_applied": _thresholds.learned,
        }
    else:
        # Reset to defaults to avoid stale state from previous --learn runs
        _thresholds.__init__()

    findings: list[dict] = []

    # --- Structural checks (no frontmatter needed) ---

    for f in found["skills"]:
        result = check_monolithic_skill(f)
        if result:
            findings.append(result.to_dict())

    findings.extend(f.to_dict() for f in check_duplicate_instructions(found))

    for f in found["always_on"]:
        result = check_bloated_always_on(f)
        if result:
            findings.append(result.to_dict())

        if platform == "workbuddy":
            result = check_workbuddy_identity_bloat(f)
            if result:
                findings.append(result.to_dict())

    for f in found["skills"]:
        result = check_no_progressive_loading(f)
        if result:
            findings.append(result.to_dict())

    for f in found["skills"]:
        result = check_large_skill(f)
        if result:
            findings.append(result.to_dict())

    # --- Workbuddy-specific structural checks ---
    if platform == "workbuddy":
        findings.extend(f.to_dict() for f in check_workbuddy_fallback_bak(root))

    # AP-09: Inline documentation blocks
    for f in found["skills"] + found["instructions"]:
        result = check_inline_documentation(f)
        if result:
            findings.append(result.to_dict())

    # AP-11: Circular agent handoff
    findings.extend(f.to_dict() for f in check_circular_handoff(found))

    # AP-13: Inline huge code blocks
    for f in found["skills"] + found["instructions"]:
        result = check_inline_code_blocks(f)
        if result:
            findings.append(result.to_dict())

    # AP-14: Redundant import/install instructions
    for f in found["skills"] + found["instructions"] + found["always_on"]:
        result = check_redundant_imports(f)
        if result:
            findings.append(result.to_dict())

    # AP-15: Excessive comment ratio
    for f in found["skills"] + found["instructions"]:
        result = check_excessive_comment_ratio(f)
        if result:
            findings.append(result.to_dict())

    # AP-16: Monolithic source files
    for f in found["skills"] + found["instructions"]:
        result = check_monolithic_source(f)
        if result:
            findings.append(result.to_dict())

    # AP-17: Missing .gitignore entries
    findings.extend(f.to_dict() for f in check_missing_gitignore_entries(root))

    # AP-18: Hard-coded config duplication
    findings.extend(f.to_dict() for f in check_config_duplication(found))

    # --- Frontmatter-based checks ---
    all_md_files = found["skills"] + found["instructions"] + found["agents"] + found["prompts"] + found["always_on"]

    for filepath in all_md_files:
        fm = parse_frontmatter(filepath)
        if not fm:
            continue

        if filepath.endswith(".instructions.md"):
            result = check_apply_to_wildcard(fm, filepath)
            if result:
                findings.append(result.to_dict())

        result = check_vague_description(fm, filepath)
        if result:
            findings.append(result.to_dict())

        if filepath.endswith(".agent.md"):
            result = check_swiss_army_agent(fm, filepath)
            if result:
                findings.append(result.to_dict())

        result = check_missing_tools(fm, filepath)
        if result:
            findings.append(result.to_dict())

        result = check_long_description(fm, filepath)
        if result:
            findings.append(result.to_dict())

        if platform == "workbuddy":
            result = check_workbuddy_extra_frontmatter(fm, filepath)
            if result:
                findings.append(result.to_dict())

    # --- Summary ---
    severity_count = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        sev = f.get("severity", "low")
        severity_count[sev] = severity_count.get(sev, 0) + 1

    total = len(findings)
    summary = {
        "total_findings": total,
        "by_severity": severity_count,
        "platform": platform,
        "files_scanned": {
            "skills": len(found["skills"]),
            "instructions": len(found["instructions"]),
            "agents": len(found["agents"]),
            "prompts": len(found["prompts"]),
            "always_on": len(found["always_on"]),
        },
        "health_score": max(0, 100 - (
            severity_count["critical"] * 20 +
            severity_count["high"] * 10 +
            severity_count["medium"] * 5 +
            severity_count["low"] * 2
        )),
    }

    return {
        "target": str(root),
        "scan_time": datetime.now().isoformat(),
        "findings": findings,
        "summary": summary,
        "threshold_info": threshold_info,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Saving-tokens-skill — 静态扫描 token 浪费反模式"
    )
    parser.add_argument("target", help="要扫描的项目目录")
    parser.add_argument("-o", "--output", help="输出 JSON 文件路径（默认输出到 stdout）")
    parser.add_argument("--platform", choices=["copilot", "workbuddy"], default="copilot",
                        help="目标平台（默认 copilot）")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    parser.add_argument("--max-depth", type=int, default=5,
                        help="扫描目录最大深度（默认 5）")
    parser.add_argument("--max-files", type=int, default=1000,
                        help="扫描文件数量上限（默认 1000）")
    parser.add_argument("--cache", action="store_true", default=True,
                        help="启用文件级缓存以加速重复扫描（默认启用）")
    parser.add_argument("--no-cache", action="store_false", dest="cache",
                        help="禁用缓存，强制全量扫描")
    parser.add_argument("--learn", action="store_true", default=False,
                        help="启用学习型阈值：基于项目文件统计自动收紧检测阈值，减少误报")
    args = parser.parse_args()

    # Validate output path
    if args.output:
        try:
            out = safe_output_path(args.output, base_dir=str(Path.cwd()))
        except ValueError as e:
            print(f"错误: {e}", file=sys.stderr)
            sys.exit(1)

    result = scan(args.target, platform=args.platform,
                  max_depth=args.max_depth, max_files=args.max_files,
                  use_cache=args.cache, learn=args.learn)
    indent = 2 if args.pretty else None

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=indent, ensure_ascii=False)
        print(f"扫描完成。发现 {result['summary']['total_findings']} 个问题。结果已保存到 {args.output}")
    else:
        print(json.dumps(result, indent=indent, ensure_ascii=False))


if __name__ == "__main__":
    main()
