from copy import deepcopy
from datetime import datetime, timedelta

from src.oracle.option_buyer_intelligence import OptionBuyerIntelligenceWorker, black76, implied_volatility
from src.oracle.fast_lane_publisher import wrap_provider_feed


EXPIRY = "2026-08-25"
OBSERVED = "2026-08-19T10:00:00+05:30"
T = (5 * 24 * 60 * 60 + 5.5 * 60 * 60) / (365 * 24 * 60 * 60)


def _leg(security_id, strike, side, forward=100.0, volatility=.20, expiry=EXPIRY):
    mid = black76(forward, strike, T, volatility, 0.0, side)
    assert mid is not None
    return {
        "security_id": str(security_id), "expiry": expiry, "ltp": mid, "iv": volatility * 100,
        "top_bid_price": max(mid - .02, .01), "top_ask_price": mid + .02,
        "top_bid_quantity": 100, "top_ask_quantity": 100,
    }


def _inputs(*, source_age=0.0, ask=1.0, ltp=2.0, forward=100.0):
    rows = []
    for strike in (96, 97, 98, 99, 100, 101, 102, 103, 104):
        volatility = .20 + .001 * abs(strike - forward)
        rows.append({
            "strike": strike, "expiry": EXPIRY,
            "ce": _leg(f"ce-{strike}", strike, "CE", forward, volatility),
            "pe": _leg(f"pe-{strike}", strike, "PE", forward, volatility),
        })
    rows[4]["ce"]["security_id"] = "target-ce"
    rows[4]["ce"]["iv"] = 99.0
    rows[4]["pe"]["security_id"] = "target-pe"
    rows[4]["pe"]["iv"] = 99.0
    argus = {"data": {
        "underlying": {"fetched_at": OBSERVED, "expiry": EXPIRY},
        "futures": {"ltp": forward, "source_age_seconds": source_age, "expiry": EXPIRY, "best_bid_price": forward - .05, "best_ask_price": forward + .05},
        "atm_window": rows, "argus_market_snapshot": {"status": "AVAILABLE"},
    }}
    vob = {"current_itm1_contracts": {
        "CE": {"contract": {"security_id": "target-ce", "strike": 100, "expiry": EXPIRY}, "quote": {"security_id": "target-ce", "bid": max(ask - .2, .01), "ask": ask, "ltp": ltp}},
        "PE": {"contract": {"security_id": "target-pe", "strike": 100, "expiry": EXPIRY}, "quote": {"security_id": "target-pe", "bid": .8, "ask": 1.0, "ltp": 1.0}},
    }}
    return argus, vob


def _attach_coherent_market(argus, *, futures_bid=99.95, futures_ask=100.05):
    depth = {}
    for row in argus["data"]["atm_window"]:
        for side in ("ce", "pe"):
            leg = row[side]
            depth[str(leg["security_id"])] = {
                "fetched_at": OBSERVED, "source_timestamp": OBSERVED,
                "average_price": 12.5,
                "total_buy_quantity": 1_200,
                "total_sell_quantity": 800,
                "last_trade_quantity": 65,
                "last_trade_time": "19/08/2026 10:00:00",
                "five_level_depth": {
                    "buy": [
                        {"price": leg["top_bid_price"], "quantity": leg["top_bid_quantity"], "orders": 2},
                        {"price": leg["top_bid_price"] - .01, "quantity": 300, "orders": 3},
                    ],
                    "sell": [
                        {"price": leg["top_ask_price"], "quantity": leg["top_ask_quantity"], "orders": 1},
                        {"price": leg["top_ask_price"] + .01, "quantity": 100, "orders": 2},
                    ],
                },
            }
    argus["data"]["argus_market_snapshot"] = {
        "status": "AVAILABLE", "fetched_at": OBSERVED,
        "futures": {"expiry": EXPIRY, "fetched_at": OBSERVED, "source_timestamp": OBSERVED,
                    "best_bid_price": futures_bid, "best_ask_price": futures_ask,
                    "ltp": 999.0, "source_age_seconds": 999.0},
        "option_market_depth": depth,
    }


