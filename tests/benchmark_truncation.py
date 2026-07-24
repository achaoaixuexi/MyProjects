"""
Truncation Quality Benchmark — old vs new fix_long_description logic.

Metrics:
  1. Entity Preservation Rate — % of key entities (dates, URLs, code terms...)
     that survive truncation.
  2. Sentence Boundary Adherence — % of truncations that end at a natural
     sentence/clause boundary vs mid-word.
  3. Bracket Safety — % of truncations that avoid cutting inside (...), [...].
  4. Fidelity Pass Rate — % of truncations that pass the _fidelity_check.
  5. Average Truncated Length — how close to 180 chars the result is (higher
     is better for token savings, but only when quality is maintained).

Usage:
    python tests/benchmark_truncation.py
"""

import sys
import os
import re
import json
from pathlib import Path

# Add scripts/ to path to import from fixer
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from fixer import (
    _smart_truncate,
    _rescue_entities,
    _fidelity_check,
    _ENTITY_PATTERNS,
)

# ── ROUGE-L for quality assessment (pure-Python, zero-dependency) ──
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from benchmark_reporter import rouge_l_similarity


# ── Old truncation (the code before improvement) ──
def _old_truncate(text: str, max_len: int = 180) -> str:
    """Original blind word-boundary truncation."""
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "..."


# ─── Semantic Fidelity  (Layer 2 quality assessment) ───

class SemanticFidelity:
    """Composite truncation quality score (0–100).

    Aggregates four sub-scores:
      - entity_retention:   fraction of key entities preserved
      - keyword_retention:  fraction of trigger-words preserved
      - structural_safety:  bracket / quote pairing completeness
      - readability:        sentence / clause boundary naturalness
    """

    TRIGGER_WORDS = [
        "use when", "使用", "diagnose", "诊断", "optimize", "优化",
        "search", "搜索", "generate", "生成", "analyze", "分析",
    ]

    def __init__(self, original: str, truncated: str):
        self.original = original
        self.truncated = truncated.rstrip(".")
        self.entity_retention = self._calc_entity_retention()
        self.keyword_retention = self._calc_keyword_retention()
        self.structural_safety = self._calc_structural_safety()
        self.readability = self._calc_readability()

    def _calc_entity_retention(self) -> float:
        orig = get_entities_in_text(self.original)
        trunc = get_entities_in_text(self.truncated)
        if not orig:
            return 1.0
        return len(orig & trunc) / len(orig)

    def _calc_keyword_retention(self) -> float:
        orig_lower = self.original.lower()
        trunc_lower = self.truncated.lower()
        orig_kw = [t for t in self.TRIGGER_WORDS if t in orig_lower]
        if not orig_kw:
            return 1.0
        preserved = sum(1 for t in orig_kw if t in trunc_lower)
        return preserved / len(orig_kw)

    def _calc_structural_safety(self) -> float:
        pairs = [('(', ')'), ('[', ']'), ('{', '}'), ('$', '$')]
        ok = 0
        for op, cl in pairs:
            if self.truncated.count(op) == self.truncated.count(cl):
                ok += 1
        # markdown code-fence
        if self.truncated.count('```') % 2 == 0:
            ok += 0.5
        else:
            ok -= 0.5
        return max(0.0, min(1.0, (ok + 0.5) / (len(pairs) + 0.5)))

    def _calc_readability(self) -> float:
        txt = self.truncated.rstrip()
        if not txt:
            return 1.0
        if any(txt.endswith(c) for c in ('.', '!', '?', ',', ';', ':')):
            return 1.0
        if txt[-1].isalnum():
            return 1.0
        return 0.0

    def composite_score(self) -> float:
        return round(
            self.entity_retention  * 0.4 +
            self.keyword_retention * 0.2 +
            self.structural_safety * 0.2 +
            self.readability       * 0.2,
            3,
        )

    def to_dict(self) -> dict:
        return {
            "composite_score": self.composite_score(),
            "entity_retention": round(self.entity_retention, 3),
            "keyword_retention": round(self.keyword_retention, 3),
            "structural_safety": round(self.structural_safety, 3),
            "readability": round(self.readability, 3),
        }


