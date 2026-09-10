from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from src.vob.episodes import episode_from_ose, select_primary_ose_vob
from src.vob.reversal import VobReversalEngine
from src.vob.shadow_ledger import MatchedShadowLedger, VARIANTS


def ose(*, security_id="101", pe_security_id="102", revision="ose-1", state="TESTED", broken=False, direction="CALL"):
    zone = {
        "zone_id": "NIFTY_CE_5M_DEMAND_20260814T100000",
        "zone_low": 100.0,
        "zone_high": 104.0,
        "status": state,
        "symbol": "NIFTY 25000 CE",
        "security_id": security_id,
        "source_candle_timestamp": "2026-08-14T10:05:00+05:30",
    }
    structure = {
        "demand": None if broken else zone,
        "supply": None,
        "recently_broken": [dict(zone, status="BROKEN")] if broken else [],
    }
    return {
        "calculation_revision": revision,
        "source_timestamp": "2026-08-14T10:05:01+05:30",
        "duel": {"state": f"CLEAR {direction} ADVANTAGE"},
        "contracts": {
            "CE": {
                "contract": {
                    "security_id": security_id,
                    "trading_symbol": f"NIFTY-CE-{security_id}",
                    "expiry": "2026-08-20",
                    "strike": 25000,
                    "option_type": "CE",
                    "lot_size": 75,
                    "instrument_source": "DHAN_INSTRUMENT_MASTER",
                },
                "structures": {"5m": structure, "3m": structure},
                "quality": {"freshness": "FRESH"},
            },
            "PE": {
                "contract": {
                    "security_id": pe_security_id,
                    "trading_symbol": f"NIFTY-PE-{pe_security_id}",
                    "expiry": "2026-08-20",
                    "strike": 25200,
                    "option_type": "PE",
                    "lot_size": 75,
                    "instrument_source": "DHAN_INSTRUMENT_MASTER",
                },
                "structures": {
                    "5m": {
                        "demand": dict(
                            zone,
                            zone_id="NIFTY_PE_5M_DEMAND_20260814T100000",
                            zone_low=48.0,
                            zone_high=52.0,
                            security_id=pe_security_id,
                            symbol="NIFTY 25200 PE",
                        )
                    }
                },
                "quality": {"freshness": "FRESH"},
            },
        },
    }


def flow(revision: int, *, reversal="PRESSURE_FLIP", option=True, adverse=False):
    return {
        "revision": revision,
        "snapshot_id": f"flow-{revision}",
        "generated_at": f"2026-08-14T10:05:0{revision}+05:30",
        "data_quality": "GOOD",
        "latency_timestamps": {"t0_packet_receive_ns": revision},
        "family_values": {
            "RESPONSE_QUALITY": {
                "state": "SELLERS_ABSORBED" if not adverse else "CLEAN_BEAR",
                "failed_aggression": 0.8 if not adverse else 0.0,
                "status": "AVAILABLE",
            },
            "BOOK_PRESSURE": {
                "book_pressure": -0.4 if adverse else 0.4,
                "status": "AVAILABLE",
            },
            "OPTION_CONFIRMATION": {
                "ce_known_buy": 20 if option else 0,
                "ce_known_sell": 5 if option else 0,
                "pe_known_buy": 4 if option else 0,
                "pe_known_sell": 15 if option else 0,
                "status": "AVAILABLE",
            },
            "REVERSAL": {"state": reversal},
        },
    }