def _prime_sudden_oi_history(worker, argus):
    worker._hydrated = True
    selected = argus["data"]["atm_window"][2:7]
    boundaries = [
        datetime.fromisoformat("2026-08-19T09:45:00+05:30"),
        datetime.fromisoformat("2026-08-19T09:50:00+05:30"),
        datetime.fromisoformat("2026-08-19T09:55:00+05:30"),
        datetime.fromisoformat(OBSERVED),
    ]
    for side in ("ce", "pe"):
        for index, row in enumerate(selected):
            leg = row[side]
            sid = str(leg["security_id"])
            values = [10_000.0, 10_010.0 + index, 10_030.0 + (2 * index)]
            prices = [100.0, 99.0, 98.0]
            if side == "ce" and index == 2:
                values.append(values[-1] - 300.0)
                prices.append(103.0)
            else:
                values.append(values[-1] + 30.0 + index)
                prices.append(97.0)
            for observed_at, oi, ltp in zip(boundaries, values, prices):
                worker.oi_tracker.record(sid, oi, ltp, observed_at)


def test_sudden_oi_uses_prior_only_exact_contract_history_and_factual_squeeze():
    argus, vob = _inputs()
    worker = OptionBuyerIntelligenceWorker()
    _prime_sudden_oi_history(worker, argus)

    sudden = worker.prepare(argus, vob)["sudden_oi"]
    call = sudden["CALL"]

    assert call["status"] == "LIVE"
    assert call["prior_sample_count"] == 2
    assert call["normal_5m_activity"] is not None
    assert call["current_5m_activity"] > call["previous_session_high"]
    assert call["percentile"] == 100.0
    assert call["previous_5m_activity"] is not None
    assert call["current_to_normal_x"] == round(
        call["current_5m_activity"] / call["normal_5m_activity"], 4
    )
    assert len(call["recent_5m_activity"]) == 3
    assert call["recent_5m_activity"][-1]["activity"] == call["current_5m_activity"]
    assert call["new_session_extreme"] is True
    assert call["top_strike"]["security_id"] == "target-ce"
    assert call["top_strike"]["state"] == "SHORT COVERING"
    assert call["top_strike"]["new_5m_high"] is True
    assert call["top_strike"]["squeeze"] is True
    assert {event["event_type"] for event in call["alerts"]} == {
        "SIDE_SESSION_EXTREME", "STRIKE_SESSION_EXTREME", "WRITER_SQUEEZE",
    }


def test_sudden_oi_event_identity_deduplicates_and_contract_rotation_does_not_leak():
    argus, vob = _inputs()
    worker = OptionBuyerIntelligenceWorker()
    _prime_sudden_oi_history(worker, argus)
    first = worker.prepare(argus, vob)["sudden_oi"]
    repeated = worker.prepare(argus, vob)["sudden_oi"]
    assert [event["event_id"] for event in first["alerts"]] == [event["event_id"] for event in repeated["alerts"]]

    rotated = deepcopy(argus)
    for row in rotated["data"]["atm_window"]:
        row["ce"]["security_id"] = f"new-{row['ce']['security_id']}"
        row["pe"]["security_id"] = f"new-{row['pe']['security_id']}"
    after_rotation = worker.prepare(rotated, vob)["sudden_oi"]
    assert after_rotation["CALL"]["status"] == "WARMING"
    assert after_rotation["PUT"]["status"] == "WARMING"
    assert after_rotation["alerts"] == []
    assert after_rotation["CALL"]["previous_session_high"] is None


