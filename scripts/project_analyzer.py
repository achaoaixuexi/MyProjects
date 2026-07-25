"""
Saving-tokens-skill — Project Analyzer (Phase 3)
==================================================
编程项目级 token 浪费分析。与 scanner.py 互补：
  - scanner.py          → 配置文件层面 (SKILL.md / instructions / agents)
  - project_analyzer.py → 源码项目层面 (源文件 / 依赖 / 构建产物)

Usage:
    python project_analyzer.py <project_dir> [-o output.json]
"""

import json
import os
import argparse
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Any

from common import safe_int, count_lines, safe_output_path


# ── Source-code file extensions ──
_SOURCE_EXTS = {'.py', '.ts', '.tsx', '.js', '.jsx', '.go', '.rs', '.java',
                '.cs', '.cpp', '.c', '.rb', '.php', '.swift', '.kt'}
_HEAVY_DIRS = {'node_modules', '.venv', 'venv', '__pycache__', 'dist',
               'build', '.next', 'target', 'vendor', '.turbo', '.cache',
               '.git', '.pytest_cache', '.token_cache'}


# ══════════════════════════════════════════════════════════════════════════
# Analysis functions
# ══════════════════════════════════════════════════════════════════════════

def _find_large_source_files(root: Path) -> list[dict]:
    """Find source files >500 lines that could cause large agent reads."""
    large = []
    for ext in _SOURCE_EXTS:
        for fpath in root.rglob(f'*{ext}'):
            # Skip heavy dirs
            if any(hd in fpath.parts for hd in _HEAVY_DIRS):
                continue
            try:
                lc = count_lines(str(fpath), include_blank=True)
            except (OSError, PermissionError):
                continue
            if lc > 500:
                try:
                    rel = fpath.relative_to(root)
                except ValueError:
                    rel = fpath
                large.append({
                    "path": str(rel),
                    "lines": lc,
                    "est_tokens_per_read": lc * 3,
                })
    large.sort(key=lambda x: -x["lines"])
    return large[:20]


def _find_unprotected_dirs(root: Path) -> dict:
    """Check if heavy directories exist but are not git-ignored."""
    gi = root / '.gitignore'
    ignored_set: set[str] = set()
    if gi.exists():
        try:
            ignored_set = set(gi.read_text(encoding='utf-8', errors='ignore').split('\n'))
        except (OSError, PermissionError):
            pass

    present_unprotected = []
    present_protected = []
    for hd in _HEAVY_DIRS:
        d = root / hd
        if d.exists():
            if hd in ignored_set or any(line.strip() == hd for line in ignored_set):
                present_protected.append(hd)
            else:
                present_unprotected.append(hd)

    return {
        "has_gitignore": gi.exists(),
        "unprotected": present_unprotected,
        "protected": present_protected,
        "unprotected_count": len(present_unprotected),
    }


def _estimate_dependency_bloat(root: Path) -> dict:
    """Rough estimate of dependency-directory file counts."""
    bloat = {}
    for hd in _HEAVY_DIRS:
        d = root / hd
        if d.exists():
            try:
                file_count = sum(1 for _ in d.rglob('*') if _.is_file())
            except (OSError, PermissionError):
                file_count = 0
            if file_count > 0:
                bloat[hd] = {
                    "files": file_count,
                    "est_scan_tokens": file_count * 10,  # ~10 tokens per file scanned
                }
    return bloat


def _find_top_level_skipped(root: Path) -> list[str]:
    """Find top-level items >5MB that would waste agent context if read."""
    large = []
    try:
        for item in root.iterdir():
            if item.is_file():
                size_mb = item.stat().st_size / (1024 * 1024)
                if size_mb > 5:
                    large.append(f"{item.name} ({size_mb:.1f} MB)")
    except (OSError, PermissionError):
        pass
    return large


# ══════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════

