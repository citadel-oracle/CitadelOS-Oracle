import importlib
import time
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

from src.api.argus_api import ArgusAPI, ArgusAPIError
from src.argus.tactical_edge import ArgusTacticalEdgeEngine
from src.argus.tactical_store import ArgusTacticalStore
from src.argus.baseline_store import ArgusBaselineStore
from src.argus.option_chain_engine import OptionChainEngine
from src.scanner.watchlist import WATCHLIST
from tests.test_argus_intraday_oi import MutableNow, chain_response


IST = ZoneInfo("Asia/Kolkata")
pytestmark = pytest.mark.integration
SUPPORTED_ARGUS_SYMBOLS = {
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "SENSEX",
}


class MutableClock:
    def __init__(self, value=0.0):
        self.value = value

    def __call__(self):
        return self.value


class FakeDhan:
    def __init__(self, response=None):
        self.response = response or chain_response()
        self.expiry_calls = 0
        self.chain_calls = 0

    def get_option_expiries(self, **kwargs):
        self.expiry_calls += 1
        return {"status": "success", "data": ["2026-07-14", "2026-07-21"]}

    def get_option_chain(self, **kwargs):
        self.chain_calls += 1
        return self.response


def make_api(path, now, clock, dhan=None):
    provider = dhan or FakeDhan()
    store = ArgusBaselineStore(path=path, now_provider=now)
    engine = OptionChainEngine(
        dhan=provider,
        baseline_store=store,
        now_provider=now,
    )
    return (
        ArgusAPI(
            engine=engine,
            cache_ttl_seconds=3,
            clock=clock,
            now_provider=now,
        ),
        provider,
    )


def test_api_validation_and_dhan_failure_are_structured():
    with TemporaryDirectory() as directory:
        now = MutableNow(datetime(2026, 7, 10, 10, 0, tzinfo=IST))
        clock = MutableClock()
        api, dhan = make_api(Path(directory) / "baseline.json", now, clock)

        try:
            api.get_oi("INVALID")
        except ArgusAPIError as error:
            assert error.status_code == 404
            assert error.detail["error"]["code"] == "UNSUPPORTED_SYMBOL"
        else:
            raise AssertionError("Invalid symbol should fail")

        try:
            api.get_oi("NIFTY", "14-07-2026")
        except ArgusAPIError as error:
            assert error.status_code == 422
            assert error.detail["error"]["code"] == "INVALID_EXPIRY_FORMAT"
        else:
            raise AssertionError("Malformed expiry should fail")

        try:
            api.get_oi("NIFTY", "2026-07-28")
        except ArgusAPIError as error:
            assert error.status_code == 422
            assert error.detail["error"]["code"] == "INVALID_EXPIRY"
        else:
            raise AssertionError("Inactive expiry should fail")

        failing, _ = make_api(
            Path(directory) / "failure.json",
            now,
            clock,
            dhan=FakeDhan(response={"error": "read-only provider unavailable"}),
        )
        try:
            failing.get_oi("NIFTY")
        except ArgusAPIError as error:
            assert error.status_code == 502
            assert error.detail["error"]["code"] == "DHAN_UNAVAILABLE"
        else:
            raise AssertionError("Dhan failure should not return fake data")

        assert dhan.chain_calls == 0


def test_all_supported_symbols_use_the_read_only_option_chain_contract():
    assert set(WATCHLIST) == SUPPORTED_ARGUS_SYMBOLS

    with TemporaryDirectory() as directory:
        now = MutableNow(datetime(2026, 7, 10, 10, 0, tzinfo=IST))
        api, dhan = make_api(
            Path(directory) / "baseline.json",
            now,
            MutableClock(),
        )

        for symbol in sorted(SUPPORTED_ARGUS_SYMBOLS):
            payload = api.get_oi(symbol)
            assert payload["data"]["underlying"]["symbol"] == symbol

        assert dhan.expiry_calls == len(SUPPORTED_ARGUS_SYMBOLS)
        assert dhan.chain_calls == len(SUPPORTED_ARGUS_SYMBOLS)


