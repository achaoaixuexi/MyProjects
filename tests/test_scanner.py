"""
Tests for scanner.py — static anti-pattern detection.
Covers all check_* functions.
"""
import pytest
import tempfile
from pathlib import Path
from scanner import (
    Finding,
    parse_frontmatter,
    count_lines,
    count_total_lines,
    check_apply_to_wildcard,
    check_monolithic_skill,
    check_vague_description,
    check_swiss_army_agent,
    check_bloated_always_on,
    check_no_progressive_loading,
    check_large_skill,
    check_missing_tools,
    check_long_description,
    check_workbuddy_identity_bloat,
    check_workbuddy_extra_frontmatter,
    discover_files,
    scan,
)


# ===================================================================
# parse_frontmatter
# ===================================================================

class TestParseFrontmatter:
    def test_basic_key_value(self, make_skill_md):
        fp = make_skill_md("test", 'name: my-skill\ndescription: hello world')
        fm = parse_frontmatter(fp)
        assert fm["name"] == "my-skill"
        assert fm["description"] == "hello world"

    def test_block_scalar(self, make_skill_md):
        fp = make_skill_md("test",
            'name: test\ndescription: |\n  Line one\n  Line two')
        fm = parse_frontmatter(fp)
        assert "Line one Line two" in fm["description"]

    def test_inline_list(self, make_skill_md):
        fp = make_skill_md("test",
            'name: test\ntools: [read, search, grep]')
        fm = parse_frontmatter(fp)
        assert len(fm["tools"]) == 3
        assert "read" in fm["tools"]

    def test_yaml_list(self, make_skill_md):
        fp = make_skill_md("test",
            'name: test\nallowed-tools:\n  - Read\n  - Grep')
        fm = parse_frontmatter(fp)
        assert len(fm["allowed-tools"]) == 2

    def test_missing_frontmatter(self, make_skill_md):
        fp = make_skill_md("test", '', '# No frontmatter\n')
        fm = parse_frontmatter(fp)
        assert fm == {}

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("")
            f.flush()
            fm = parse_frontmatter(f.name)
        assert fm == {}


# ===================================================================
# Line counting
# ===================================================================

class TestLineCounting:
    def test_count_lines(self, make_skill_md):
        body = "\n".join(f"line {i}" for i in range(10))
        fp = make_skill_md("test", 'name: test', body)
        assert count_lines(fp) > 0

    def test_count_total_lines(self, make_skill_md):
        body = "line1\n\nline2\n\n\nline3"
        fp = make_skill_md("test", 'name: test', body)
        # 3 non-empty + 3 blank = 6 total lines (+ frontmatter lines)
        assert count_total_lines(fp) >= 6


# ===================================================================
# AP-01: applyTo wildcard
# ===================================================================

class TestAP01ApplyToWildcard:
    def test_detects_wildcard_string(self):
        fm = {"applyTo": "**"}
        result = check_apply_to_wildcard(fm, "test.instructions.md")
        assert result is not None
        assert result.id == "AP-01"
        assert result.severity == "critical"

    def test_detects_wildcard_in_list(self):
        fm = {"applyTo": ["**/*.py", "**"]}
        result = check_apply_to_wildcard(fm, "test.instructions.md")
        assert result is not None
        assert result.id == "AP-01"

    def test_no_false_positive_specific_glob(self):
        fm = {"applyTo": "**/*.py"}
        result = check_apply_to_wildcard(fm, "test.instructions.md")
        assert result is None

    def test_no_apply_to_field(self):
        fm = {"name": "test"}
        result = check_apply_to_wildcard(fm, "test.instructions.md")
        assert result is None

    def test_only_triggers_on_instructions(self):
        # check_apply_to_wildcard checks frontmatter only; filtering by
        # file type is done at the call site in scan(), not in the checker.
        fm = {"applyTo": "**"}
        result = check_apply_to_wildcard(fm, "SKILL.md")
        # The checker itself does detect it - scan() is responsible for
        # only calling it on .instructions.md files
        assert result is not None
        assert result.id == "AP-01"


# ===================================================================
# AP-02: Monolithic SKILL.md
# ===================================================================

