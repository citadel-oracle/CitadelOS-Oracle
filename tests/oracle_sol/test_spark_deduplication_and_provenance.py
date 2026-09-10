"""Comprehensive Unit & Integration Test Suite for Spark Deduplication, Provenance, & Nonce Association."""

import json
from unittest import mock
import pytest
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src.oracle_sol.external_context import (
    validate_external_context_payload,
    classify_radar_item_time,
    RadarTimeClassification,
)
from scripts.citadel_spark_live_runner import (
    normalize_fact_title,
    generate_deterministic_fact_id,
    parse_event_timestamps_from_text,
    deduplicate_and_merge_session_events,
    parse_spark_markdown,
    get_persisted_session_events,
    finalize_captured_response,
)

IST = ZoneInfo("Asia/Kolkata")


# ── 1. Timestamp Test Matrix ──

def test_timestamp_matrix_full_explicit_datetime():
    """1. Full explicit ISO datetime -> parsed exactly."""
    text = "Release published on 2026-09-01T12:00:00Z by official portal."
    utc, ist, pub = parse_event_timestamps_from_text(text, "2026-09-01")
    assert utc == "2026-09-01T12:00:00Z"
    assert ist == "17:30:00"
    assert pub == "2026-09-01T12:00:00Z"


def test_timestamp_matrix_date_only():
    """2. Date only without time -> remains unknown event time (no fake midnight time invented)."""
    text = "Report released on 2026-09-01 during morning."
    utc, ist, pub = parse_event_timestamps_from_text(text, "2026-09-01")
    # Date only does not invent a fake time
    assert ist is None
    assert utc is None


def test_timestamp_matrix_today_time_only():
    """3. Today explicit time -> parsed with session date."""
    text = "Intraday headline reported at 2:14 PM IST."
    utc, ist, pub = parse_event_timestamps_from_text(text, "2026-09-01")
    assert ist == "14:14:00"
    assert utc == "2026-09-01T08:44:00Z"


def test_timestamp_matrix_historical_datetime_no_session_date_attaching():
    """4. Historical date + time -> does NOT attach current session date."""
    text = "Settlement concluded on August 28 at 15:30 IST."
    utc, ist, pub = parse_event_timestamps_from_text(text, "2026-09-01")
    assert ist == "15:30:00"
    assert utc == "2026-08-28T10:00:00Z"


def test_timestamp_matrix_friday_close_unknown():
    """5. 'Friday close' alone -> remains timestamp unknown (no fake timestamp fabricated)."""
    text = "S&P 500 settled lower at Friday close."
    utc, ist, pub = parse_event_timestamps_from_text(text, "2026-09-01")
    assert utc is None
    assert ist is None
    assert pub is None


def test_timestamp_matrix_no_timestamp_unknown():
    """6. No timestamp in text -> returns None (classified as TIMESTAMP_UNKNOWN)."""
    text = "Dow Jones futures baseline liquidity digesting rate risks."
    utc, ist, pub = parse_event_timestamps_from_text(text, "2026-09-01")
    assert utc is None
    assert ist is None
    assert pub is None


# ── 2. Timezone Pair Synchronization ──

def test_generated_time_pair_synchronized():
    """Verify generated_at_utc and generated_at_ist represent the exact same instant."""
    raw = json.dumps({
        "scan_nonce": "NONCE_TEST_12345",
        "scheduled_events": [], "breaking_events": [], "overnight_context": [],
        "index_specific_events": [],
        "global_context": [{
            "title": "US futures baseline",
            "factual_summary": "A sourced baseline observation was returned.",
            "status": "UNCONFIRMED",
        }],
        "data_gaps": [], "sources": [],
    })
    parsed = parse_spark_markdown(raw, "2026-09-01", scan_nonce="NONCE_TEST_12345")
    utc_str = parsed["generated_at_utc"]
    ist_str = parsed["generated_at_ist"]
    
    dt_utc = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    dt_ist = dt_utc.astimezone(IST)
    assert dt_ist.strftime("%H:%M:%S") == ist_str, "generated_at_utc and generated_at_ist must match the exact same instant"


# ── 3. Nonce Association & Validation ──

def test_nonce_association_verified():
    """Verify response containing matching nonce is accepted."""
    raw = json.dumps({
        "scan_nonce": "NONCE_20260901_143000_abcd",
        "scheduled_events": [], "breaking_events": [], "overnight_context": [],
        "index_specific_events": [],
        "global_context": [{
            "title": "US futures baseline",
            "factual_summary": "A sourced baseline observation was returned.",
            "status": "UNCONFIRMED",
        }],
        "data_gaps": [], "sources": [],
    })
    parsed = parse_spark_markdown(raw, "2026-09-01", scan_nonce="NONCE_20260901_143000_abcd")
    assert parsed["scan_nonce"] == "NONCE_20260901_143000_abcd"
    assert parsed["nonce_verified"] is True