def test_api_cache_respects_ttl_and_closed_market_stays_stale():
    with TemporaryDirectory() as directory:
        now = MutableNow(datetime(2026, 7, 10, 10, 0, tzinfo=IST))
        clock = MutableClock()
        api, dhan = make_api(Path(directory) / "baseline.json", now, clock)

        first = api.get_oi("NIFTY")
        second = api.get_oi("NIFTY")
        assert first["cache"]["hit"] is False
        assert second["cache"]["hit"] is True
        assert dhan.expiry_calls == 1
        assert dhan.chain_calls == 1

        clock.value = 3.1
        api.get_oi("NIFTY")
        assert dhan.expiry_calls == 2
        assert dhan.chain_calls == 2

        now.value = datetime(2026, 7, 10, 16, 0, tzinfo=IST)
        clock.value = 100
        stale = api.get_oi("NIFTY")
        assert stale["status"] == "stale"
        assert stale["freshness"] == "stale"
        assert dhan.expiry_calls == 2
        assert dhan.chain_calls == 2


def test_finished_same_day_expiry_rolls_current_cache_to_next_dhan_expiry():
    """A closed-market LAST_GOOD must not retain the finished weekly contract."""

    class RolloverDhan(FakeDhan):
        def get_option_expiries(self, **kwargs):
            self.expiry_calls += 1
            return {"status": "success", "data": ["2026-07-14", "2026-07-21"]}

    with TemporaryDirectory() as directory:
        now = MutableNow(datetime(2026, 7, 14, 15, 20, tzinfo=IST))
        clock = MutableClock()
        api, dhan = make_api(
            Path(directory) / "baseline.json", now, clock, dhan=RolloverDhan()
        )

        before_close = api.get_oi("NIFTY")
        assert before_close["data"]["underlying"]["expiry"] == "2026-07-14"

        now.value = datetime(2026, 7, 14, 15, 31, tzinfo=IST)
        clock.value = 1.0
        after_close = api.get_oi("NIFTY")

        assert after_close["cache"]["hit"] is False
        assert after_close["data"]["underlying"]["expiry"] == "2026-07-21"
        assert dhan.expiry_calls == 2
        assert dhan.chain_calls == 2

        # Cache-only readers use the rolled contract while it is available.
        latest = api.projection("NIFTY")
        assert latest["data"]["underlying"]["expiry"] == "2026-07-21"

        # They must fail closed rather than resurrect a finished LAST_GOOD.
        api._cache[("NIFTY", "current")] = {
            "data": before_close["data"], "cached_at": clock.value + 1.0,
        }
        assert api.projection("NIFTY") is None


def test_projection_freshness_is_separate_from_three_second_fetch_dedup():
    with TemporaryDirectory() as directory:
        started = datetime(2026, 7, 10, 10, 0, tzinfo=IST)
        now = MutableNow(started)
        clock = MutableClock()
        api, dhan = make_api(Path(directory) / "baseline.json", now, clock)

        api.get_oi("NIFTY")
        assert api.cache_ttl_seconds == 3
        assert api.projection_freshness_seconds == 20

        for age in (3.1, 12.0, 19.9):
            clock.value = age
            now.value = started + timedelta(seconds=age)
            projection = api.projection("NIFTY")
            assert projection["status"] == "available"
            assert projection["reason"] is None
            assert projection["cache"]["projection_freshness_seconds"] == 20

        # Reading a projection never performs a provider refresh.
        assert dhan.chain_calls == 1