def argus(
    direction: str,
    revision="argus-1",
    *,
    ce_price=106.0,
    pe_price=50.0,
    ce_security_id="101",
    pe_security_id="102",
    atm_strike=25100,
    ce_strike=25000,
    pe_strike=25200,
):
    return {
        "data": {
            "underlying": {
                "ltp": atm_strike + 16,
                "atm_strike": atm_strike,
                "expiry": "2026-08-20",
                "fetched_at": "2026-08-14T10:05:04+05:30",
            },
            "atm_window": [
                {
                    "strike": ce_strike,
                    "ce": {
                        "security_id": ce_security_id, "ltp": ce_price,
                        "top_bid_price": ce_price - 0.2, "top_ask_price": ce_price + 0.2,
                    },
                },
                {
                    "strike": pe_strike,
                    "pe": {
                        "security_id": pe_security_id, "ltp": pe_price,
                        "top_bid_price": pe_price - 0.2, "top_ask_price": pe_price + 0.2,
                    },
                },
            ],
            "tactical_edge": {
                "direction": direction,
                "argus_prime": {"snapshot_id": revision, "raw_direction": direction},
            },
        }
    }


def test_episode_id_is_deterministic_and_references_existing_zone():
    first = episode_from_ose(ose())
    second = episode_from_ose(ose(revision="ose-2"))
    assert first is not None and second is not None
    assert first.episode_id == second.episode_id
    assert (first.zone_bottom, first.zone_top) == (100.0, 104.0)
    assert first.primary_reason == "NEAREST_SUPPORT"
    assert first.source_engine == "OPTIONS_STRUCTURE_ENGINE_V1"
    assert first.session_date == "2026-08-14"
    assert first.expiry_day is False


def test_episode_and_matched_variants_carry_explicit_expiry_bucket():
    source = ose()
    source["contracts"]["CE"]["contract"]["expiry"] = "2026-08-14"
    source["contracts"]["PE"]["contract"]["expiry"] = "2026-08-14"
    episode = episode_from_ose(source)
    assert episode is not None
    assert episode.expiry_day is True

    ledger = MatchedShadowLedger()
    ledger.begin_episode(episode, recorded_at=episode.created_at)
    current = ledger.current(episode.episode_id)
    assert {row["expiry_bucket"] for row in current.values()} == {"EXPIRY"}
    assert {row["expiry_day"] for row in current.values()} == {True}


def test_primary_adapter_does_not_calculate_or_mutate_geometry():
    source = ose()
    frozen = deepcopy(source)
    selected = select_primary_ose_vob(source)
    assert selected["zone"]["zone_low"] == 100.0
    assert source == frozen


def test_frozen_contract_does_not_roll_during_active_reversal():
    engine = VobReversalEngine()
    engine.ingest_ose(ose(security_id="101"))
    engine.ingest_flow(flow(1))
    engine.ingest_flow(flow(2, reversal="REVERSAL_FORMING"))
    assert engine.projection()["reversal_state"] == "REVERSAL_BUILDING"
    engine.ingest_ose(ose(security_id="202", revision="ose-2"))
    assert engine.projection()["episode"]["contract_identity"]["security_id"] == "101"


def test_option_price_projection_joins_exact_quote_and_vob_without_new_thresholds():
    engine = VobReversalEngine()
    engine.ingest_ose(ose())
    engine.ingest_argus(argus("CALL", ce_price=106.0, pe_price=50.0))
    projection = engine.projection()["option_contracts"]

    call = projection["CE"]
    assert call["contract"]["security_id"] == "101"
    assert call["quote"] == {
        "security_id": "101",
        "strike": 25000.0,
        "option_type": "CE",
        "ltp": 106.0,
        "bid": 105.8,
        "ask": 106.2,
        "source": "ARGUS_DHAN_OPTION_CHAIN",
        "timestamp": "2026-08-14T10:05:04+05:30",
        "freshness": "FRESH",
    }
    assert call["vob"]["zone_bottom"] == 100.0
    assert call["vob"]["zone_top"] == 104.0
    assert call["distance"] == {
        "distance_to_zone_points": 2.0,
        "distance_to_zone_pct": 1.886792,
        "inside_zone": False,
        "nearest_zone_boundary": 104.0,
        "relation": "ABOVE",
    }

    put = projection["PE"]
    assert put["contract"]["security_id"] == "102"
    assert put["quote"]["ltp"] == 50.0
    assert put["distance"]["inside_zone"] is True
    assert put["distance"]["distance_to_zone_points"] == 0.0

    engine.ingest_argus(argus("CALL", revision="argus-2", ce_price=104.0))
    touching = engine.projection()["option_contracts"]["CE"]["distance"]
    assert touching["inside_zone"] is True
    assert touching["relation"] == "TOUCHING"