def test_sudden_oi_missing_boundary_observation_is_unavailable_not_zero():
    argus, vob = _inputs()
    worker = OptionBuyerIntelligenceWorker()
    worker._hydrated = True
    selected = argus["data"]["atm_window"][2:7]
    for row in selected:
        leg = row["ce"]
        worker.oi_tracker.record(str(leg["security_id"]), 10_000.0, 100.0, datetime.fromisoformat("2026-08-19T09:55:00+05:30"))
    call = worker.prepare(argus, vob)["sudden_oi"]["CALL"]
    assert call["status"] == "WARMING"
    assert call["current_5m_activity"] is None
    assert call["percentile"] is None
    assert call["new_session_extreme"] is False


def test_sudden_oi_straddle_activity_rejects_atm_contract_rotation():
    worker = OptionBuyerIntelligenceWorker()
    worker._hydrated = True
    start = datetime.fromisoformat("2026-08-19T09:45:00+05:30")
    worker._record_timed_value(worker._straddle_series, 200.0, start, identity="old-ce:old-pe")
    worker._record_timed_value(
        worker._straddle_series,
        215.0,
        start + timedelta(minutes=5),
        identity="new-ce:new-pe",
    )

    context = worker._timed_change_context(
        worker._straddle_series,
        5,
        start + timedelta(minutes=5),
        require_same_identity=True,
    )

    assert context["change"] is None
    assert context["percentile"] is None


def test_sudden_oi_price_oi_timing_fails_closed_without_canonical_price_event():
    argus, vob = _inputs()
    worker = OptionBuyerIntelligenceWorker()
    _prime_sudden_oi_history(worker, argus)
    observed_at = datetime.fromisoformat(OBSERVED)
    worker._record_timed_value(worker._price_series, 24_000.0, observed_at - timedelta(seconds=2))
    worker._record_timed_value(worker._price_series, 24_100.0, observed_at)

    response = worker.prepare(argus, vob)["sudden_oi"]["price_oi_response"]

    assert response["call_timing"] == "NO CLEAR FOLLOW"
    assert response["put_timing"] == "NO CLEAR FOLLOW"


def test_sudden_oi_same_day_dhan_backfill_is_bounded_ordered_and_rotation_safe(monkeypatch):
    class FakeDhan:
        def get_intraday_candles(self, segment, security_id, **kwargs):
            start = datetime.fromisoformat("2026-08-19T09:15:00+05:30")
            candles = []
            for minute in range(26):
                opened_at = start + timedelta(minutes=minute)
                row = {
                    "time": opened_at.timestamp(),
                    "close": 100.0 + minute / 100.0,
                    "open_interest": None,
                }
                if segment == "NSE_FNO":
                    row["open_interest"] = 10_000.0 + minute * 10.0 + int(str(security_id).split("-")[-1])
                candles.append(row)
            return {"success": True, "candles": candles}

    class FakeMaster:
        def _rows(self, _underlying):
            return [
                {
                    "SM_EXPIRY_DATE": EXPIRY,
                    "UNDERLYING_SYMBOL": "NIFTY",
                    "OPTION_TYPE": side,
                    "STRIKE_PRICE": str(strike),
                    "SECURITY_ID": f"{side.lower()}-{strike}",
                }
                for strike in range(98, 103)
                for side in ("CE", "PE")
            ]

        @staticmethod
        def _text(row, *keys):
            return next((row[key] for key in keys if row.get(key) is not None), None)

    monkeypatch.setattr("src.oracle.option_buyer_intelligence.sleep", lambda _seconds: None)
    worker = OptionBuyerIntelligenceWorker(
        dhan_history_client=FakeDhan(), instrument_master=FakeMaster()
    )
    live_at = datetime.fromisoformat("2026-08-19T09:41:00+05:30")
    worker.oi_tracker.record("ce-100", 99_999.0, 123.0, live_at)
    frames = worker._backfill_same_day_dhan(
        live_at,
        live_at,
        {"underlying": {"expiry": EXPIRY}},
    )
    worker._rebuild_side_activity_history(frames, live_at)

    ce_series = list(worker.oi_tracker._series["ce-100"])
    assert ce_series == sorted(ce_series, key=lambda item: item[0])
    assert ce_series[-1][1] == 99_999.0
    assert worker._hydration_diagnostics["option_securities_fetched"] == 10
    assert worker._hydration_diagnostics["historical_observations_recovered"] > 0
    assert len(worker._session_side_activity["CE"]) >= 3
    assert len(worker._session_side_activity["PE"]) >= 3
    assert all(len(item["security_ids"]) == 5 for item in worker._session_side_activity["CE"].values())


