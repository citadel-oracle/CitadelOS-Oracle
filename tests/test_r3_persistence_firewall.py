import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.argus.tactical_store import ArgusTacticalStore, ArgusTacticalStoreError
from src.argus.tactical_edge import ArgusTacticalEdgeEngine


def test_t1_persistence_oserror_does_not_kill_analytics_and_maintains_memory_state():
    """T1: Persistence OSError must not kill live analytics and must keep state in memory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store_path = Path(tmpdir) / "argus_tactical_state.json"
        store = ArgusTacticalStore(path=store_path)

        # 1. Successful first write
        calculation_id = "calc-001"
        projection = {
            "symbol": "NIFTY",
            "calculation_id": calculation_id,
            "regime": "BALANCED",
            "score": 75.0,
        }
        evidence_record = {"timestamp": "2026-08-18T15:00:00+05:30", "score": 75.0}

        published = store.publish(calculation_id, projection, evidence_record)
        assert published is True
        assert store.is_degraded is False
        assert store.latest()["calculation_id"] == calculation_id
        assert store.load()["latest_calculation_id"] == calculation_id

        # 2. Simulate disk full / OSError during atomic write
        calculation_id_2 = "calc-002"
        projection_2 = {
            "symbol": "NIFTY",
            "calculation_id": calculation_id_2,
            "regime": "TRENDING_BULL",
            "score": 88.0,
        }
        evidence_record_2 = {"timestamp": "2026-08-18T15:01:00+05:30", "score": 88.0}

        # Mock tempfile.mkstemp or os.fsync to throw OSError [Errno 28] No space left on device
        with patch("tempfile.mkstemp", side_effect=OSError(28, "No space left on device")):
            # Must NOT raise ArgusTacticalStoreError or kill the caller
            published_2 = store.publish(calculation_id_2, projection_2, evidence_record_2)
            assert published_2 is True
            assert store.is_degraded is True
            assert store.last_persistence_error is not None
            assert "No space left on device" in str(store.last_persistence_error)

            # In-memory canonical latest state MUST reflect the newest calculation!
            latest = store.latest()
            assert latest["calculation_id"] == calculation_id_2
            assert latest["regime"] == "TRENDING_BULL"
            assert latest["score"] == 88.0
            assert store.load()["latest_calculation_id"] == calculation_id_2

        # 3. Simulate recovery of disk space
        calculation_id_3 = "calc-003"
        projection_3 = {
            "symbol": "NIFTY",
            "calculation_id": calculation_id_3,
            "regime": "ACCELERATING",
            "score": 95.0,
        }
        evidence_record_3 = {"timestamp": "2026-08-18T15:02:00+05:30", "score": 95.0}

        published_3 = store.publish(calculation_id_3, projection_3, evidence_record_3)
        assert published_3 is True
        assert store.is_degraded is False
        assert store.latest()["calculation_id"] == calculation_id_3
        assert store.load()["latest_calculation_id"] == calculation_id_3
