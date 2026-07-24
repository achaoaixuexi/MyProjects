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