def test_target_iv_excluded_and_ask_not_ltp_drives_fair_comparison():
    argus, vob = _inputs(ask=.5, ltp=999.0)
    output = OptionBuyerIntelligenceWorker().prepare(argus, vob)
    changed = deepcopy(argus)
    changed["data"]["atm_window"][4]["ce"]["iv"] = 250.0
    without_circularity = OptionBuyerIntelligenceWorker().prepare(changed, vob)
    assert output["CE"]["quality"]["valid"] is True
    assert output["CE"]["fair_iv"] < 25.0
    assert output["CE"]["comparison"] == "BELOW_FAIR"
    assert output["CE"]["ask"] == .5
    assert without_circularity["CE"]["fair_iv"] == output["CE"]["fair_iv"]
    assert output["CE"]["quality"]["fair_iv_method"] == "ARBITRAGE_GATED_TOTAL_VARIANCE_INTERPOLATION_EXCLUDING_TARGET"


def test_invalid_quotes_and_wrong_expiry_are_excluded_but_same_expiry_surface_survives():
    argus, vob = _inputs()
    argus["data"]["atm_window"][0]["pe"]["top_bid_quantity"] = 0
    argus["data"]["atm_window"][1]["pe"]["top_bid_price"] = 10
    argus["data"]["atm_window"][1]["pe"]["top_ask_price"] = 9
    argus["data"]["atm_window"][8]["ce"]["expiry"] = "2026-09-01"
    output = OptionBuyerIntelligenceWorker().prepare(argus, vob)
    assert output["CE"]["quality"]["valid"] is True
    assert output["CE"]["quality"]["surface_point_count"] == 5


def test_forward_parity_quote_interval_gate_fails_closed():
    argus, vob = _inputs()
    argus["data"]["futures"]["ltp"] = 101.0
    argus["data"]["futures"]["best_bid_price"] = 100.95
    argus["data"]["futures"]["best_ask_price"] = 101.05
    output = OptionBuyerIntelligenceWorker().prepare(argus, vob)
    assert output["CE"]["fair_price"] is None
    assert output["CE"]["quality"]["forward_gate_rule"] == "QUOTE_INTERVAL_OVERLAP"
    assert output["CE"]["quality"]["forward_discrepancy"] > output["CE"]["quality"]["forward_gate_tolerance"]


def test_arbitrage_invalid_surface_fails_to_dash():
    argus, vob = _inputs()
    bad = argus["data"]["atm_window"][7]["ce"]
    bad["top_bid_price"], bad["top_ask_price"] = 5.0, 5.1
    output = OptionBuyerIntelligenceWorker().prepare(argus, vob)
    assert output["CE"]["fair_price"] is None
    assert output["CE"]["quality"]["valid"] is False


def test_black76_and_iv_numerical_sanity():
    value = black76(100, 100, .5, .2, .01, "CE")
    assert value is not None
    recovered = implied_volatility(value, 100, 100, .5, .01, "CE")
    assert recovered is not None and abs(recovered - .2) < 1e-10


def test_exact_time_repricing_time_value_time_lost_and_holding():
    argus, vob = _inputs(ask=.9, ltp=2.0)
    worker = OptionBuyerIntelligenceWorker()
    first = worker.prepare(argus, vob)["CE"]
    later_argus = deepcopy(argus)
    later_argus["data"]["underlying"]["fetched_at"] = "2026-08-19T15:00:00+05:30"
    later_vob = deepcopy(vob)
    later_vob["current_itm1_contracts"]["CE"]["quote"]["ltp"] = 3.0
    later = worker.prepare(later_argus, later_vob)["CE"]
    assert first["time_loss_expected"] is None and first["time_lost_today"] is None
    assert first["time_value_left"] == 2.0
    assert later["actual_change"] == 1.0
    assert later["time_loss_expected"] is not None and later["time_loss_expected"] < 0.0
    assert later["time_lost_today"] == later["time_loss_expected"]
    assert later["premium_holding"] == round(later["actual_change"] - later["time_loss_expected"], 2)


