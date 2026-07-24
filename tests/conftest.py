"""
Shared test fixtures and helpers for Saving-tokens-skill tests.
"""
import os
import sys
import tempfile
import pytest
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import scanner
import session_analyzer


@pytest.fixture
def temp_skill_dir():
    """Create a temporary skill directory with SKILL.md for testing."""
    with tempfile.TemporaryDirectory() as tmp:
        skill_dir = Path(tmp) / "test-skill"
        skill_dir.mkdir()
        yield skill_dir


@pytest.fixture
def make_skill_md():
    """Factory: create a SKILL.md with given content in a temp dir."""
    def _make(name: str, frontmatter: str, body: str = "# Test\n") -> str:
        tmp = tempfile.mkdtemp()
        skill_dir = Path(tmp) / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        content = f"---\n{frontmatter}\n---\n\n{body}"
        filepath = skill_dir / "SKILL.md"
        filepath.write_text(content, encoding="utf-8")
        refs = skill_dir / "references"
        refs.mkdir(exist_ok=True)
        return str(filepath)
    return _make


@pytest.fixture
def sample_frontmatter_well_formed():
    return {
        "name": "test-skill",
        "description": "Use when: testing Python code and running unit tests for skill validation",
        "allowed-tools": ["Read", "Grep"],
    }


@pytest.fixture
def sample_frontmatter_wildcard():
    return {
        "name": "bad-skill",
        "description": "test",
        "applyTo": "**",
    }


@pytest.fixture
def sample_frontmatter_vague():
    return {
        "name": "vague-skill",
        "description": "A helpful skill",
    }


@pytest.fixture
def sample_frontmatter_swiss_army():
    return {
        "name": "swiss-agent",
        "description": "Use when doing anything",
        "tools": ["read", "write", "edit", "search", "execute", "web", "agent", "todo"],
    }


@pytest.fixture
def sample_frontmatter_long_desc():
    return {
        "name": "verbose-skill",
        "description": "x" * 600,
    }