def test_single_cache_producer_refreshes_independently_of_v2_rebuilds():
    with TemporaryDirectory() as directory:
        started = datetime(2026, 7, 10, 10, 0, tzinfo=IST)
        now = MutableNow(started)
        clock = MutableClock()
        api, dhan = make_api(Path(directory) / "baseline.json", now, clock)
        published = []

        assert api.start_cache_producer(
            None,
            symbol="NIFTY",
            interval_seconds=0.01,
            on_snapshot=published.append,
        ) is True
        assert api.start_cache_producer(
            None, symbol="NIFTY", interval_seconds=0.01
        ) is False
        deadline = time.monotonic() + 1
        while api.projection("NIFTY") is None and time.monotonic() < deadline:
            time.sleep(0.01)

        clock.value = 3.1
        now.value = started + timedelta(seconds=3.1)
        deadline = time.monotonic() + 1
        while dhan.chain_calls < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        api.stop_cache_producer()

        assert dhan.chain_calls == 2
        assert api.projection("NIFTY")["status"] == "available"
        assert published
        assert all(item["data"]["underlying"]["expiry"] == "2026-07-14" for item in published)


def test_truly_stale_or_malformed_argus_source_blocks_readiness():
    with TemporaryDirectory() as directory:
        started = datetime(2026, 7, 10, 10, 0, tzinfo=IST)
        now = MutableNow(started)
        clock = MutableClock()
        api, _ = make_api(Path(directory) / "baseline.json", now, clock)
        api.get_oi("NIFTY")

        clock.value = 12
        now.value = started + timedelta(seconds=21)
        stale = api.projection("NIFTY")
        assert stale["status"] == "stale"
        assert stale["reason"] == "ARGUS_SOURCE_STALE"

        cached = next(iter(api._cache.values()))
        cached["data"]["underlying"]["fetched_at"] = "malformed"
        malformed = api.projection("NIFTY")
        assert malformed["status"] == "stale"
        assert malformed["reason"] == "ARGUS_CACHE_UNAVAILABLE"


def test_fastapi_route_returns_contract_and_structured_4xx():
    with TemporaryDirectory() as directory:
        now = MutableNow(datetime(2026, 7, 10, 10, 0, tzinfo=IST))
        api, _ = make_api(
            Path(directory) / "baseline.json", now, MutableClock()
        )
        main = importlib.import_module("app.main")
        original = main.argus
        original_feed = main.option_chart_feed
        original_ose = main.options_structure_engine
        original_tactical = main.argus_tactical_edge
        original_coherent = main._argus_coherent_projection
        main.argus = api
        main.option_chart_feed = type(
            "ReadOnlyFeed", (), {"ingest": staticmethod(lambda _projection: None)}
        )()
        main.options_structure_engine = type(
            "ReadOnlyOSE", (), {"projection": staticmethod(lambda: {})}
        )()
        main.argus_tactical_edge = ArgusTacticalEdgeEngine(
            ArgusTacticalStore(Path(directory) / "tactical.json")
        )
        try:
            main._argus_coherent_projection = main.current_argus_projection(
                "NIFTY"
            )
            payload = main.argus_oi(symbol="NIFTY")
            assert payload["status"] == "available"
            assert payload["data"]["underlying"]["symbol"] == "NIFTY"
            assert len(payload["data"]["atm_window"]) == 11
            assert set(payload["data"]) == {
                "underlying",
                "totals",
                "atm_window",
                "walls",
                "dominance",
                "verdict",
                "provenance",
                "missing_fields",
                "tactical_edge",
            }
            assert payload["data"]["provenance"] == {
                "day_change_oi_basis": "previous_day",
                "intraday_change_oi_basis": "session_baseline",
                "activity_basis": "intraday_price_change_and_intraday_change_oi",
                "minimum_price_change": 0.05,
                "minimum_oi_change": 1,
            }

            try:
                main.argus_oi(symbol="NOT_AN_INDEX")
            except HTTPException as error:
                assert error.status_code == 404
                assert error.detail["error"]["code"] == "UNSUPPORTED_SYMBOL"
            else:
                raise AssertionError("Route should preserve the structured 404")
        finally:
            main.argus = original
            main.option_chart_feed = original_feed
            main.options_structure_engine = original_ose
            main.argus_tactical_edge = original_tactical
            main._argus_coherent_projection = original_coherent