def test_straddle_roll_is_continuity_safe_and_driver_is_raw_contribution():
    argus, vob = _inputs()
    worker = OptionBuyerIntelligenceWorker()
    first = worker.prepare(argus, vob)["straddle"]
    rolled, _ = _inputs(forward=101.0)
    rolled["data"]["underlying"]["fetched_at"] = "2026-08-19T10:01:00+05:30"
    second = worker.prepare(rolled, vob)["straddle"]
    assert first["premium_today"] == second["premium_today"] == 0.0
    assert second["continuity_state"] == "STRIKE_SWITCH_ADJUSTED"
    assert second["premium_driver"] == "MIXED"


def test_contract_and_unavailable_microstructure_are_preserved():
    argus, vob = _inputs()
    output = OptionBuyerIntelligenceWorker().prepare(argus, vob)
    assert output["schema_version"] == 1
    assert output["CE"]["spread"] == .2
    assert output["CE"]["fair_advantage"] is not None
    assert output["CE"]["flow"]["buying_volume"] is None
    assert "most_traded_price" not in output["CE"]["book"]
    assert output["straddle"]["vwap"] is None
    assert output["fit"]["call_evidence"] is None
    assert output["fit"]["state"] == "NO_CLEAN_FIT"
    assert "market_preference" not in output


def test_direct_dhan_market_pressure_and_visible_five_level_book_are_published():
    argus, vob = _inputs()
    _attach_coherent_market(argus)
    output = OptionBuyerIntelligenceWorker().prepare(argus, vob)["CE"]
    pressure, book = output["market_pressure"], output["book"]
    assert pressure == {
        "total_buy_quantity": 1200,
        "total_sell_quantity": 800,
        "book_buy_share_pct": 66.67,
        "book_sell_share_pct": 33.33,
        "last_trade_quantity": 65,
        "last_trade_time": "19/08/2026 10:00:00",
        "average_trade_price": 12.5,
        "source_timestamp": OBSERVED,
        "provenance": "DHAN_V2_MARKETFEED_QUOTE",
    }
    assert book["best_bid"]["quantity"] == 100
    assert book["biggest_buy_level"]["quantity"] == 300
    assert book["best_ask"]["orders"] == 1
    assert book["five_level_buy_quantity"] == 400
    assert book["five_level_sell_quantity"] == 200


def test_straddle_time_loss_actual_change_and_holding_use_existing_option_model():
    argus, vob = _inputs()
    worker = OptionBuyerIntelligenceWorker()
    first = worker.prepare(argus, vob)["straddle"]
    later = deepcopy(argus)
    later["data"]["underlying"]["fetched_at"] = "2026-08-19T10:01:00+05:30"
    later["data"]["atm_window"][4]["ce"]["ltp"] += 1.0
    later["data"]["atm_window"][4]["pe"]["ltp"] += 2.0
    second = worker.prepare(later, vob)["straddle"]
    assert first["time_loss_expected"] is None
    assert second["time_loss_expected"] is not None
    assert second["actual_change"] == 3.0
    assert second["premium_holding"] == round(second["actual_change"] - second["time_loss_expected"], 2)


def test_same_batch_book_midpoint_ignores_stale_futures_trade_ltp():
    argus, vob = _inputs()
    _attach_coherent_market(argus)
    output = OptionBuyerIntelligenceWorker().prepare(argus, vob)
    assert output["CE"]["quality"]["valid"] is True
    assert output["CE"]["quality"]["forward"] == 100.0
    assert output["CE"]["quality"]["quote_age_seconds"] == 0.0


