import json
import os
import threading
from time import perf_counter
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import pytest

from src.strategy_lab.storage import ImmutableStream


def test_append_batch_preserves_chain_and_idempotency_with_one_logical_batch(temp_stream_path):
    stream = ImmutableStream(temp_stream_path)
    rows = stream.append_batch(
        [
            ("PACKET", {"sequence": 1}, None, "packet-1"),
            ("PACKET", {"sequence": 2}, None, "packet-2"),
            ("PACKET", {"sequence": 2}, None, "packet-2"),
        ]
    )
    assert rows[1]["record_hash"] == rows[2]["record_hash"]
    assert len(stream.read()) == 2
    assert stream.verify() == {"valid": True, "records": 2, "failure_index": None}


def test_append_batch_does_not_copy_entire_idempotency_history(temp_stream_path):
    stream = ImmutableStream(temp_stream_path)
    stream.append_batch(
        [("PACKET", {"sequence": index}, None, f"packet-{index}") for index in range(100)]
    )
    with mock.patch("src.strategy_lab.storage.deepcopy", wraps=deepcopy) as copy_value:
        stream.append_batch([("PACKET", {"sequence": 101}, None, "packet-101")])
    assert copy_value.call_count < 10


@pytest.fixture
def temp_stream_path():
    with TemporaryDirectory() as d:
        yield Path(d) / "test_stream.jsonl"


def test_empty_stream_first_append(temp_stream_path):
    stream = ImmutableStream(temp_stream_path)
    res = stream.append("TEST", {"a": 1})
    assert res["previous_hash"] == "GENESIS"
    assert len(stream.read()) == 1


def test_existing_file_bootstrap_preserves_hash_continuity(temp_stream_path):
    stream1 = ImmutableStream(temp_stream_path)
    r1 = stream1.append("TEST", {"a": 1})
    r2 = stream1.append("TEST", {"a": 2})

    stream2 = ImmutableStream(temp_stream_path)
    r3 = stream2.append("TEST", {"a": 3})

    assert len(stream2.read()) == 3
    assert r3["previous_hash"] == r2["record_hash"]


def test_duplicate_idempotency_key_returns_original_record(temp_stream_path):
    stream = ImmutableStream(temp_stream_path)
    r1 = stream.append("TEST", {"a": 1}, idempotency_key="key1")
    r2 = stream.append("TEST", {"a": 2}, idempotency_key="key1")

    assert r1["record_id"] == r2["record_id"]
    assert len(stream.read()) == 1


def test_duplicate_detection_survives_new_instance_restart(temp_stream_path):
    stream1 = ImmutableStream(temp_stream_path)
    r1 = stream1.append("TEST", {"a": 1}, idempotency_key="key1")

    stream2 = ImmutableStream(temp_stream_path)
    r2 = stream2.append("TEST", {"a": 2}, idempotency_key="key1")

    assert r1["record_id"] == r2["record_id"]
    assert len(stream2.read()) == 1


def test_100_sequential_records_produce_valid_chain(temp_stream_path):
    stream = ImmutableStream(temp_stream_path)
    for i in range(100):
        stream.append("TEST", {"i": i})

    assert len(stream.read()) == 100
    assert stream.verify()["valid"] is True


def test_concurrent_same_instance_threads_preserve_chain(temp_stream_path):
    stream = ImmutableStream(temp_stream_path)

    def worker(idx):
        stream.append("TEST", {"idx": idx})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(stream.read()) == 20
    assert stream.verify()["valid"] is True


def test_external_valid_append_triggers_safe_resynchronisation(temp_stream_path):
    stream = ImmutableStream(temp_stream_path)
    r1 = stream.append("TEST", {"a": 1})

    stream_external = ImmutableStream(temp_stream_path)
    r2 = stream_external.append("TEST", {"a": 2})

    r3 = stream.append("TEST", {"a": 3})
    assert r3["previous_hash"] == r2["record_hash"]
    assert len(stream.read()) == 3
    assert stream.verify()["valid"] is True


def test_malformed_truncated_trailing_record_fails_closed(temp_stream_path):
    stream = ImmutableStream(temp_stream_path)
    stream.append("TEST", {"a": 1})

    with temp_stream_path.open("a", encoding="utf-8") as f:
        f.write("{bad json\n")

    stream2 = ImmutableStream(temp_stream_path)
    with pytest.raises(RuntimeError, match="STRATEGY_LAB_IMMUTABLE_STREAM_CORRUPTED"):
        stream2.append("TEST", {"a": 2})