def analyze_project(target_dir: str) -> dict:
    """Run project-level analysis and return structured results."""
    root = Path(target_dir).resolve()
    if not root.is_dir():
        return {"error": f"目录不存在: {target_dir}"}

    large_files = _find_large_source_files(root)
    dirs_info = _find_unprotected_dirs(root)
    bloat = _estimate_dependency_bloat(root)
    large_items = _find_top_level_skipped(root)

    # ── Token waste estimates ──
    est_waste = 0
    for lf in large_files:
        est_waste += (lf["lines"] - 100) * 3  # assume 100 useful lines
    for hd, info in bloat.items():
        if hd in dirs_info.get("unprotected", []):
            est_waste += info.get("est_scan_tokens", 0)

    total_bloat_files = sum(info.get("files", 0) for info in bloat.values())

    summary = {
        "large_source_files": len(large_files),
        "largest_file_lines": large_files[0]["lines"] if large_files else 0,
        "unprotected_dirs": dirs_info["unprotected_count"],
        "protected_dirs": len(dirs_info.get("protected", [])),
        "bloat_dir_count": len(bloat),
        "bloat_file_count": total_bloat_files,
        "large_top_level_items": len(large_items),
        "est_token_waste": est_waste,
    }

    return {
        "target": str(root),
        "analysis_time": datetime.now().isoformat(),
        "large_files": large_files[:10],
        "directories": dirs_info,
        "dependency_bloat": {k: v for k, v in sorted(bloat.items(), key=lambda x: -x[1]["files"])[:8]},
        "large_items": large_items,
        "summary": summary,
    }


def estimate_savings_rate(data: dict) -> dict:
    """Compute estimated token savings rate from project analysis."""
    summary = data.get("summary", {})
    est_waste = summary.get("est_token_waste", 0)
    large_files = summary.get("large_source_files", 0)
    unprotected = summary.get("unprotected_dirs", 0)
    bloat_files = summary.get("bloat_file_count", 0)

    # Conservative estimate: a typical coding session reads 5-10 files
    avg_savings_per_session = 0
    if large_files > 0:
        avg_savings_per_session += min(large_files * 300, 3000)  # 300 tokens saved per large file, cap at 3000
    if unprotected > 0:
        avg_savings_per_session += min(unprotected * 500, 2000)   # 500 per unprotected dir
    if bloat_files > 100:
        avg_savings_per_session += 1000                           # flat bonus for bloated projects

    return {
        "est_waste_total": est_waste,
        "est_savings_per_session": avg_savings_per_session,
        "est_savings_pct": f"{min(avg_savings_per_session / 20000 * 100, 50):.1f}%",
        "note": "基于典型编程会话 20,000 token 上下文的保守估算",
    }


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Saving-tokens-skill — 编程项目级 token 浪费分析"
    )
    parser.add_argument("target", help="要分析的项目目录")
    parser.add_argument("-o", "--output", help="输出 JSON 文件路径")
    parser.add_argument("--pretty", action="store_true", help="格式化输出")
    args = parser.parse_args()

    result = analyze_project(args.target)
    savings = estimate_savings_rate(result)
    result["savings_estimate"] = savings

    indent = 2 if args.pretty else None

    if args.output:
        try:
            out = safe_output_path(args.output, base_dir=str(Path.cwd()))
        except ValueError as e:
            print(f"错误: {e}", file=sys.stderr)
            sys.exit(1)
        with open(str(out), "w", encoding="utf-8") as f:
            json.dump(result, f, indent=indent, ensure_ascii=False)
        print(f"分析完成。结果已保存到 {args.output}")
        print(f"  大型源文件: {result['summary']['large_source_files']} 个")
        print(f"  未排除目录: {result['summary']['unprotected_dirs']} 个")
        print(f"  预估会话节省: {savings['est_savings_per_session']:,} tokens ({savings['est_savings_pct']} 的会话上下文)")
    else:
        print(json.dumps(result, indent=indent, ensure_ascii=False))


if __name__ == "__main__":
    main()