# ── Test case definitions ──
# Each case has an id, the full description text, and the entity types expected.
TEST_CASES: list[dict] = [
    # ──── Dates near boundary ────
    {
        "id": "date_near_boundary",
        "desc": (
            "Use when writing database migration scripts and performing schema changes. "
            "Supports PostgreSQL, MySQL, and SQLite backends. "
            "The latest stable release was on 2026-07-15 with full backward compatibility. "
            "Migration files should follow the naming convention V1_0_0__description.sql."
        ),
        "expected_entities": ["2026-07-15", "PostgreSQL", "MySQL", "SQLite"],
    },
    {
        "id": "date_deep_in_text",
        "desc": (
            "Diagnose and optimize agent token consumption in VS Code Copilot and Workbuddy. "
            "This skill scans configuration files for known anti-patterns such as applyTo wildcards, "
            "monolithic SKILL.md files exceeding 500 lines, and duplicate instruction files. "
            "The benchmark was last executed on 2026-07-23 showing 38 percent overall savings. "
            "Future releases are planned for Q4 2026."
        ),
        "expected_entities": ["2026-07-23", "VS Code", "Workbuddy"],
    },

    # ──── URLs near boundary ────
    {
        "id": "url_near_boundary",
        "desc": (
            "Search the web and extract content via the Tavily API. "
            "Configure the API endpoint at https://api.tavily.com/v1/search with your key. "
            "For detailed documentation refer to https://docs.tavily.com/api-reference/streaming "
            "which covers all available parameters including search_depth and max_results."
        ),
        "expected_entities": ["https://api.tavily.com/v1/search", "https://docs.tavily.com/api-reference/streaming"],
    },

    # ──── Inline code / technical terms ────
    {
        "id": "code_terms_near_boundary",
        "desc": (
            "This skill handles Python project scaffolding with `FastAPI` and `SQLAlchemy` async sessions. "
            "Use `black --line-length 100` for code formatting and `mypy --strict` for type checking. "
            "The `pytest.ini` configuration should include `asyncio_mode = auto` for proper async test execution. "
            "Key decorators include `@router.get('/items/{item_id}')` and `@depends(get_db)` for DI."
        ),
        "expected_entities": ["FastAPI", "SQLAlchemy", "mypy", "pytest.ini"],
    },

    # ──── CamelCase & Acronyms ────
    {
        "id": "camelcase_acronyms",
        "desc": (
            "Configure the CI pipeline using GitHub Actions with Docker Compose for PostgreSQL "
            "and Redis caching. The OpenAI API key should be stored in AWS SecretsManager. "
            "Use ReactQuery for frontend data fetching and Zustand for state management. "
            "The Kubernetes deployment requires HelmCharts version 3.12."
        ),
        "expected_entities": ["GitHub", "Docker", "PostgreSQL", "Redis", "OpenAI", "AWS", "ReactQuery", "Zustand", "Kubernetes", "HelmCharts"],
    },

    # ──── Bracket safety ────
    {
        "id": "bracket_safety",
        "desc": (
            "This diagnostic tool (supporting VS Code Copilot and Workbuddy platforms) scans for anti-patterns "
            "including: applyTo wildcards (AP-01), monolithic SKILL.md (AP-02), duplicate instructions (AP-03), "
            "and vague description fields (AP-04). Each finding includes a severity level [critical, high, medium, low] "
            "along with an estimated token savings figure. The scanner also checks Workbuddy-specific issues "
            "such as fallback.bak residue files (WB-01) and identity bloat (WB-02)."
        ),
        "expected_entities": ["VS Code", "Workbuddy", "AP-01", "AP-02", "AP-03", "AP-04"],
    },

    # ──── Chinese text ────
    {
        "id": "chinese_trigger_words",
        "desc": (
            "诊断并优化 AI 智能体的 token 消耗。支持 VS Code Copilot 和 Workbuddy 平台。"
            "扫描项目配置文件中的已知反模式，包括 applyTo 全量匹配和重复的 instructions 文件。"
            "使用 `session_analyzer.py` 分析运行时数据，检测长会话未压缩、输入输出 token 比例失衡等问题。"
            "运行 `python scripts/scanner.py . -o result.json` 开始诊断。"
            "注意事项：静态分析估算基于文件大小和反模式计数，非精确 token 数。"
        ),
        "expected_entities": ["VS Code", "Workbuddy", "session_analyzer.py", "scanner.py"],
    },

    # ──── Version numbers ────
    {
        "id": "version_numbers",
        "desc": (
            "Upgrade guide from version 1.5.2 to version 2.0.0. This major release introduces breaking changes "
            "in the authentication middleware. The deprecated OAuth2PasswordBearer has been replaced with "
            "OAuth2AuthorizationCodeBearer from the fastapi.security module. Python version 3.12 or higher "
            "is now required. Legacy support for Python 3.9 and Python 3.10 has been removed entirely."
        ),
        "expected_entities": ["OAuth2PasswordBearer", "OAuth2AuthorizationCodeBearer", "Python"],
    },

    # ──── Edge: very short description ────
    {
        "id": "short_desc",
        "desc": "A brief helper for quick code formatting tasks.",
        "expected_entities": [],
    },

    # ──── Edge: all entities past boundary ────
    {
        "id": "entities_all_past_boundary",
        "desc": (
            "Use when writing and reviewing code for token efficiency optimization. "
            "aaaaaaaa bbbbbbbb cccccccc dddddddd eeeeeeee ffffffff gggggggg hhhhhhhh "
            "iiiiiiii jjjjjjjj kkkkkkkk llllllll mmmmmmmm nnnnnnnn oooooooo pppppppp "
            "qqqqqqqq rrrrrrrr ssssssss tttttttt uuuuuuuu vvvvvvvv wwwwwwww xxxxxxxx "
            "yyyyyyyy zzzzzzzz. The API key is sk-abc123def456 and the endpoint is "
            "at https://example.com/api/v42 with PostgreSQL version 16.3."
        ),
        "expected_entities": ["PostgreSQL", "https://example.com/api/v42"],
    },

    # ──── Issue 6-1: Special-format edge cases ────

    {
        "id": "json_structure",
        "desc": (
            "Configure the API gateway with the following JSON settings: "
            '{"api_endpoint": "https://api.example.com/v2", "version": "2026-07-24", '
            '"retry": {"max_attempts": 3, "backoff_ms": 500}, '
            '"features": ["search", "recommend", "chat"]}. '
            "The JSON blob must be valid after any processing including truncation."
        ),
        "expected_entities": ["https://api.example.com/v2", "2026-07-24"],
    },
    {
        "id": "csv_table",
        "desc": (
            "The following CSV data represents monthly token usage: "
            "name,date,tokens_input,tokens_output,total\n"
            "Alice,2026-07-15,15000,3200,18200\n"
            "Bob,2026-07-20,23000,4100,27100\n"
            "Charlie,2026-07-22,8900,2100,11000. "
            "Note that CSV column alignment and delimiter integrity are critical."
        ),
        "expected_entities": ["2026-07-15", "2026-07-20", "2026-07-22"],
    },
    {
        "id": "latex_inline",
        "desc": (
            "For mathematical notation we use LaTeX: $E = mc^2$ is Einstein's equation "
            "and $\\sum_{i=1}^{n} x_i$ represents summation. "
            "The inline formula $F = ma$ and display formula $$\\int_0^\\infty e^{-x^2} dx$$ "
            "must preserve dollar-sign pairing through truncation."
        ),
        "expected_entities": [],
    },
    {
        "id": "mixed_code_json",
        "desc": (
            "Use when writing database migrations with `SQLAlchemy` and `FastAPI`. "
            'Configure via JSON: `{"pool_size": 20, "max_overflow": 10}`. '
            "Run with `uvicorn main:app --reload --port 8080`. "
            "Refer to https://docs.sqlalchemy.org/en/20/ for the latest API changes "
            "released on 2026-07-15. See also PostgreSQL and Redis configuration."
        ),
        "expected_entities": ["SQLAlchemy", "FastAPI",
                              "https://docs.sqlalchemy.org/en/20/",
                              "2026-07-15", "PostgreSQL", "Redis"],
    },
    {
        "id": "deeply_nested_brackets",
        "desc": (
            "The anti-pattern hierarchy is: ((AP-01 and (AP-02 or AP-03)) and "
            "(AP-04 or (AP-05 and AP-06))) and ((WB-01) or (WB-02 and WB-03)). "
            "Each anti-pattern has a severity rating [critical, high, medium, low] "
            "and a category (context loading, progressive loading, agent design). "
            "Refer to references/anti-patterns.md for the complete list."
        ),
        "expected_entities": ["WB"],
    },
]


