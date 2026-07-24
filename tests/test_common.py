"""Tests for common.py — shared utilities."""
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from common import safe_int, safe_float, count_lines, safe_output_path


class TestSafeInt:
    def test_valid_int(self):
        assert safe_int("42") == 42
        assert safe_int(100) == 100
        assert safe_int("-5") == -5

    def test_invalid_returns_default(self):
        assert safe_int("abc") == 0
        assert safe_int(None) == 0
        assert safe_int("abc", default=99) == 99

    def test_float_truncates(self):
        assert safe_int(3.7) == 3


class TestSafeFloat:
    def test_valid_float(self):
        assert safe_float("3.14") == 3.14
        assert safe_float(2.0) == 2.0

    def test_invalid_returns_default(self):
        assert safe_float("abc") == 0.0
        assert safe_float(None, default=1.5) == 1.5


class TestCountLines:
    def test_non_empty_file(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("line1\nline2\n\nline4\n", encoding="utf-8")
        assert count_lines(str(f)) == 3  # non-blank
        assert count_lines(str(f), include_blank=True) == 4

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.md"
        f.write_text("", encoding="utf-8")
        assert count_lines(str(f)) == 0

    def test_missing_file(self):
        assert count_lines("/nonexistent/file.md") == 0


class TestSafeOutputPath:
    def test_within_base(self, tmp_path):
        base = str(tmp_path)
        out = safe_output_path(f"{base}/report.md", base_dir=base)
        assert out.name == "report.md"

    def test_traversal_blocked(self, tmp_path):
        base = str(tmp_path)
        with pytest.raises(ValueError):
            safe_output_path(f"{base}/../outside.md", base_dir=base)

    def test_absolute_path_resolved(self, tmp_path):
        p = tmp_path / "sub" / ".." / "report.md"
        out = safe_output_path(str(p), base_dir=str(tmp_path))
        assert out.parent == tmp_path
