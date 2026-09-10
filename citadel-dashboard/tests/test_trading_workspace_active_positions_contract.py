from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "src/app/page.tsx").read_text(encoding="utf-8")
STYLES = (ROOT / "src/app/trading-workspace.module.css").read_text(encoding="utf-8")
ADAPTER = (ROOT / "src/dashboard/adapters/DashboardDataAdapter.ts").read_text(encoding="utf-8")


def workspace_source() -> str:
    start = PAGE.index("function TradingWorkspace")
    end = PAGE.index("function PersonalOraclePanel")
    return PAGE[start:end]


def test_active_positions_section_is_permanent_and_has_authentic_flat_state():
    workspace = workspace_source()
    assert workspace.count('aria-label="Active Positions"') == 1
    assert "rankedPositions.length ? (" in workspace
    assert "NO ACTIVE PAPER POSITIONS" in workspace
    assert "All registered strategies are currently flat." in workspace
    assert ") : null}" not in workspace[workspace.index('aria-label="Active Positions"'):workspace.index('aria-label="Personal Trading Intelligence"')]


def test_open_strategy_lab_fixture_uses_existing_card_and_closed_positions_are_excluded():
    workspace = workspace_source()
    open_position_fixture = {
        "position_id": "position-fixture-1",
        "strategy_id": "future-strategy",
        "status": "OPEN",
        "contract": "NIFTY JUL 25100 CE",
        "current_price": 154.5,
    }
    closed_position_fixture = {**open_position_fixture, "position_id": "position-fixture-closed", "status": "CLOSED"}
    fixtures = [open_position_fixture, closed_position_fixture]
    rendered = [position for position in fixtures if str(position.get("status", "OPEN")).upper() == "OPEN"]
    assert [position["position_id"] for position in rendered] == ["position-fixture-1"]
    assert "renderPositionHero(rankedPositions[0])" in workspace
    assert ".filter((position) => String(position.status ?? 'OPEN').toUpperCase() === 'OPEN')" in workspace
    assert "execution?.authoritative_open_positions ?? execution?.positions" in workspace
    assert "paperTrading.data" not in workspace[workspace.index("const positions ="):workspace.index("const schedulerRunning")]


def test_active_card_uses_held_contract_values_and_stable_position_identity():
    workspace = workspace_source()
    assert "const primary = strikeLabel && optionType" in workspace
    assert "`${underlying} ${strikeLabel} ${optionType}`" in workspace
    assert "contractIdentity.expiryLabel" in workspace
    assert "contractIdentity.tradingSymbol" in workspace
    assert "Quantity / Lots" in workspace
    assert "position.option_contract?.lot_size" in workspace
    assert "position.option_contract?.security_id" in workspace
    assert "data-position-id={positionId}" in workspace
    assert "position.current_price ?? null" in workspace
    assert "deployment?.current_decision?.underlying_price" not in workspace
    assert "key={position.position_id ?? position.trade_id ??" in workspace


def test_today_closed_positions_follow_active_positions_and_reuse_projection_panel():
    workspace = workspace_source()
    active = workspace.index('aria-label="Active Positions"')
    closed = workspace.index("<TodaysClosedTradesPanel", active)
    oracle = workspace.index('aria-label="Personal Trading Intelligence"')
    assert active < closed < oracle
    assert "data={execution?.todays_closed_trades}" in workspace
    assert workspace.count("<TodaysClosedTradesPanel") == 1
    assert PAGE.count("<TodaysClosedTradesPanel") == 1
    assert '.closedPanel { grid-area: closed;' in STYLES
    assert '"positions positions"\n    "closed closed"\n    "oracle oracle"' in STYLES


def test_store_adapter_remains_strategy_lab_scoped_without_direct_fetch():
    assert "const execution = object(strategyLab.execution)" in ADAPTER
    assert "const authoritative = list(execution.authoritative_open_positions).map(object)" in ADAPTER
    assert "const positions = authoritative.length ? authoritative : list(execution.positions).map(object)" in ADAPTER
    assert "const activePositions = positions.filter" in ADAPTER
    assert "string(item.status, 'OPEN').toUpperCase() === 'OPEN'" in ADAPTER
    assert "activePositions: activePositions.map" in ADAPTER
    assert "item.pnl_valid === false ? null" in ADAPTER
    assert "fetch(" not in PAGE


def test_unavailable_and_stale_held_contract_quotes_are_truthful():
    workspace = workspace_source()
    assert "MTM UNAVAILABLE" in workspace
    assert "MTM STALE" in workspace
    assert "QUOTE UNAVAILABLE" in workspace
    assert "position.stop_breach?.breached === true" in workspace


def test_oracle_has_full_workspace_span_in_both_position_states():
    assert ".oraclePanel { grid-area: oracle; width: 100%; }" in STYLES
    has_positions = STYLES[STYLES.index(".hasPositions"):STYLES.index(".flatBook")]
    flat_book = STYLES[STYLES.index(".flatBook"):STYLES.index(".positionsPanel")]
    assert '"oracle oracle"' in has_positions
    assert '"oracle oracle"' in flat_book
    assert '"positions positions"' in flat_book