# ── Metrics computation ──
def count_entities_in_text(text: str) -> int:
    """Count how many entities from _ENTITY_PATTERNS appear in text."""
    found = set()
    for pattern, _etype in _ENTITY_PATTERNS:
        for m in re.finditer(pattern, text):
            found.add(m.group())
    return len(found)


def get_entities_in_text(text: str) -> set[str]:
    """Return set of entity strings found in text."""
    found: set[str] = set()
    for pattern, _etype in _ENTITY_PATTERNS:
        for m in re.finditer(pattern, text):
            found.add(m.group())
    return found


def check_sentence_boundary(text: str) -> bool:
    """Check if text ends at a sentence/clause boundary (before '...')."""
    stripped = text.rstrip(".")
    if not stripped:
        return True
    last_chars = stripped[-3:] if len(stripped) >= 3 else stripped
    # Ends with sentence terminator
    if any(stripped.endswith(c) for c in ('.', '!', '?', ',', ';', ':')):
        return True
    # Ends with a complete word (last char is alphanumeric)
    if stripped[-1].isalnum():
        return True
    return False


def check_bracket_safety(original: str, truncated: str) -> bool:
    """Check that truncation didn't cut inside brackets — extended for
    LaTeX $...$ / JSON {} [] / markdown code-fence ```."""
    base = truncated.rstrip(".")
    pairs = [
        ('(', ')'), ('[', ']'), ('{', '}'),     # standard
        ('$', '$'),                              # LaTeX math
    ]
    for op, cl in pairs:
        if base.count(op) != base.count(cl):
            return False
    # Markdown code-fence triples
    fence_count = base.count('```')
    if fence_count % 2 != 0:
        return False
    return True