def test_option_price_projection_keeps_frozen_episode_contract_when_ose_rolls():
    engine = VobReversalEngine()
    engine.ingest_ose(ose(security_id="101"))
    engine.ingest_flow(flow(1))
    engine.ingest_flow(flow(2, reversal="REVERSAL_FORMING"))
    engine.ingest_argus(argus("CALL"))
    engine.ingest_ose(ose(security_id="202", revision="ose-2"))

    call = engine.projection()["option_contracts"]["CE"]
    assert call["contract_status"] == "FROZEN_EPISODE"
    assert call["contract"]["security_id"] == "101"
    assert call["quote"]["security_id"] == "101"


def test_active_call_episode_freezes_both_contract_identities_across_atm_roll():
    engine = VobReversalEngine()
    engine.ingest_ose(ose(security_id="101", pe_security_id="102", direction="CALL"))
    engine.ingest_argus(argus("CALL", ce_security_id="101", pe_security_id="102"))

    engine.ingest_ose(ose(security_id="201", pe_security_id="202", revision="ose-2", direction="CALL"))
    projection = engine.projection()

    assert projection["episode"]["contract_identity"]["security_id"] == "101"
    assert projection["contract_pair_status"] == "FROZEN_EPISODE"
    assert projection["option_contracts"]["CE"]["contract"]["security_id"] == "101"
    assert projection["option_contracts"]["PE"]["contract"]["security_id"] == "102"
    assert projection["option_contracts"]["CE"]["contract_status"] == "FROZEN_EPISODE"
    assert projection["option_contracts"]["PE"]["contract_status"] == "FROZEN_EPISODE"


def test_active_put_episode_freezes_both_contract_identities_across_atm_roll():
    engine = VobReversalEngine()
    engine.ingest_ose(ose(security_id="101", pe_security_id="102", direction="PUT"))
    engine.ingest_argus(argus("PUT", ce_security_id="101", pe_security_id="102"))

    engine.ingest_ose(ose(security_id="201", pe_security_id="202", revision="ose-2", direction="PUT"))
    projection = engine.projection()

    assert projection["episode"]["direction"] == "PUT"
    assert projection["episode"]["contract_identity"]["security_id"] == "102"
    assert projection["option_contracts"]["CE"]["contract"]["security_id"] == "101"
    assert projection["option_contracts"]["PE"]["contract"]["security_id"] == "102"
    assert projection["option_contracts"]["CE"]["contract_status"] == "FROZEN_EPISODE"
    assert projection["option_contracts"]["PE"]["contract_status"] == "FROZEN_EPISODE"


def test_closed_episode_resumes_canonical_current_itm1_pair():
    engine = VobReversalEngine()
    engine.ingest_ose(ose(security_id="101", pe_security_id="102"))
    engine.ingest_argus(argus("CALL", ce_security_id="301", pe_security_id="302"))
    closed = ose(security_id="201", pe_security_id="202", revision="ose-2", broken=True)
    engine.ingest_ose(closed)
    projection = engine.projection()

    assert projection["reversal_state"] == "REVERSAL_FAILED"
    assert projection["contract_pair_status"] == "CURRENT_ITM1"
    assert projection["option_contracts"]["CE"]["contract"]["security_id"] == "301"
    assert projection["option_contracts"]["PE"]["contract"]["security_id"] == "302"
    assert projection["option_contracts"]["CE"]["contract_status"] == "CURRENT_ITM1"
    assert projection["option_contracts"]["PE"]["contract_status"] == "CURRENT_ITM1"