def test_nonce_mismatch_fails_association():
    """Verify response with missing or mismatched nonce fails association check."""
    raw = json.dumps({
        "scan_nonce": "OLD_NONCE_9999",
        "scheduled_events": [], "breaking_events": [], "overnight_context": [],
        "index_specific_events": [],
        "global_context": [{
            "title": "US futures baseline",
            "factual_summary": "A sourced baseline observation was returned.",
            "status": "UNCONFIRMED",
        }],
        "data_gaps": [], "sources": [],
    })
    with pytest.raises(ValueError, match="NONCE_MISMATCH"):
        parse_spark_markdown(raw, "2026-09-01", scan_nonce="NONCE_20260901_143000_abcd")


# ── 4. Deduplication & Provenance Tests A–E ──

def test_dedup_case_a_exact_same_event_no_duplicate():
    """Test A: Exact same event on next scan -> 1 unified event."""
    fid = generate_deterministic_fact_id("sched", "India Q1 GDP Release")
    existing = [{"fact_id": fid, "title": "India Q1 GDP Release", "factual_summary": "7.8% growth", "source_name": "UNKNOWN", "verification_status": "UNVERIFIED"}]
    incoming = [{"fact_id": fid, "title": "India Q1 GDP Release", "factual_summary": "7.8% growth", "source_name": "UNKNOWN", "verification_status": "UNVERIFIED"}]
    merged, sources = deduplicate_and_merge_session_events(existing, incoming)
    assert len(merged) == 1
    assert merged[0]["title"] == "India Q1 GDP Release"


def test_dedup_case_b_same_title_changed_content():
    """Test B: Same title with changed factual content -> content updated, identity preserved."""
    fid = generate_deterministic_fact_id("break", "Middle East Escalation")
    existing = [{"fact_id": fid, "title": "Middle East Escalation", "factual_summary": "Initial report", "status": "DEVELOPING", "source_name": "UNKNOWN", "verification_status": "UNVERIFIED"}]
    incoming = [{"fact_id": fid, "title": "Middle East Escalation", "factual_summary": "Military strikes exchanged, Brent crude above $90/bbl", "status": "DEVELOPING", "source_name": "UNKNOWN", "verification_status": "UNVERIFIED"}]
    merged, sources = deduplicate_and_merge_session_events(existing, incoming)
    assert len(merged) == 1
    assert "Military strikes exchanged" in merged[0]["factual_summary"]


def test_dedup_case_c_multi_source_provenance_retention():
    """Test C: Same event from two distinct sources -> preserves BOTH source records in sources list."""
    fid = generate_deterministic_fact_id("sched", "India Macro Output")
    existing = [{
        "fact_id": fid,
        "title": "India Macro Output",
        "factual_summary": "7.8% growth",
        "source_name": "MoSPI",
        "verification_status": "UNVERIFIED",
        "sources_list": [{"source_name": "MoSPI", "reliability_tier": "OFFICIAL_GOVERNMENT"}]
    }]
    incoming = [{
        "fact_id": fid,
        "title": "India Macro Output",
        "factual_summary": "7.8% growth",
        "source_name": "Press Information Bureau",
        "verification_status": "UNVERIFIED",
        "sources_list": [{"source_name": "Press Information Bureau", "reliability_tier": "OFFICIAL_GOVERNMENT"}]
    }]
    merged, combined_sources = deduplicate_and_merge_session_events(existing, incoming)
    assert len(merged) == 1
    source_names = {s["source_name"] for s in combined_sources}
    assert "MoSPI" in source_names, "Source 1 must be retained in sources list"
    assert "Press Information Bureau" in source_names, "Source 2 must be retained in sources list"
    assert len(combined_sources) == 2, "Both source records must be preserved without silent overwrite"


def test_dedup_case_d_genuinely_new_development():
    """Test D: Genuinely new development -> added."""
    fid1 = generate_deterministic_fact_id("sched", "India Q1 GDP")
    fid2 = generate_deterministic_fact_id("sched", "MSCI CAS Rebalance")
    existing = [{"fact_id": fid1, "title": "India Q1 GDP", "factual_summary": "7.8%", "source_name": "UNKNOWN", "verification_status": "UNVERIFIED"}]
    incoming = [{"fact_id": fid2, "title": "MSCI CAS Rebalance", "factual_summary": "₹39,718 Cr turnover", "source_name": "UNKNOWN", "verification_status": "UNVERIFIED"}]
    merged, sources = deduplicate_and_merge_session_events(existing, incoming)
    assert len(merged) == 2