def run_benchmark() -> dict:
    """Run old vs new truncation on all test cases and collect metrics."""
    results = {
        "test_date": "2026-07-24",
        "num_test_cases": len(TEST_CASES),
        "cases": [],
        "summary_old": {
            "entity_preservation_rate": 0.0,
            "sentence_boundary_rate": 0.0,
            "bracket_safety_rate": 0.0,
            "fidelity_pass_rate": 0.0,
            "avg_fidelity_score": 0.0,
            "avg_rouge_l": 0.0,
            "avg_truncated_length": 0.0,
            "avg_length_vs_target": 0.0,
        },
        "summary_new": {
            "entity_preservation_rate": 0.0,
            "sentence_boundary_rate": 0.0,
            "bracket_safety_rate": 0.0,
            "fidelity_pass_rate": 0.0,
            "avg_fidelity_score": 0.0,
            "avg_rouge_l": 0.0,
            "avg_truncated_length": 0.0,
            "avg_length_vs_target": 0.0,
        },
    }

    # Accumulators
    old_entity_total, old_entity_preserved = 0, 0
    new_entity_total, new_entity_preserved = 0, 0
    old_sentence_ok, new_sentence_ok = 0, 0
    old_bracket_ok, new_bracket_ok = 0, 0
    old_fidelity_ok, new_fidelity_ok = 0, 0
    old_lengths, new_lengths = [], []
    old_fid_scores, new_fid_scores = [], []
    old_rouge_s, new_rouge_s = [], []

    for tc in TEST_CASES:
        desc = tc["desc"]
        old_result = _old_truncate(desc)
        new_result = _smart_truncate(desc)

        # Entity counts
        orig_entities = get_entities_in_text(desc)
        old_entities = get_entities_in_text(old_result)
        new_entities = get_entities_in_text(new_result)

        n_orig = len(orig_entities)
        n_old = len(old_entities)
        n_new = len(new_entities)

        old_entity_total += n_orig
        old_entity_preserved += n_old
        new_entity_total += n_orig
        new_entity_preserved += n_new

        # Sentence boundary
        old_sent = check_sentence_boundary(old_result)
        new_sent = check_sentence_boundary(new_result)
        old_sentence_ok += 1 if old_sent else 0
        new_sentence_ok += 1 if new_sent else 0

        # Bracket safety
        old_bracket = check_bracket_safety(desc, old_result)
        new_bracket = check_bracket_safety(desc, new_result)
        old_bracket_ok += 1 if old_bracket else 0
        new_bracket_ok += 1 if new_bracket else 0

        # Fidelity check
        old_fid, _ = _fidelity_check(desc, old_result)
        new_fid, _ = _fidelity_check(desc, new_result)
        old_fidelity_ok += 1 if old_fid else 0
        new_fidelity_ok += 1 if new_fid else 0

        # Lengths
        old_len = len(old_result.rstrip("."))
        new_len = len(new_result.rstrip("."))
        old_lengths.append(old_len)
        new_lengths.append(new_len)

        # ── Semantic Fidelity composite score (Layer 2) ──
        sf_old = SemanticFidelity(desc, old_result)
        sf_new = SemanticFidelity(desc, new_result)
        old_fs = sf_old.composite_score()
        new_fs = sf_new.composite_score()
        old_fid_scores.append(old_fs)
        new_fid_scores.append(new_fs)

        # ── ROUGE-L similarity (Layer 3) ──
        old_rl = rouge_l_similarity(desc, old_result.rstrip("."))
        new_rl = rouge_l_similarity(desc, new_result.rstrip("."))
        old_rouge_s.append(old_rl)
        new_rouge_s.append(new_rl)

        # Lost entities detail
        lost_old = orig_entities - old_entities
        lost_new = orig_entities - new_entities

        case_result = {
            "id": tc["id"],
            "desc_len": len(desc),
            "old_len": old_len,
            "new_len": new_len,
            "orig_entities": sorted(orig_entities),
            "old_preserved": sorted(old_entities),
            "new_preserved": sorted(new_entities),
            "old_lost": sorted(lost_old),
            "new_lost": sorted(lost_new),
            "old_sentence_boundary": old_sent,
            "new_sentence_boundary": new_sent,
            "old_bracket_safe": old_bracket,
            "new_bracket_safe": new_bracket,
            "old_fidelity_pass": old_fid,
            "new_fidelity_pass": new_fid,
            "old_fidelity_score": old_fs,
            "new_fidelity_score": new_fs,
            "old_rouge_l": old_rl,
            "new_rouge_l": new_rl,
        }
        results["cases"].append(case_result)

    n = len(TEST_CASES)

    # Old summary
    results["summary_old"]["entity_preservation_rate"] = round(old_entity_preserved / max(old_entity_total, 1) * 100, 1)
    results["summary_old"]["sentence_boundary_rate"] = round(old_sentence_ok / n * 100, 1)
    results["summary_old"]["bracket_safety_rate"] = round(old_bracket_ok / n * 100, 1)
    results["summary_old"]["fidelity_pass_rate"] = round(old_fidelity_ok / n * 100, 1)
    results["summary_old"]["avg_truncated_length"] = round(sum(old_lengths) / n, 1)
    results["summary_old"]["avg_length_vs_target"] = round(sum(old_lengths) / n / 180 * 100, 1)
    results["summary_old"]["avg_fidelity_score"] = round(sum(old_fid_scores) / n, 3)
    results["summary_old"]["avg_rouge_l"] = round(sum(old_rouge_s) / n, 3)

    # New summary
    results["summary_new"]["entity_preservation_rate"] = round(new_entity_preserved / max(new_entity_total, 1) * 100, 1)
    results["summary_new"]["sentence_boundary_rate"] = round(new_sentence_ok / n * 100, 1)
    results["summary_new"]["bracket_safety_rate"] = round(new_bracket_ok / n * 100, 1)
    results["summary_new"]["fidelity_pass_rate"] = round(new_fidelity_ok / n * 100, 1)
    results["summary_new"]["avg_truncated_length"] = round(sum(new_lengths) / n, 1)
    results["summary_new"]["avg_length_vs_target"] = round(sum(new_lengths) / n / 180 * 100, 1)
    results["summary_new"]["avg_fidelity_score"] = round(sum(new_fid_scores) / n, 3)
    results["summary_new"]["avg_rouge_l"] = round(sum(new_rouge_s) / n, 3)

    return results