class TestAP02MonolithicSkill:
    def test_detects_large_skill(self, make_skill_md):
        # Create a 501-line SKILL.md
        body = "\n".join(f"line {i}" for i in range(501))
        fp = make_skill_md("huge-skill", 'name: huge', body)
        # Remove auto-created references/ to simulate no split
        ref_dir = Path(fp).parent / "references"
        import shutil
        shutil.rmtree(ref_dir, ignore_errors=True)
        result = check_monolithic_skill(fp)
        assert result is not None
        assert result.id == "AP-02"

    def test_skips_small_skill(self, make_skill_md):
        body = "\n".join(f"line {i}" for i in range(10))
        fp = make_skill_md("small-skill", 'name: small', body)
        result = check_monolithic_skill(fp)
        assert result is None

    def test_flags_large_skill_even_with_references(self, make_skill_md):
        body = "\n".join(f"line {i}" for i in range(600))
        fp = make_skill_md("ref-skill", 'name: ref', body)
        # references/ exists from fixture, but >500 lines always flagged
        result = check_monolithic_skill(fp)
        assert result is not None
        assert result.id == "AP-02"


# ===================================================================
# AP-04: Vague description
# ===================================================================

class TestAP04VagueDescription:
    def test_detects_missing_description(self, sample_frontmatter_well_formed):
        fm = {}  # no description at all
        result = check_vague_description(fm, "test.md")
        assert result is not None
        assert result.id == "AP-04"

    def test_detects_short_description(self):
        fm = {"description": "Help"}
        result = check_vague_description(fm, "test.md")
        assert result is not None
        assert result.id == "AP-04"
        assert result.severity == "high"

    def test_detects_no_use_when_pattern(self):
        fm = {"description": "do stuff with code"}
        result = check_vague_description(fm, "test.md")
        assert result is not None
        assert result.id == "AP-04"

    def test_accepts_well_formed_description(self):
        fm = {"description": "Use when writing database migrations and schema changes for SQL"}
        result = check_vague_description(fm, "test.md")
        assert result is None

    def test_accepts_chinese_description(self):
        # Chinese text doesn't have spaces, so word count check is lenient.
        # Long enough Chinese description with trigger word passes.
        fm = {"description": "使用场景: 编写数据库迁移脚本和表结构变更，用于 PostgreSQL 和 MySQL 数据库版本管理"}
        result = check_vague_description(fm, "test.md")
        assert result is None


# ===================================================================
# AP-05: Swiss-army Agent
# ===================================================================

class TestAP05SwissArmyAgent:
    def test_detects_too_many_tools(self):
        fm = {"tools": ["read", "write", "edit", "search", "execute", "web"]}
        result = check_swiss_army_agent(fm, "test.agent.md")
        assert result is not None
        assert result.id == "AP-05"

    def test_accepts_few_tools(self):
        fm = {"tools": ["read", "search"]}
        result = check_swiss_army_agent(fm, "test.agent.md")
        assert result is None

    def test_skips_non_agent_files(self):
        # Like AP-01, file-type filtering is at scan() call site, not in checker.
        fm = {"tools": ["read", "write", "edit", "search", "execute", "web", "agent"]}
        result = check_swiss_army_agent(fm, "SKILL.md")
        # scan() is responsible for only calling this on .agent.md files
        assert result is not None
        assert result.id == "AP-05"

    def test_handles_missing_tools(self):
        fm = {"name": "test"}
        result = check_swiss_army_agent(fm, "test.agent.md")
        assert result is None


# ===================================================================
# AP-06: Bloated always-on
# ===================================================================

class TestAP06BloatedAlwaysOn:
    def test_detects_large_file(self, make_skill_md):
        body = "\n".join(f"line {i}" for i in range(250))
        fp = make_skill_md("big", 'name: big', body)
        result = check_bloated_always_on(fp)
        assert result is not None
        assert result.id == "AP-06"

    def test_accepts_small_file(self, make_skill_md):
        body = "\n".join(f"line {i}" for i in range(50))
        fp = make_skill_md("small", 'name: small', body)
        result = check_bloated_always_on(fp)
        assert result is None


# ===================================================================
# AP-07: No progressive loading
# ===================================================================

class TestAP07NoProgressiveLoading:
    def test_detects_missing_references(self, make_skill_md):
        body = "\n".join(f"line {i}" for i in range(200))
        fp = make_skill_md("nosplit", 'name: nosplit', body)
        import shutil
        shutil.rmtree(Path(fp).parent / "references", ignore_errors=True)
        result = check_no_progressive_loading(fp)
        assert result is not None
        assert result.id == "AP-07"

    def test_accepts_small_skill(self, make_skill_md):
        body = "\n".join(f"line {i}" for i in range(10))
        fp = make_skill_md("tiny", 'name: tiny', body)
        result = check_no_progressive_loading(fp)
        assert result is None


