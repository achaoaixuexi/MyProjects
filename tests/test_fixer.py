"""Tests for fixer.py — auto-fix engine."""
import sys
import json
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from fixer import (
    FixResult,
    fix_duplicate_instructions,
    fix_long_description,
    generate_manual_fix_suggestions,
)


class TestFixResult:
    def test_success(self):
        r = FixResult("AP-03", "deleted", "file.md")
        assert r.finding_id == "AP-03"
        assert r.success is True

    def test_failure(self):
        r = FixResult("AP-03", "failed", "file.md", success=False)
        assert r.success is False


class TestFixDuplicateInstructions:
    def test_dry_run_no_changes(self, tmp_path):
        # Create a mock AGENTS.md
        agents = tmp_path / ".github" / "AGENTS.md"
        agents.parent.mkdir(parents=True, exist_ok=True)
        agents.write_text("# test")
        findings = [{"id": "AP-03", "file": str(agents)}]
        results = fix_duplicate_instructions(findings, dry_run=True)
        assert len(results) == 1
        assert "[DRY-RUN]" in results[0].action
        assert agents.exists()  # dry run doesn't modify

    def test_empty_findings(self):
        results = fix_duplicate_instructions([], dry_run=False)
        assert len(results) == 0


class TestFixLongDescription:
    def test_empty_findings(self):
        results = fix_long_description([], dry_run=False)
        assert len(results) == 0

    def test_non_md_file_skipped(self):
        findings = [{"id": "AP-12", "file": "/tmp/test.txt"}]
        results = fix_long_description(findings, dry_run=True)
        assert len(results) == 0


class TestGenerateManualFix:
    def test_ap01_suggestion_generated(self):
        findings = [{"id": "AP-01", "file": "/tmp/test.instructions.md"}]
        guide = generate_manual_fix_suggestions(findings)
        assert "AP-01" in guide
        assert "applyto" in guide.lower()

    def test_multiple_ap_types(self):
        findings = [
            {"id": "AP-01", "file": "a.md"},
            {"id": "AP-02", "file": "b.md"},
            {"id": "AP-04", "file": "c.md"},
        ]
        guide = generate_manual_fix_suggestions(findings)
        assert "AP-01" in guide
        assert "AP-02" in guide
        assert "AP-04" in guide