def test_canonical_itm1_pair_rolls_together_but_episode_pair_stays_frozen():
    engine = VobReversalEngine()
    engine.ingest_ose(ose(security_id="101", pe_security_id="102", direction="CALL"))
    engine.ingest_argus(argus(
        "CALL", atm_strike=25000, ce_strike=24950, pe_strike=25050,
        ce_security_id="ce-24950", pe_security_id="pe-25050",
    ))
    before = engine.projection()
    assert before["canonical_market"] == {
        "reference_price": 25016.0,
        "strike_interval": 50.0,
        "atm_strike": 25000.0,
        "source": "ARGUS_OPTION_CHAIN_RESOLVER",
        "source_timestamp": "2026-08-14T10:05:04+05:30",
    }
    assert before["current_itm1_contracts"]["CE"]["contract"]["strike"] == 24950.0
    assert before["current_itm1_contracts"]["PE"]["contract"]["strike"] == 25050.0

    engine.ingest_argus(argus(
        "CALL", revision="argus-2", atm_strike=25050,
        ce_strike=25000, pe_strike=25100,
        ce_security_id="ce-25000", pe_security_id="pe-25100",
    ))
    after = engine.projection()
    assert after["current_itm1_contracts"]["CE"]["contract"]["security_id"] == "ce-25000"
    assert after["current_itm1_contracts"]["PE"]["contract"]["security_id"] == "pe-25100"
    assert after["option_contracts"]["CE"]["contract"]["security_id"] == "101"
    assert after["option_contracts"]["PE"]["contract"]["security_id"] == "102"


def test_idle_pair_rolls_to_new_canonical_itm1_after_episode_closes():
    engine = VobReversalEngine()
    engine.ingest_ose(ose(security_id="101", pe_security_id="102"))
    engine.ingest_argus(argus(
        "CALL", atm_strike=25000, ce_strike=24950, pe_strike=25050,
        ce_security_id="ce-old", pe_security_id="pe-old",
    ))
    engine.ingest_argus(argus(
        "CALL", revision="argus-2", atm_strike=25050,
        ce_strike=25000, pe_strike=25100,
        ce_security_id="ce-new", pe_security_id="pe-new",
    ))
    engine.ingest_ose(ose(security_id="201", pe_security_id="202", revision="ose-2", broken=True))
    projection = engine.projection()
    assert projection["option_contracts"]["CE"]["contract"]["security_id"] == "ce-new"
    assert projection["option_contracts"]["PE"]["contract"]["security_id"] == "pe-new"
    assert projection["option_contracts"]["CE"]["vob"] == {}
    assert projection["option_contracts"]["PE"]["vob"] == {}


def test_frozen_quotes_and_vob_distances_use_the_same_pair_ids():
    engine = VobReversalEngine()
    engine.ingest_ose(ose(security_id="101", pe_security_id="102"))
    engine.ingest_ose(ose(security_id="201", pe_security_id="202", revision="ose-2"))
    mixed_window = argus("CALL", ce_security_id="101", pe_security_id="102", ce_price=103.0, pe_price=50.0)
    mixed_window["data"]["atm_window"].append({
        "strike": 25100,
        "ce": {"security_id": "201", "ltp": 999.0, "top_bid_price": 998.0, "top_ask_price": 1000.0},
        "pe": {"security_id": "202", "ltp": 888.0, "top_bid_price": 887.0, "top_ask_price": 889.0},
    })
    engine.ingest_argus(mixed_window)
    projection = engine.projection()["option_contracts"]

    for side, security_id in (("CE", "101"), ("PE", "102")):
        assert projection[side]["contract"]["security_id"] == security_id
        assert projection[side]["quote"]["security_id"] == security_id
        assert projection[side]["distance"]["relation"] in {"INSIDE", "TOUCHING", "ABOVE", "BELOW"}