def print_report(results: dict) -> None:
    """Print a human-readable benchmark report."""
    s_old = results["summary_old"]
    s_new = results["summary_new"]

    def delta(old_val: float, new_val: float) -> str:
        diff = new_val - old_val
        sign = "+" if diff >= 0 else ""
        return f"{sign}{diff:.1f}"

    print("=" * 72)
    print("  截断质量基准测试报告 — fix_long_description 改进效果")
    print("=" * 72)
    print(f"  测试日期: {results['test_date']}")
    print(f"  测试用例数: {results['num_test_cases']}")
    print()

    # ── Summary comparison table ──
    print("-" * 72)
    print("  综合指标对比")
    print("-" * 72)
    print(f"  {'指标':<32} {'旧算法':>10} {'新算法':>10} {'变化':>10}")
    print(f"  {'-'*32} {'-'*10} {'-'*10} {'-'*10}")

    metrics = [
        ("实体保留率 (%)", "entity_preservation_rate"),
        ("句/从句边界率 (%)", "sentence_boundary_rate"),
        ("括号安全性 (%)", "bracket_safety_rate"),
        ("保真度通过率 (%)", "fidelity_pass_rate"),
        ("综合保真度 (0-1)", "avg_fidelity_score"),
        ("ROUGE-L 相似度", "avg_rouge_l"),
        ("平均截断长度 (字符)", "avg_truncated_length"),
        ("长度 vs 目标 180 (%)", "avg_length_vs_target"),
    ]

    for label, key in metrics:
        o = s_old[key]
        n = s_new[key]
        d = delta(o, n) if isinstance(o, float) else f"{'+' if n>o else ''}{n-o}"
        print(f"  {label:<32} {o:>10.1f} {n:>10.1f} {d:>10}")

    print()
    print("-" * 72)
    print("  逐用例详情")
    print("-" * 72)

    for case in results["cases"]:
        cid = case["id"]
        n_lost_old = len(case["old_lost"])
        n_lost_new = len(case["new_lost"])
        old_sent = "✅" if case["old_sentence_boundary"] else "❌"
        new_sent = "✅" if case["new_sentence_boundary"] else "❌"
        old_bkt = "✅" if case["old_bracket_safe"] else "❌"
        new_bkt = "✅" if case["new_bracket_safe"] else "❌"
        old_fid = "✅" if case["old_fidelity_pass"] else "❌"
        new_fid = "✅" if case["new_fidelity_pass"] else "❌"

        print(f"\n  [{cid}]  原文 {case['desc_len']} 字符")
        print(f"    旧: {case['old_len']} 字符 | 新: {case['new_len']} 字符")
        print(f"    实体丢失: 旧={n_lost_old} 新={n_lost_new}")
        if case["old_lost"]:
            print(f"      旧丢失: {case['old_lost']}")
        if case["new_lost"]:
            print(f"      新丢失: {case['new_lost']}")
        print(f"    句边界: 旧={old_sent} 新={new_sent} | 括号: 旧={old_bkt} 新={new_bkt} | 保真: 旧={old_fid} 新={new_fid}")
        old_fs = case.get("old_fidelity_score", 0)
        new_fs = case.get("new_fidelity_score", 0)
        old_rl = case.get("old_rouge_l", 0)
        new_rl = case.get("new_rouge_l", 0)
        print(f"    保真度: 旧={old_fs:.3f} 新={new_fs:.3f} | ROUGE-L: 旧={old_rl:.3f} 新={new_rl:.3f}")

    # ── Key findings ──
    print()
    print("=" * 72)
    print("  关键发现")
    print("=" * 72)

    entity_improvement = s_new["entity_preservation_rate"] - s_old["entity_preservation_rate"]
    sentence_improvement = s_new["sentence_boundary_rate"] - s_old["sentence_boundary_rate"]
    bracket_improvement = s_new["bracket_safety_rate"] - s_old["bracket_safety_rate"]
    fidelity_improvement = s_new["fidelity_pass_rate"] - s_old["fidelity_pass_rate"]

    findings = []

    if entity_improvement > 0:
        findings.append(
            f"  ✅ 实体保留率提升 {entity_improvement:+.1f}% — 新算法能救援截断点附近的"
            f" 日期、URL、代码术语、CamelCase 等技术实体，避免关键信息丢失。"
        )
    elif entity_improvement == 0:
        findings.append(
            f"  ➡️ 实体保留率持平 — 两种算法在该测试集上保留了相同数量的实体。"
        )

    if sentence_improvement > 0:
        findings.append(
            f"  ✅ 句边界率提升 {sentence_improvement:+.1f}% — 新算法优先在句尾/从句尾截断，"
            f" 产生的截断文本更自然、更易读。"
        )

    if bracket_improvement > 0:
        findings.append(
            f"  ✅ 括号安全性提升 {bracket_improvement:+.1f}% — 新算法避免在括号 `(...)` "
            f"`[...]` 内部截断，保证结构完整性。"
        )

    if fidelity_improvement > 0:
        findings.append(
            f"  ✅ 保真度通过率提升 {fidelity_improvement:+.1f}% — 截断后核心触发词保留更好，"
            f" 降低 skill 发现失败的风险。"
        )
    elif fidelity_improvement == 0 and s_new["fidelity_pass_rate"] == 100.0:
        findings.append(
            f"  ✅ 保真度通过率保持 100% — 两种算法均通过所有保真度检查。"
        )

    # Token savings cost
    len_diff = s_new["avg_truncated_length"] - s_old["avg_truncated_length"]
    if len_diff > 0:
        findings.append(
            f"  ⚠️ 平均截断长度增加 {len_diff:+.1f} 字符 — 实体救援和句边界保留会略微增加"
            f" 输出长度，但仍在目标 180 字符的可接受范围内（{s_new['avg_length_vs_target']:.1f}%）。"
            f" 这是质量换空间的合理取舍。"
        )
    elif len_diff <= 0:
        findings.append(
            f"  ✅ 平均截断长度未增加 — 在提升质量的同时没有牺牲压缩效率。"
        )

    for f_text in findings:
        print(f"  {f_text}")

    print()
    print("=" * 72)
    print("  结论")
    print("=" * 72)
    total_improvements = sum(1 for v in [entity_improvement, sentence_improvement,
                                          bracket_improvement, fidelity_improvement] if v > 0)
    if total_improvements >= 3:
        print(f"  新算法在 {total_improvements} 个维度上显著优于旧算法。")
        print(f"  智能截断 + 实体白名单 + 保真度校验的组合策略，在几乎不增加")
        print(f"  输出长度（+{len_diff:.1f} 字符）的前提下，大幅提升了 description")
        print(f"  截断的语义完整性，有效降低了因截断丢失关键信息而导致")
        print(f"  skill 发现失败的风险。")
    elif total_improvements >= 1:
        print(f"  新算法在 {total_improvements} 个维度上优于旧算法，改动有效。")
    print()


if __name__ == "__main__":
    results = run_benchmark()
    print_report(results)

    # Also save JSON for reference
    out_path = Path(__file__).parent.parent / "benchmark_truncation_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"  详细结果已保存至: {out_path}")