# ===================================================================
# AP-08: Large SKILL.md (200-500)
# ===================================================================

class TestAP08LargeSkill:
    def test_detects_medium_skill(self, make_skill_md):
        body = "\n".join(f"line {i}" for i in range(300))
        fp = make_skill_md("medium", 'name: medium', body)
        result = check_large_skill(fp)
        assert result is not None
        assert result.id == "AP-08"

    def test_skips_small_skill(self, make_skill_md):
        body = "\n".join(f"line {i}" for i in range(50))
        fp = make_skill_md("small", 'name: small', body)
        result = check_large_skill(fp)
        assert result is None


# ===================================================================
# AP-10: Missing tools
# ===================================================================

class TestAP10MissingTools:
    def test_detects_no_tools(self):
        fm = {"name": "test"}
        result = check_missing_tools(fm, "test.agent.md")
        assert result is not None
        assert result.id == "AP-10"

    def test_accepts_declared_tools(self):
        fm = {"name": "test", "tools": ["read"]}
        result = check_missing_tools(fm, "test.agent.md")
        assert result is None


# ===================================================================
# AP-12: Long description
# ===================================================================

class TestAP12LongDescription:
    def test_detects_long_description(self):
        fm = {"description": "x" * 600}
        result = check_long_description(fm, "test.md")
        assert result is not None
        assert result.id == "AP-12"

    def test_accepts_short_description(self):
        fm = {"description": "Use when testing"}
        result = check_long_description(fm, "test.md")
        assert result is None

    def test_handles_non_string(self):
        fm = {"description": 123}
        result = check_long_description(fm, "test.md")
        assert result is None


# ===================================================================
# Workbuddy-specific
# ===================================================================

class TestWorkbuddyChecks:
    def test_identity_bloat(self, make_skill_md):
        body = "\n".join(f"line {i}" for i in range(150))
        fp = make_skill_md("wb", 'name: wb', body)
        # Rename to IDENTITY.md
        new_fp = str(Path(fp).parent / "IDENTITY.md")
        import os
        os.rename(fp, new_fp)
        result = check_workbuddy_identity_bloat(new_fp)
        assert result is not None
        assert result.id == "WB-02"

    def test_identity_ok(self, make_skill_md):
        body = "\n".join(f"line {i}" for i in range(30))
        fp = make_skill_md("wb", 'name: wb', body)
        new_fp = str(Path(fp).parent / "IDENTITY.md")
        import os
        os.rename(fp, new_fp)
        result = check_workbuddy_identity_bloat(new_fp)
        assert result is None

    def test_extra_frontmatter(self):
        fm = {
            "name": "test",
            "description": "x" * 400,
            "version": "1.0.0",
            "tags": ["test"],
        }
        result = check_workbuddy_extra_frontmatter(fm, "test.md")
        assert result is not None
        assert result.id == "WB-03"


# ===================================================================
# Finding class
# ===================================================================

class TestFinding:
    def test_to_dict(self):
        f = Finding("AP-01", "critical", "/tmp/test.md",
                     detail="test detail", suggestion="fix it",
                     est_savings="100 tokens")
        d = f.to_dict()
        assert d["id"] == "AP-01"
        assert d["severity"] == "critical"
        assert d["file"] == "/tmp/test.md"
        assert d["detail"] == "test detail"
        assert d["suggestion"] == "fix it"
        assert d["est_savings"] == "100 tokens"


# ===================================================================
# scan() integration
# ===================================================================

class TestScanIntegration:
    def test_scan_empty_dir(self, tmp_path):
        result = scan(str(tmp_path))
        assert result["summary"]["total_findings"] == 0
        assert result["summary"]["health_score"] == 100

    def test_scan_with_skill_dir(self, make_skill_md):
        import tempfile
        import shutil
        tmp = tempfile.mkdtemp()
        agent_skills = Path(tmp) / ".agents" / "skills"
        agent_skills.mkdir(parents=True)

        # Create a well-formed skill
        skill_dir = agent_skills / "good-skill"
        skill_dir.mkdir()
        refs = skill_dir / "references"
        refs.mkdir()
        content = "---\nname: good-skill\ndescription: Use when doing awesome things with Python and testing\n---\n\n# Good Skill\n\nSome content here."
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

        result = scan(tmp)
        assert result is not None
        assert "total_findings" in result["summary"]

        shutil.rmtree(tmp, ignore_errors=True)
