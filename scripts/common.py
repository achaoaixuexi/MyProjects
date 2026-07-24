"""
Saving-tokens-skill — Common utilities shared across all scripts.
"""

import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Type-safe value extraction
# ---------------------------------------------------------------------------

def safe_int(val: Any, default: int = 0) -> int:
    """Safely convert to int, returning default on failure."""
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def safe_float(val: Any, default: float = 0.0) -> float:
    """Safely convert to float, returning default on failure."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# File utilities
# ---------------------------------------------------------------------------

def count_lines(filepath: str, include_blank: bool = False) -> int:
    """Count lines in a file."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            if include_blank:
                return sum(1 for _ in f)
            return sum(1 for line in f if line.strip())
    except (FileNotFoundError, PermissionError, OSError):
        return 0


# ---------------------------------------------------------------------------
# YAML frontmatter parsing
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_frontmatter(filepath: str) -> dict[str, Any]:
    """Parse YAML frontmatter. Tries pyyaml first, falls back to manual parser."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except (FileNotFoundError, PermissionError, OSError):
        return {}

    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}
    raw = match.group(1)

    # Try pyyaml first
    try:
        import yaml
        return yaml.safe_load(raw) or {}
    except ImportError:
        pass

    # Fallback manual parser (handles block scalars, lists, simple key-value)
    result: dict[str, Any] = {}
    lines = raw.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        kv = re.match(r"^(\w[\w-]*)\s*:\s*(.*)$", line)
        if not kv:
            i += 1
            continue
        key = kv.group(1)
        val = kv.group(2).strip()

        # Block scalar (|, >)
        if re.match(r"^[|>][-+]?$", val):
            block_lines = []
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if not nxt.strip():
                    block_lines.append("")
                    i += 1
                    continue
                if nxt.startswith("  ") or nxt.startswith("\t"):
                    block_lines.append(nxt.strip())
                    i += 1
                else:
                    break
            result[key] = " ".join(block_lines)
            continue

        # Inline list
        if val.startswith("[") and val.endswith("]"):
            result[key] = [item.strip().strip('"').strip("'") for item in val[1:-1].split(",")]
            i += 1
            continue

        # YAML list
        if val == "":
            list_items = []
            i += 1
            while i < len(lines):
                lm = re.match(r"^\s*-\s+(.+)$", lines[i])
                if lm:
                    list_items.append(lm.group(1).strip().strip('"').strip("'"))
                    i += 1
                elif not lines[i].strip():
                    i += 1
                else:
                    break
            if list_items:
                result[key] = list_items
                continue
            result[key] = ""
            continue

        result[key] = val.strip('"').strip("'")
        i += 1

    return result


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

def safe_output_path(output_arg: str, base_dir: str | None = None) -> Path:
    """Validate and resolve an output file path, preventing traversal."""
    path = Path(output_arg).resolve()
    if base_dir:
        base = Path(base_dir).resolve()
        try:
            path.relative_to(base)
        except ValueError:
            raise ValueError(f"输出路径 {output_arg} 不在允许的目录内 ({base_dir})")
    return path