def test_dedup_case_e_baseline_market_values_update():
    """Test E: Baseline market values update without creating breaking news duplicates."""
    def response(nonce, value):
        return json.dumps({
            "scan_nonce": nonce,
            "scheduled_events": [], "breaking_events": [], "overnight_context": [],
            "index_specific_events": [],
            "global_context": [{
                "title": "Dow Jones Futures baseline",
                "factual_summary": value,
                "status": "UNCONFIRMED",
            }],
            "data_gaps": [], "sources": [],
        })
    raw1 = response("N1", "Reported level approximately 53,300.")
    raw2 = response("N2", "Reported level approximately 53,350.")
    p1 = parse_spark_markdown(raw1, "2026-09-01", scan_nonce="N1")
    p2 = parse_spark_markdown(raw2, "2026-09-01", scan_nonce="N2")
    assert len(p1["breaking_events"]) == 0
    assert len(p2["breaking_events"]) == 0
    assert p1["global_context"][0]["fact_id"] == p2["global_context"][0]["fact_id"]


def test_structured_parser_rejects_empty_context_and_self_promotion():
    empty = json.dumps({
        "scan_nonce": "N1", "scheduled_events": [], "breaking_events": [],
        "overnight_context": [], "index_specific_events": [], "global_context": [],
        "data_gaps": [], "sources": [],
    })
    with pytest.raises(ValueError, match="SPARK_RESPONSE_EMPTY_CONTEXT"):
        parse_spark_markdown(empty, "2026-09-01", scan_nonce="N1")

    nonempty = json.dumps({
        "scan_nonce": "N2", "scheduled_events": [], "breaking_events": [],
        "overnight_context": [], "index_specific_events": [],
        "global_context": [{
            "title": "CBOE VIX observation",
            "factual_summary": "The upstream response included a current reading.",
            "status": "UNCONFIRMED",
            "verification_status": "VERIFIED",
        }],
        "data_gaps": [], "sources": [],
    })
    parsed = parse_spark_markdown(nonempty, "2026-09-01", scan_nonce="N2")
    item = parsed["global_context"][0]
    assert item["verification_status"] == "UNVERIFIED"
    assert "source_url" not in item


def test_captured_response_is_persisted_and_hashed_before_canonical_ingest(tmp_path):
    nonce = "CAPTURE_NONCE_1"
    raw = json.dumps({
        "scan_nonce": nonce,
        "scheduled_events": [], "breaking_events": [], "overnight_context": [],
        "index_specific_events": [],
        "global_context": [{
            "title": "Sourced external observation",
            "factual_summary": "The provider returned one current external observation.",
            "status": "UNCONFIRMED",
        }],
        "data_gaps": [], "sources": [],
    })
    now = datetime(2026, 9, 2, 7, 0, tzinfo=timezone.utc)
    with (
        mock.patch("scripts.citadel_spark_live_runner.ARTIFACTS_DIR", tmp_path / "artifacts"),
        mock.patch("scripts.citadel_spark_live_runner.STATUS_FILE", tmp_path / "status.json"),
        mock.patch("scripts.citadel_spark_live_runner.ingest_payload_http", return_value=(True, 200)) as ingest,
    ):
        code, status = finalize_captured_response(
            raw,
            now_utc=now,
            session_date="2026-09-02",
            scan_nonce=nonce,
            run_id="run_fixture",
        )

    assert code == 0
    raw_path = tmp_path / "artifacts" / "run_fixture" / "raw.json"
    manifest = json.loads((raw_path.parent / "manifest.json").read_text())
    assert json.loads(raw_path.read_text())["raw_response"] == raw
    assert manifest["raw_artifact_sha256"] == __import__("hashlib").sha256(raw_path.read_bytes()).hexdigest()
    assert manifest["item_count"] == 1
    assert status["external_context_id"].startswith("ctx_spark_real_20260902_")
    assert ingest.call_count == 1


# ── 5. Legacy Deduplication Integration Test ──

def test_legacy_history_id_dedup_integration():
    """Integration Test: Legacy old ID + same new event -> exactly ONE merged event in active context."""
    legacy_event = {
        "fact_id": "sched_002_mospi_gdp",  # Legacy format
        "title": "India Q1 GDP Grew at 7.8%",
        "factual_summary": "India Q1 GDP grew at 7.8%",
        "status": "CONFIRMED",
        "source_name": "UNKNOWN",
        "verification_status": "UNVERIFIED"
    }
    new_event = {
        "fact_id": generate_deterministic_fact_id("sched", "India Q1 GDP Grew at 7.8%"),  # New canonical format
        "title": "India Q1 GDP Grew at 7.8%",
        "factual_summary": "India Q1 GDP grew at 7.8% with manufacturing resilience",
        "status": "CONFIRMED",
        "source_name": "UNKNOWN",
        "verification_status": "UNVERIFIED"
    }
    merged, sources = deduplicate_and_merge_session_events([legacy_event], [new_event])
    assert len(merged) == 1, "Legacy ID and new canonical ID for the same title must merge into 1 event"
    assert "manufacturing resilience" in merged[0]["factual_summary"]
    assert merged[0]["fact_id"] == new_event["fact_id"]
