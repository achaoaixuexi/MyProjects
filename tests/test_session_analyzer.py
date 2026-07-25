"""
Tests for session_analyzer.py — runtime token waste detection.
Covers all detect_* functions.
"""
import pytest
from session_analyzer import (
    detect_long_sessions_without_compaction,
    detect_late_compaction,
    detect_input_output_imbalance,
    detect_repeated_file_reads,
    detect_oversized_user_messages,
    detect_token_heavy_sessions,
    detect_full_file_minor_edit,
    detect_sequential_tool_calls,
    detect_repeated_unchanged_reads,
    detect_inline_code_without_file_ref,
    detect_redundant_code_output,
    detect_unused_session_memory,
    cross_reference,
    analyze,
    SessionFinding,
)


# ===================================================================
# SessionFinding
# ===================================================================

class TestSessionFinding:
    def test_to_dict(self):
        f = SessionFinding("RP-01", "high", "test detail",
                           session_id="sess-123", tokens_wasted=5000,
                           suggestion="use /compact")
        d = f.to_dict()
        assert d["id"] == "RP-01"
        assert d["severity"] == "high"
        assert d["session_id"] == "sess-123"
        assert d["tokens_wasted_est"] == 5000
        assert d["suggestion"] == "use /compact"


# ===================================================================
# RP-01: Long sessions without compaction
# ===================================================================

class TestRP01NoCompaction:
    def test_detects_long_session_no_checkpoints(self):
        data = {
            "sessions": [{"id": "sess-1", "turn_count": 25}],
            "checkpoints": [],
            "turns": [{"session_id": "sess-1"}] * 25,
        }
        results = detect_long_sessions_without_compaction(data)
        assert len(results) == 1
        assert results[0].id == "RP-01"
        assert results[0].tokens_wasted > 0

    def test_skips_session_with_checkpoints(self):
        data = {
            "sessions": [{"id": "sess-1", "turn_count": 25}],
            "checkpoints": [{"session_id": "sess-1", "checkpoint_number": 1}],
            "turns": [{"session_id": "sess-1"}] * 25,
        }
        results = detect_long_sessions_without_compaction(data)
        assert len(results) == 0

    def test_skips_short_sessions(self):
        data = {
            "sessions": [{"id": "sess-1", "turn_count": 5}],
            "checkpoints": [],
            "turns": [{"session_id": "sess-1"}] * 5,
        }
        results = detect_long_sessions_without_compaction(data)
        assert len(results) == 0

    def test_handles_empty_data(self):
        data = {"sessions": [], "checkpoints": [], "turns": []}
        results = detect_long_sessions_without_compaction(data)
        assert len(results) == 0


# ===================================================================
# RP-02: Late compaction
# ===================================================================

class TestRP02LateCompaction:
    def test_detects_late_compaction(self):
        data = {
            "sessions": [{"id": "sess-1"}],
            "checkpoints": [
                {"session_id": "sess-1", "checkpoint_number": 50},
            ],
            "turns": [{"session_id": "sess-1"}] * 80,
        }
        results = detect_late_compaction(data)
        assert len(results) == 1
        assert results[0].id == "RP-02"

    def test_accepts_early_compaction(self):
        data = {
            "sessions": [{"id": "sess-1"}],
            "checkpoints": [
                {"session_id": "sess-1", "checkpoint_number": 15},
            ],
            "turns": [{"session_id": "sess-1"}] * 80,
        }
        results = detect_late_compaction(data)
        assert len(results) == 0

    def test_handles_empty_data(self):
        results = detect_late_compaction({"sessions": [], "checkpoints": [], "turns": []})
        assert len(results) == 0


# ===================================================================
# RP-03: Input/output imbalance
# ===================================================================

class TestRP03Imbalance:
    def test_detects_severe_imbalance(self):
        data = {
            "events": [
                {"session_id": "sess-1", "type": "assistant.usage",
                 "usage_input_tokens": 50000, "usage_output_tokens": 2000},
            ]
        }
        results = detect_input_output_imbalance(data)
        assert len(results) == 1
        assert results[0].id == "RP-03"

    def test_accepts_balanced_ratio(self):
        data = {
            "events": [
                {"session_id": "sess-1", "type": "assistant.usage",
                 "usage_input_tokens": 3000, "usage_output_tokens": 2000},
            ]
        }
        results = detect_input_output_imbalance(data)
        assert len(results) == 0

    def test_handles_no_events(self):
        results = detect_input_output_imbalance({"events": []})
        assert len(results) == 0

    def test_handles_missing_data(self):
        results = detect_input_output_imbalance({})
        assert len(results) == 0

    def test_ignores_non_usage_events(self):
        data = {
            "events": [
                {"session_id": "sess-1", "type": "user.message"},
            ]
        }
        results = detect_input_output_imbalance(data)
        assert len(results) == 0