def test_parallel_evidence_accepts_argus_before_or_after_option_rotation():
    before = VobReversalEngine()
    before.ingest_ose(ose())
    before.ingest_argus(argus("CALL"))
    before.ingest_flow(flow(1))
    before.ingest_flow(flow(2, reversal="REVERSAL_FORMING"))
    assert before.projection()["reversal_state"] == "REVERSAL_READY"

    after = VobReversalEngine()
    after.ingest_ose(ose())
    after.ingest_flow(flow(1))
    after.ingest_flow(flow(2, reversal="REVERSAL_FORMING"))
    assert after.projection()["reversal_state"] == "REVERSAL_BUILDING"
    after.ingest_argus(argus("CALL"))
    assert after.projection()["reversal_state"] == "REVERSAL_READY"


def test_unknown_evidence_remains_unknown():
    engine = VobReversalEngine()
    engine.ingest_ose(ose())
    engine.ingest_flow({"revision": 1, "family_values": {}})
    result = engine.projection()
    assert result["evidence"]["premium_velocity"]["state"] == "UNKNOWN"
    assert result["evidence"]["target_option_wakeup"]["state"] == "UNKNOWN"
    assert "premium_velocity" in result["unknown_fields"]


def test_one_tick_support_cannot_create_building_state():
    engine = VobReversalEngine()
    engine.ingest_ose(ose())
    engine.ingest_flow(flow(1, reversal="PRESSURE_FLIP"))
    assert engine.projection()["reversal_state"] == "WATCHING"


def test_vob_invalidation_fails_reversal():
    engine = VobReversalEngine()
    engine.ingest_ose(ose())
    engine.ingest_flow(flow(1))
    engine.ingest_flow(flow(2, reversal="REVERSAL_FORMING"))
    engine.ingest_ose(ose(revision="ose-2", broken=True))
    assert engine.projection()["reversal_state"] == "REVERSAL_FAILED"


def test_projection_has_no_competing_entry_stop_target_calculation():
    engine = VobReversalEngine()
    engine.ingest_ose(ose())
    result = engine.projection()
    assert result["entry_ref"] is None
    assert result["sl_ref"] is None
    assert result["target_ref"] is None
    assert result["authority"]["entry_sl_target_one_use_trail"] == "PULLBACK_MASTER"


def test_matched_variants_share_episode_and_preserve_ask_bid_truth():
    episode = episode_from_ose(ose())
    ledger = MatchedShadowLedger()
    ledger.begin_episode(episode, recorded_at=episode.created_at)
    current = ledger.current(episode.episode_id)
    assert set(current) == set(VARIANTS)
    assert {row["contract_security_id"] for row in current.values()} == {"101"}
    ledger.record_entry(
        episode, "EARLY_REVERSAL", entry_time="2026-08-14T10:06:00+05:30",
        entry_ask=10.0, initial_sl=8.0, target=None,
    )
    ledger.mark(
        episode, "EARLY_REVERSAL", recorded_at="2026-08-14T10:07:00+05:30",
        current_bid=12.0,
    )
    marked = ledger.current(episode.episode_id)["EARLY_REVERSAL"]
    assert marked["entry_ask"] == 10.0
    assert marked["current_bid"] == 12.0
    assert marked["r"] == 1.0


def test_projection_is_copy_safe_and_revisioned():
    engine = VobReversalEngine()
    engine.ingest_ose(ose())
    first = engine.projection()
    revision = first["revision"]
    first["episode"]["contract_identity"]["security_id"] = "MUTATED"
    assert engine.projection()["episode"]["contract_identity"]["security_id"] == "101"
    engine.ingest_flow(flow(1))
    assert engine.projection()["revision"] > revision


def test_fastapi_serving_path_only_publishes_prepared_reversal_state():
    source = Path("app/main.py").read_text(encoding="utf-8")
    endpoint = source.split('@app.get("/v1/oracle/fast-lane")', 1)[1].split(
        '@app.get("/v1/oracle/fast-lane/stream")', 1
    )[0]
    assert "vob_reversal_engine" not in endpoint
    assert "oracle_fast_lane.response()" in endpoint