def test_simulated_write_failure_does_not_advance_cached_state(temp_stream_path):
    stream = ImmutableStream(temp_stream_path)
    r1 = stream.append("TEST", {"a": 1})
    
    # Force a state cache before mocking
    _ = stream._get_state()
    orig_state_hash = stream._state_cache["previous_hash"]

    # Mock Path.open to raise an OS error during write
    with mock.patch('pathlib.Path.open', side_effect=OSError("Disk full")):
        with pytest.raises(OSError):
            stream.append("TEST", {"a": 2}, idempotency_key="key2")

    # Ensure cache is not advanced
    assert stream._state_cache["previous_hash"] == orig_state_hash
    assert "key2" not in stream._indexed_rows(("key2",))
    
    # We can still append safely afterwards
    r3 = stream.append("TEST", {"a": 3})
    assert r3["previous_hash"] == r1["record_hash"]


def test_read_behaviour_remains_unchanged(temp_stream_path):
    stream = ImmutableStream(temp_stream_path)
    stream.append("TEST", {"a": 1})
    stream.append("TEST", {"a": 2})
    stream.append("TEST", {"a": 3})
    
    rows = stream.read()
    assert len(rows) == 3
    assert [r["payload"]["a"] for r in rows] == [1, 2, 3]
    
    rows_limit = stream.read(limit=2)
    assert len(rows_limit) == 2
    assert [r["payload"]["a"] for r in rows_limit] == [2, 3]


def test_warm_append_does_not_invoke_read(temp_stream_path):
    stream = ImmutableStream(temp_stream_path)
    stream.append("TEST", {"a": 1})
    
    with mock.patch.object(stream, 'read') as mock_read:
        stream.append("TEST", {"a": 2})
        mock_read.assert_not_called()


def test_cold_bootstrap_occurs_once(temp_stream_path):
    stream = ImmutableStream(temp_stream_path)
    
    with mock.patch.object(stream, '_bootstrap', wraps=stream._bootstrap) as mock_bootstrap:
        # First append uses bootstrap
        stream.append("TEST", {"a": 1})
        
        # Second append should hit cache
        stream.append("TEST", {"a": 2})
        
        # Third append should hit cache
        stream.append("TEST", {"a": 3})
        
        mock_bootstrap.assert_called_once()


def test_file_replacement_triggers_resynchronisation(temp_stream_path):
    stream = ImmutableStream(temp_stream_path)
    r1 = stream.append("TEST", {"a": 1})
    
    # Trigger state caching
    stream._get_state()
    
    # Replace file entirely using a temp copy (changes inode)
    temp_stream_path_2 = temp_stream_path.with_name("temp_copy.jsonl")
    temp_stream_path_2.write_text(temp_stream_path.read_text())
    
    # Append a new record to the new file via a different instance
    stream2 = ImmutableStream(temp_stream_path_2)
    r2 = stream2.append("TEST", {"a": 2})
    
    # Replace original file with the new file
    os.replace(temp_stream_path_2, temp_stream_path)
    
    # Original stream should resync due to inode/mtime/size change
    with mock.patch.object(stream, '_bootstrap', wraps=stream._bootstrap) as mock_bootstrap:
        r3 = stream.append("TEST", {"a": 3})
        mock_bootstrap.assert_called_once()
        assert r3["previous_hash"] == r2["record_hash"]


def test_cross_process_safety_invariant_documentation(temp_stream_path):
    """
    DOCUMENTATION INVARIANT:
    ImmutableStream relies on threading.RLock() for concurrent within-process appends.
    It does NOT use OS-level locks (e.g. fcntl.flock).
    Cross-process sequential appends (process A writes, then process B writes) are safe 
    because _file_signature() forces an idempotency/hash resync.
    However, strictly concurrent cross-process appends might interleave write() calls 
    at the OS level, creating corrupted JSON segments.
    Single-writer invariant per file is strongly recommended.
    """
    stream1 = ImmutableStream(temp_stream_path)
    stream2 = ImmutableStream(temp_stream_path)
    
    r1 = stream1.append("TEST", {"a": 1})
    r2 = stream2.append("TEST", {"a": 2})
    
    # The second instance safely triggers a resync before appending
    assert r2["previous_hash"] == r1["record_hash"]


def test_valid_checkpoint_resumes_without_scanning_history(temp_stream_path):
    first = ImmutableStream(temp_stream_path)
    first.append_batch(
        [("TEST", {"i": i}, None, f"key-{i}") for i in range(2_000)],
        return_rows=False,
    )
    resumed = ImmutableStream(temp_stream_path)
    row = resumed.append("TEST", {"i": 2_000}, idempotency_key="key-2000")
    assert resumed.resume_metrics()["mode"] == "CHECKPOINT"
    assert resumed.resume_metrics()["scanned_bytes"] == 0
    assert row["payload"]["i"] == 2_000