# ===================================================================
# RP-04: Repeated file reads
# ===================================================================

class TestRP04RepeatedReads:
    def test_detects_5_reads(self):
        data = {
            "session_files": [
                {"session_id": "sess-1", "file_path": "src/main.py"}
            ] * 5
        }
        results = detect_repeated_file_reads(data)
        assert len(results) == 1
        assert results[0].id == "RP-04"

    def test_skips_few_reads(self):
        data = {
            "session_files": [
                {"session_id": "sess-1", "file_path": "src/main.py"}
            ] * 3
        }
        results = detect_repeated_file_reads(data)
        assert len(results) == 0

    def test_multiple_files_with_repeats(self):
        data = {
            "session_files": (
                [{"session_id": "sess-1", "file_path": "a.py"}] * 5 +
                [{"session_id": "sess-1", "file_path": "b.py"}] * 6
            )
        }
        results = detect_repeated_file_reads(data)
        assert len(results) == 2

    def test_empty(self):
        results = detect_repeated_file_reads({"session_files": []})
        assert len(results) == 0


# ===================================================================
# RP-05: Oversized user messages
# ===================================================================

class TestRP05OversizedMessages:
    def test_detects_long_message(self):
        data = {
            "turns": [
                {"session_id": "sess-1", "user_message": "x" * 5000},
            ]
        }
        results = detect_oversized_user_messages(data)
        assert len(results) >= 1
        assert results[0].id == "RP-05"

    def test_skips_short_messages(self):
        data = {
            "turns": [
                {"session_id": "sess-1", "user_message": "short msg"},
            ]
        }
        results = detect_oversized_user_messages(data)
        assert len(results) == 0

    def test_limits_to_10(self):
        data = {
            "turns": [
                {"session_id": f"sess-{i}", "user_message": "x" * 5000}
                for i in range(20)
            ]
        }
        results = detect_oversized_user_messages(data)
        assert len(results) <= 10

    def test_checks_content_field(self):
        data = {
            "turns": [
                {"session_id": "sess-1", "user_content": "y" * 4000},
            ]
        }
        results = detect_oversized_user_messages(data)
        assert len(results) >= 1


# ===================================================================
# RP-06: Token-heavy sessions
# ===================================================================

class TestRP06TokenHeavy:
    def test_detects_outlier_session(self):
        # 1 outlier (100K) among 10 small sessions (1K each)
        # avg = 109K/10 = 10.9K, 3x = 32.7K → 100K > 32.7K ✓
        events = [{"session_id": "sess-big", "type": "assistant.usage",
                    "usage_input_tokens": 80000, "usage_output_tokens": 20000}]
        for i in range(9):
            events.append({"session_id": f"sess-{i}", "type": "assistant.usage",
                           "usage_input_tokens": 800, "usage_output_tokens": 200})
        data = {"events": events}
        results = detect_token_heavy_sessions(data)
        assert len(results) == 1
        assert results[0].id == "RP-06"
        assert "sess-big" in results[0].session_id

    def test_no_events_returns_empty(self):
        results = detect_token_heavy_sessions({"events": []})
        assert len(results) == 0

    def test_all_similar_returns_empty(self):
        data = {
            "events": [
                {"session_id": "sess-1", "type": "assistant.usage",
                 "usage_input_tokens": 3000, "usage_output_tokens": 1000},
                {"session_id": "sess-2", "type": "assistant.usage",
                 "usage_input_tokens": 3000, "usage_output_tokens": 1000},
            ]
        }
        results = detect_token_heavy_sessions(data)
        assert len(results) == 0


# ===================================================================
# Cross-reference
# ===================================================================

class TestCrossReference:
    def test_matches_ap01_rp03(self):
        static = [{"id": "AP-01"}]
        runtime = [{"id": "RP-03"}]
        result = cross_reference(runtime, static)
        assert len(result) == 1

    def test_matches_ap06_rp01(self):
        static = [{"id": "AP-06"}]
        runtime = [{"id": "RP-01"}]
        result = cross_reference(runtime, static)
        assert len(result) == 1

    def test_no_match(self):
        result = cross_reference([{"id": "RP-04"}], [{"id": "AP-12"}])
        assert len(result) == 0

    def test_empty_inputs(self):
        result = cross_reference([], [])
        assert len(result) == 0


# ===================================================================
# analyze() integration
# ===================================================================

