from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = (ROOT / "src/components/institutional/TodaysClosedTradesPanel.tsx").read_text(encoding="utf-8")
STYLES = (ROOT / "src/app/trading-workspace.module.css").read_text(encoding="utf-8")


def test_closed_positions_preserve_all_projected_trades_and_empty_only_on_zero_rows():
    assert "trades.length === 0" in COMPONENT
    assert "trades.map((trade) =>" in COMPONENT
    assert "key={trade.trade_id}" in COMPONENT
    assert "data-trade-id={trade.trade_id}" in COMPONENT
    assert "trades.filter(" not in COMPONENT
    assert "summary.completed_trades === 0" not in COMPONENT


def test_closed_positions_show_operator_identity_lifecycle_and_paper_scope():
    for token in (
        "readableContract",
        "tradingSymbol",
        "expiry",
        "trade.strategy",
        "quantity",
        "lots",
        "trade.entry_price",
        "trade.exit_price",
        "trade.realized_pnl",
        "trade.exit_reason",
        "duration(trade.holding_duration_seconds)",
        ">Paper</Badge>",
        'aria-label="Today Closed Positions"',
    ):
        assert token in COMPONENT


def test_closed_positions_use_ist_and_never_promote_security_id():
    assert "timeZone: 'Asia/Kolkata'" in COMPONENT
    assert "Contract {trade.contract}" not in COMPONENT
    assert "`${underlying} ${strike} ${optionType}`" in COMPONENT


def test_closed_positions_reuse_workspace_design_tokens_and_compact_ledger_structure():
    for token in (
        "var(--cds-color-surface)",
        "var(--cds-border-subtle)",
        "var(--cds-radius-sm)",
        "var(--cds-type-caption-size)",
        "var(--cds-font-mono)",
        ".closedLedgerHeader",
        ".closedTradeRow",
        ".closedPaperBadge",
    ):
        assert token in STYLES
    assert "workspaceStyles.closedPanel" in COMPONENT
    assert 'role="table"' in COMPONENT
    assert 'role="row"' in COMPONENT
    assert 'role="cell"' in COMPONENT
