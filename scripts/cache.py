"""
Saving-tokens-skill — File-system cache for incremental scanning.

Strategy:
  - Cache key = (filepath, mtime_ns, file_size) → avoids re-scanning
    unchanged files.
  - Session-analyzer cache = set of already-analysed session_ids.
  - Cache location: <project_root>/.token_cache/

Usage:
    from cache import FileScanCache, SessionCache
"""

import json
import os
from pathlib import Path
from datetime import datetime


DEFAULT_CACHE_DIR = ".token_cache"


# ── File-scan cache (for scanner.py) ──

class FileScanCache:
    """Maps file identity → cached Finding dicts."""

    def __init__(self, project_root: str | Path):
        self.root = Path(project_root)
        self.cache_dir = self.root / DEFAULT_CACHE_DIR
        self.cache_file = self.cache_dir / "scan_cache.json"
        self._data: dict[str, dict] = {}  # key → {findings, cached_at}
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._data = {}
        self._loaded = True

    def _save(self):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    @staticmethod
    def _file_key(filepath: str) -> str | None:
        """Build a stable cache key from file metadata."""
        try:
            st = os.stat(filepath)
            return f"{filepath}::{st.st_mtime_ns}::{st.st_size}"
        except OSError:
            return None

    def get(self, filepath: str) -> list[dict] | None:
        """Return cached findings for *filepath*, or None if stale/missing."""
        self._load()
        key = self._file_key(filepath)
        if key is None:
            return None
        entry = self._data.get(key)
        if entry is None:
            return None
        return entry.get("findings")

    def put(self, filepath: str, findings: list[dict]):
        """Store findings under the current file identity."""
        key = self._file_key(filepath)
        if key is None:
            return
        self._data[key] = {
            "findings": findings,
            "cached_at": datetime.now().isoformat(),
        }
        self._save()

    def purge_stale(self, known_files: set[str]):
        """Remove entries whose filepaths no longer exist in *known_files*."""
        self._load()
        stale = []
        for key in list(self._data.keys()):
            fpath = key.split("::", 1)[0]
            if fpath not in known_files:
                stale.append(key)
        for k in stale:
            del self._data[k]
        if stale:
            self._save()

    def clear(self):
        """Delete all cached data."""
        self._data = {}
        self._save()

    def __len__(self) -> int:
        self._load()
        return len(self._data)


# ── Session-analysis cache (for session_analyzer.py) ──

class SessionCache:
    """Remembers which session_ids have already been analysed."""

    def __init__(self, project_root: str | Path):
        self.root = Path(project_root)
        self.cache_dir = self.root / DEFAULT_CACHE_DIR
        self.cache_file = self.cache_dir / "session_cache.json"
        self._analyzed: set[str] = set()
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._analyzed = set(data.get("analyzed_ids", []))
            except (json.JSONDecodeError, OSError):
                self._analyzed = set()
        self._loaded = True

    def _save(self):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump({"analyzed_ids": sorted(self._analyzed)}, f, indent=2)

    def is_analyzed(self, session_id: str) -> bool:
        self._load()
        return session_id in self._analyzed

    def mark_analyzed(self, session_id: str):
        self._load()
        self._analyzed.add(session_id)
        self._save()

    def mark_analyzed_batch(self, session_ids: list[str]):
        self._load()
        self._analyzed.update(session_ids)
        self._save()

    def clear(self):
        self._analyzed = set()
        self._save()

    def __len__(self) -> int:
        self._load()
        return len(self._analyzed)