class TestAnalyzeIntegration:
    def test_empty_data(self):
        data = {
            "backend": "cloud",
            "sessions": [],
            "turns": [],
            "events": [],
            "session_files": [],
            "checkpoints": [],
        }
        result = analyze(data)
        assert result["total_findings"] == 0
        assert result["backend"] == "cloud"

    def test_with_sample_data(self):
        data = {
            "backend": "cloud",
            "sessions": [{"id": "sess-1"}],
            "turns": [{"session_id": "sess-1"}] * 25,
            "events": [],
            "session_files": [
                {"session_id": "sess-1", "file_path": "x.py"}
            ] * 5,
            "checkpoints": [],
        }
        result = analyze(data, use_cache=False)
        assert result["total_findings"] > 0
        assert result["sessions_analyzed"] == 1
        assert result["turns_analyzed"] == 25

    def test_returns_cross_references_field(self):
        data = {
            "backend": "local",
            "sessions": [],
            "turns": [],
            "events": [],
            "session_files": [],
            "checkpoints": [],
        }
        result = analyze(data, static_findings=[{"id": "AP-01"}])
        assert "cross_references" in result


# ===================================================================
# Phase 1: Programming-project detectors (RP-07, RP-08, RP-10)
# ===================================================================

class TestRP07FullFileMinorEdit:
    def test_detects_large_range_read(self):
        data = {
            "session_files": [
                {"session_id": "s1", "file_path": "src/main.py",
                 "start_line": 1, "end_line": 1200},
            ]
        }
        results = detect_full_file_minor_edit(data)
        assert len(results) == 1
        assert results[0].id == "RP-07"
        assert results[0].tokens_wasted > 0

    def test_skips_small_reads(self):
        data = {
            "session_files": [
                {"session_id": "s1", "file_path": "src/main.py",
                 "start_line": 50, "end_line": 100},
            ]
        }
        results = detect_full_file_minor_edit(data)
        assert len(results) == 0

    def test_handles_missing_range(self):
        data = {
            "session_files": [
                {"session_id": "s1", "file_path": "src/main.py"},
            ]
        }
        results = detect_full_file_minor_edit(data)
        assert len(results) == 0

    def test_empty_data(self):
        results = detect_full_file_minor_edit({"session_files": []})
        assert len(results) == 0


class TestRP08SequentialToolCalls:
    def test_detects_3_serial_reads(self):
        data = {
            "tool_calls": [
                {"session_id": "s1", "tool_name": "read_file"},
                {"session_id": "s1", "tool_name": "read_file"},
                {"session_id": "s1", "tool_name": "read_file"},
            ]
        }
        results = detect_sequential_tool_calls(data)
        assert len(results) == 1
        assert results[0].id == "RP-08"

    def test_skips_2_serial(self):
        data = {
            "tool_calls": [
                {"session_id": "s1", "tool_name": "read_file"},
                {"session_id": "s1", "tool_name": "read_file"},
            ]
        }
        results = detect_sequential_tool_calls(data)
        assert len(results) == 0

    def test_detects_mixed_tools(self):
        data = {
            "tool_calls": [
                {"session_id": "s1", "tool_name": "read_file"},
                {"session_id": "s1", "tool_name": "grep_search"},
                {"session_id": "s1", "tool_name": "list_dir"},
                {"session_id": "s1", "tool_name": "file_search"},
            ]
        }
        results = detect_sequential_tool_calls(data)
        assert len(results) == 1  # 4 in a row

    def test_interrupted_streak(self):
        data = {
            "tool_calls": [
                {"session_id": "s1", "tool_name": "read_file"},
                {"session_id": "s1", "tool_name": "write_file"},
                {"session_id": "s1", "tool_name": "read_file"},
                {"session_id": "s1", "tool_name": "read_file"},
            ]
        }
        results = detect_sequential_tool_calls(data)
        assert len(results) == 0  # max streak is 2 after interruption

    def test_empty(self):
        results = detect_sequential_tool_calls({})
        assert len(results) == 0

    def test_no_tool_calls_field(self):
        results = detect_sequential_tool_calls({"events": []})
        assert len(results) == 0