def test_partial_full_quote_batch_fails_closed_without_mixing_chain_quotes():
    argus, vob = _inputs()
    _attach_coherent_market(argus)
    depth = argus["data"]["argus_market_snapshot"]["option_market_depth"]
    argus["data"]["argus_market_snapshot"]["option_market_depth"] = {
        key: value for key, value in depth.items() if key in {"target-ce", "target-pe"}
    }
    output = OptionBuyerIntelligenceWorker().prepare(argus, vob)
    assert output["CE"]["quality"]["valid"] is False


def test_live_chain_remains_publishable_when_futures_and_option_expiries_differ():
    argus, vob = _inputs()
    argus["data"]["futures"]["expiry"] = "2026-09-29"

    output = OptionBuyerIntelligenceWorker().prepare(argus, vob)
    wrapped = wrap_provider_feed("option_buyer_intelligence", output, None)

    assert output["CE"]["quality"]["valid"] is True
    assert output["PE"]["quality"]["valid"] is True
    assert output["option_intelligence"]["status"] == "LIVE"
    assert output["status"] == "LIVE"
    assert wrapped["ok"] is True
    assert wrapped["data"]["option_intelligence"]["status"] == "LIVE"


def test_repo_skew_momentum_and_sign_contradiction():
    from src.oracle.option_intelligence import OptionIntelligenceEngine
    from datetime import datetime, timezone
    
    engine = OptionIntelligenceEngine(lot_size=1, rate=0.07)
    
    # Record a steepening put skew sequence
    for i, s25 in enumerate([1.0, 1.5, 2.2, 3.0, 4.2, 5.5]):
        dt = datetime(2026, 8, 24, 10, 0, i * 3, tzinfo=timezone.utc)
        engine.record_iv_skew(
            atm_iv=10.0,
            skew_25d=s25,
            observed_at=dt,
            c25_iv=10.0,
            p25_iv=10.0 + s25,
            c10_iv=10.0,
            p10_iv=10.0 + s25 * 0.8,
            skew_10d=s25 * 0.8,
        )
    
    repo_res = engine.calculate_repo_skew_momentum()
    assert repo_res["repo_skew_velocity"] is not None
    assert repo_res["repo_skew_velocity"] > 0.0
    assert repo_res["repo_wing_confirms"] is True
    assert repo_res["repo_regime"] == "steepening"


def test_multi_wing_velocity_and_cadence_metadata():
    from src.oracle.option_intelligence import OptionIntelligenceEngine
    from datetime import datetime, timezone
    
    engine = OptionIntelligenceEngine(lot_size=1, rate=0.07)
    t0 = datetime(2026, 8, 24, 10, 0, 0, tzinfo=timezone.utc)
    
    # Push samples over 15 minutes (900 seconds)
    for step in range(0, 950, 5):
        dt = datetime.fromtimestamp(t0.timestamp() + step, tz=timezone.utc)
        engine.record_iv_skew(
            atm_iv=10.0 + step * 0.002,
            skew_25d=-1.5 + step * 0.001,
            observed_at=dt,
            c25_iv=11.0,
            p25_iv=9.5 + step * 0.001,
            c10_iv=10.5,
            p10_iv=10.0 + step * 0.001,
            skew_10d=-0.5 + step * 0.001,
        )
        
    vels = engine.calculate_iv_skew_velocities(
        current_atm_iv=11.9,
        current_skew=-0.55,
        observed_at=datetime.fromtimestamp(t0.timestamp() + 950, tz=timezone.utc),
        c25_iv=11.0,
        p25_iv=10.45,
        c10_iv=10.5,
        p10_iv=10.95,
        skew_10d=0.45,
    )
    
    assert vels["history_depth_seconds"] >= 900.0
    assert vels["iv_5m_delta"] is not None
    assert vels["iv_15m_delta"] is not None
    assert vels["repo_skew_velocity"] is not None