def test_absent_checkpoint_rebuilds_legacy_stream_once(temp_stream_path):
    first = ImmutableStream(temp_stream_path)
    first.append("TEST", {"i": 1}, idempotency_key="key-1")
    first._discard_checkpoint()
    resumed = ImmutableStream(temp_stream_path)
    duplicate = resumed.append("TEST", {"i": 999}, idempotency_key="key-1")
    assert resumed.resume_metrics()["mode"] == "FULL_REBUILD"
    assert duplicate["payload"]["i"] == 1
    assert len(resumed.read()) == 1


def test_stale_checkpoint_recovers_only_valid_uncheckpointed_tail(temp_stream_path):
    first = ImmutableStream(temp_stream_path)
    one = first.append("TEST", {"i": 1}, idempotency_key="key-1")
    with mock.patch.object(first, "_save_checkpoint", side_effect=OSError("crash")):
        with pytest.raises(OSError):
            first.append("TEST", {"i": 2}, idempotency_key="key-2")
    resumed = ImmutableStream(temp_stream_path)
    duplicate = resumed.append("TEST", {"i": 200}, idempotency_key="key-2")
    assert resumed.resume_metrics()["mode"] == "TAIL_RECOVERY"
    assert duplicate["payload"]["i"] == 2
    assert resumed.read()[1]["previous_hash"] == one["record_hash"]


def test_corrupt_checkpoint_falls_back_to_authoritative_stream(temp_stream_path):
    first = ImmutableStream(temp_stream_path)
    original = first.append("TEST", {"i": 1}, idempotency_key="key-1")
    if first._checkpoint is not None:
        first._checkpoint.close()
        first._checkpoint = None
    first.checkpoint_path.write_bytes(b"not-a-sqlite-database")
    resumed = ImmutableStream(temp_stream_path)
    duplicate = resumed.append("TEST", {"i": 2}, idempotency_key="key-1")
    assert resumed.resume_metrics()["mode"] == "SAFE_FALLBACK_REBUILD"
    assert duplicate["record_hash"] == original["record_hash"]


def test_stream_truncated_behind_checkpoint_fails_closed(temp_stream_path):
    stream = ImmutableStream(temp_stream_path)
    stream.append("TEST", {"i": 1}, idempotency_key="key-1")
    with temp_stream_path.open("r+b") as handle:
        handle.truncate(max(1, temp_stream_path.stat().st_size // 2))
    resumed = ImmutableStream(temp_stream_path)
    with pytest.raises(RuntimeError, match="IMMUTABLE_STREAM_CORRUPTED"):
        resumed.append("TEST", {"i": 2}, idempotency_key="key-2")


def test_same_length_stream_tampering_invalidates_checkpoint(temp_stream_path):
    stream = ImmutableStream(temp_stream_path)
    stream.append("TEST", {"value": "alpha"}, idempotency_key="key-1")
    content = temp_stream_path.read_bytes()
    temp_stream_path.write_bytes(content.replace(b'"alpha"', b'"omega"'))
    resumed = ImmutableStream(temp_stream_path)
    with pytest.raises(RuntimeError, match="HASH_CHAIN_INVALID"):
        resumed.append("TEST", {"value": "next"}, idempotency_key="key-2")


def test_restart_preserves_sequence_order_and_replay_equality(temp_stream_path):
    first = ImmutableStream(temp_stream_path)
    rows = first.append_batch(
        [("TEST", {"sequence": i}, None, f"key-{i}") for i in range(50)]
    )
    resumed = ImmutableStream(temp_stream_path)
    last = resumed.append("TEST", {"sequence": 50}, idempotency_key="key-50")
    replay = resumed.read()
    assert [row["payload"]["sequence"] for row in replay] == list(range(51))
    assert last["previous_hash"] == rows[-1]["record_hash"]
    assert resumed.verify()["valid"] is True


def test_resume_cost_uses_checkpoint_not_total_history(temp_stream_path):
    stream = ImmutableStream(temp_stream_path, max_bytes=100 * 1024 * 1024)
    stream.append_batch(
        [
            ("TEST", {"sequence": i, "payload": "x" * 3_500}, None, f"key-{i}")
            for i in range(3_000)
        ],
        return_rows=False,
    )
    assert temp_stream_path.stat().st_size >= 10 * 1024 * 1024
    resumed = ImmutableStream(temp_stream_path, max_bytes=100 * 1024 * 1024)
    started = perf_counter()
    resumed.append("TEST", {"sequence": 3_000}, idempotency_key="key-3000")
    elapsed_ms = (perf_counter() - started) * 1_000
    assert resumed.resume_metrics()["mode"] == "CHECKPOINT"
    assert resumed.resume_metrics()["scanned_bytes"] == 0
    assert elapsed_ms < 250
