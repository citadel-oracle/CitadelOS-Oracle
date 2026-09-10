"""R3 proof of the reachable, continuously scheduled Option Chain producer."""

from __future__ import annotations

import ast
import inspect
import time
from pathlib import Path
from unittest.mock import patch

from src.argus.market_snapshot import ArgusMarketSnapshotProvider
from src.argus.option_chain_engine import OptionChainEngine
from src.broker.dhan_client import DhanClient
from src.oracle.isolated_market_data_gateway import IsolatedMarketDataGateway


ROOT = Path(__file__).resolve().parents[1]
APP_MAIN = ROOT / "app" / "main.py"
ARGUS_API = ROOT / "src" / "api" / "argus_api.py"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"missing production function: {name}")


def _attribute_call(node: ast.AST, attribute: str) -> list[ast.Call]:
    return [
        call
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == attribute
    ]


def _startup_optionchain_producers(extra: list[tuple[str, str]] | None = None) -> list[tuple[str, str]]:
    """Discover producer registrations from the real startup function.

    The list is derived from production AST and callback edges, not a
    hard-coded producer count. ``extra`` exists only for negative control.
    """

    app_tree = _tree(APP_MAIN)
    startup = _function(app_tree, "_hydrate_oracle_runtime_inner")
    registrations = []
    for call in _attribute_call(startup, "start_cache_producer"):
        owner = ast.unparse(call.func.value)
        callback = next(
            (
                ast.unparse(keyword.value)
                for keyword in call.keywords
                if keyword.arg == "on_snapshot"
            ),
            "",
        )
        registrations.append((owner, callback))

    fanout = _function(app_tree, "_argus_cache_fanout")
    enrich = _function(app_tree, "_enrich_argus_projection")
    refresh_calls = _attribute_call(enrich, "refresh")
    assert refresh_calls, "ArgusMarketSnapshotProvider.refresh is no longer in the enrichment path"
    enrich_calls = [
        call
        for call in ast.walk(fanout)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "_enrich_argus_projection"
    ]
    assert any(
        any(
            keyword.arg == "refresh_market"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in call.keywords
        )
        for call in enrich_calls
    ), "startup fanout no longer reaches ArgusMarketSnapshotProvider.refresh"

    api_tree = _tree(ARGUS_API)
    producer_loop = _function(api_tree, "_cache_producer_loop")
    get_oi = _function(api_tree, "_get_oi")
    assert any(
        isinstance(call.func, ast.Attribute) and call.func.attr == "_get_oi"
        for call in ast.walk(producer_loop)
        if isinstance(call, ast.Call)
    ), "continuous producer no longer calls ArgusAPI._get_oi"
    assert any(
        isinstance(call.func, ast.Attribute) and call.func.attr == "fetch_current_snapshot"
        for call in ast.walk(get_oi)
        if isinstance(call, ast.Call)
    ), "ArgusAPI producer no longer reaches OptionChainEngine.fetch_current_snapshot"
    assert any(
        isinstance(call.func, ast.Attribute) and call.func.attr == "get_option_chain"
        for call in ast.walk(get_oi)
        if isinstance(call, ast.Call)
    ), "ArgusAPI producer no longer reaches DhanClient.get_option_chain"

    registrations.extend(extra or [])
    return registrations


def _assert_one_producer(registrations: list[tuple[str, str]]) -> None:
    assert len(registrations) == 1, registrations
    owner, callback = registrations[0]
    assert owner == "argus"
    assert callback == "_argus_cache_fanout"
    assert "ArgusMarketSnapshotProvider" in inspect.getsource(ArgusMarketSnapshotProvider)


def test_dhan_option_chain_rate_guard_spacing():
    """The central guard applies across distinct DhanClient instances."""

    c1 = DhanClient(access_token="mock_tok", client_id="mock_id")
    c2 = DhanClient(access_token="mock_tok", client_id="mock_id")
    with patch.object(c1, "_post", return_value={"data": "chain1"}), patch.object(
        c2, "_post", return_value={"data": "chain2"}
    ):
        with DhanClient._option_chain_lock:
            DhanClient._last_option_chain_request_monotonic = 0.0
        t0 = time.monotonic()
        c1.get_option_chain("IDX_I", 13, "2026-08-20")
        assert time.monotonic() - t0 < 0.5
        c2.get_option_chain("IDX_I", 13, "2026-08-20")
        assert time.monotonic() - t0 >= 2.95


def test_single_market_data_gateway_owner_topology():
    gw = IsolatedMarketDataGateway()
    health = gw.health()
    assert health["status"] == "DOWN"
    assert health["WS_OWNER_COUNT"] == 0
    assert health["ISOLATION_TIER"] == "SEPARATE_PROCESS"


def test_reachable_production_optionchain_topology_exclusivity():
    registrations = _startup_optionchain_producers()
    _assert_one_producer(registrations)
    assert registrations[0][0] == "argus"
    assert registrations[0][1] == "_argus_cache_fanout"
    assert DhanClient.MIN_OPTION_CHAIN_INTERVAL_SECONDS >= 3.0


def test_negative_control_detects_second_continuous_producer():
    """The same topology assertion rejects an in-memory second registration."""

    registrations = _startup_optionchain_producers(
        extra=[("rogue_producer", "rogue_optionchain_callback")]
    )
    try:
        _assert_one_producer(registrations)
    except AssertionError:
        return
    raise AssertionError("negative control failed to detect a second producer")