class TestRP10RepeatedUnchangedReads:
    def test_detects_3_reads_same_file(self):
        data = {
            "session_files": [
                {"session_id": "s1", "file_path": "src/config.py"},
                {"session_id": "s1", "file_path": "src/config.py"},
                {"session_id": "s1", "file_path": "src/config.py"},
            ]
        }
        results = detect_repeated_unchanged_reads(data)
        assert len(results) == 1
        assert results[0].id == "RP-10"
        assert results[0].tokens_wasted > 0

    def test_skips_2_reads(self):
        data = {
            "session_files": [
                {"session_id": "s1", "file_path": "src/config.py"},
                {"session_id": "s1", "file_path": "src/config.py"},
            ]
        }
        results = detect_repeated_unchanged_reads(data)
        assert len(results) == 0

    def test_different_mtimes_skipped(self):
        data = {
            "session_files": [
                {"session_id": "s1", "file_path": "src/x.py",
                 "file_mtime": "100"},
                {"session_id": "s1", "file_path": "src/x.py",
                 "file_mtime": "200"},
                {"session_id": "s1", "file_path": "src/x.py",
                 "file_mtime": "300"},
            ]
        }
        results = detect_repeated_unchanged_reads(data)
        assert len(results) == 0  # file changed between reads

    def test_same_mtime_detected(self):
        data = {
            "session_files": [
                {"session_id": "s1", "file_path": "src/x.py",
                 "file_mtime": "100"},
                {"session_id": "s1", "file_path": "src/x.py",
                 "file_mtime": "100"},
                {"session_id": "s1", "file_path": "src/x.py",
                 "file_mtime": "100"},
            ]
        }
        results = detect_repeated_unchanged_reads(data)
        assert len(results) == 1

    def test_empty(self):
        results = detect_repeated_unchanged_reads({})
        assert len(results) == 0


# ===================================================================
# Phase 2: Message-quality & Session-memory detectors  (RP-09,11,12)
# ===================================================================

class TestRP09InlineCodeWithoutFileRef:
    def test_detects_large_code_no_file_ref(self):
        data = {
            "turns": [{
                "session_id": "s1",
                "user_message": "Fix this:\n```python\n" + "x = 1\n" * 200 + "```",
            }]
        }
        results = detect_inline_code_without_file_ref(data)
        assert len(results) == 1
        assert results[0].id == "RP-09"

    def test_skips_with_file_ref(self):
        data = {
            "turns": [{
                "session_id": "s1",
                "user_message": "Fix @src/main.py:\n```python\nx = 1\n```",
            }]
        }
        results = detect_inline_code_without_file_ref(data)
        assert len(results) == 0  # has @file ref

    def test_skips_small_code(self):
        data = {
            "turns": [{
                "session_id": "s1",
                "user_message": "```python\nprint('hi')\n```",
            }]
        }
        results = detect_inline_code_without_file_ref(data)
        assert len(results) == 0

    def test_empty(self):
        results = detect_inline_code_without_file_ref({})
        assert len(results) == 0


class TestRP11RedundantCodeOutput:
    def test_detects_duplicate_blocks(self):
        # Need >200 chars per block
        line = "    result.append(item)\n"
        block = "def process(items):\n" + line * 12 + "    return result\n"
        data = {
            "turns": [
                {"session_id": "s1", "assistant_message": "```python\n" + block + "```"},
                {"session_id": "s1", "assistant_message": "```python\n" + block + "```"},
            ]
        }
        results = detect_redundant_code_output(data)
        assert len(results) == 1
        assert results[0].id == "RP-11"

    def test_skips_different_blocks(self):
        data = {
            "turns": [
                {"session_id": "s1", "assistant_message": "```python\nx=1\n```"},
                {"session_id": "s1", "assistant_message": "```python\ny=2\n```"},
            ]
        }
        results = detect_redundant_code_output(data)
        assert len(results) == 0

    def test_skips_small_blocks(self):
        data = {
            "turns": [
                {"session_id": "s1", "assistant_message": "```python\nx=1\n```"},
                {"session_id": "s1", "assistant_message": "```python\nx=1\n```"},
            ]
        }
        results = detect_redundant_code_output(data)
        assert len(results) == 0  # blocks too small (<200 chars)

    def test_empty(self):
        results = detect_redundant_code_output({})
        assert len(results) == 0


class TestRP12UnusedSessionMemory:
    def test_detects_repeated_terms(self):
        data = {
            "turns": [
                {"session_id": "s1", "user_message": "How to use DataManager with TokenOptimizer and UserSession?"},
                {"session_id": "s1", "user_message": "DataManager middleware and UserSession config"},
                {"session_id": "s1", "user_message": "TokenOptimizer session with DataManager and UserSession"},
                {"session_id": "s1", "user_message": "DataManager, TokenOptimizer, UserSession best practices"},
            ]
        }
        results = detect_unused_session_memory(data)
        assert len(results) == 1
        assert results[0].id == "RP-12"

    def test_skips_few_repeats(self):
        data = {
            "turns": [
                {"session_id": "s1", "user_message": "What is FastAPI?"},
                {"session_id": "s1", "user_message": "How to use Docker?"},
            ]
        }
        results = detect_unused_session_memory(data)
        assert len(results) == 0

    def test_skips_few_turns(self):
        data = {
            "turns": [
                {"session_id": "s1", "user_message": "FastAPI setup"},
                {"session_id": "s1", "user_message": "FastAPI routes"},
            ]
        }
        results = detect_unused_session_memory(data)
        assert len(results) == 0

    def test_empty(self):
        results = detect_unused_session_memory({})
        assert len(results) == 0
