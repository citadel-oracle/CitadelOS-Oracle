# Strategy Lab Institutional Paper Trading Engine

## Boundary

This engine exists only under Strategy Lab. It does not import or mutate Production or Development Paper State, Risk, ledgers, schedulers, strategies, or accounts. It has no broker client and always reports `live_trading_enabled=false` and `broker_submission=false`.

## Authoritative ownership

Each strategy owns one workspace and one aggregate:

`Signal → Risk → Order → ExecutionProvider → Fill → Position → Trade → Journal → Replay → Statistics → Default Portfolio`

`paper_transactions.jsonl` is the immutable event/recovery stream. `paper_engine_state.json` is the atomic materialized state recovered from the last valid `StateCommitted` snapshot. Order/fill streams are audit projections. Legacy Paper State and statistics documents are read projections. No other module owns or recalculates strategy P&L, positions, capital, or statistics.

## Provider contract

`ExecutionProvider.execute(...)` receives an immutable order, market context, reference price, and paper cost policy. It returns an `ExecutionReport`; it cannot mutate OMS, account, position, journal, replay, statistics, or portfolio state.

Only `PaperExecutionProvider` is implemented. It supports deterministic market, limit, and stop paper matching, partial quantities, fees, and slippage. There is no broker provider, provider API, or provider-selection UI.

## Account and risk policy

Capital is declared in strategy metadata under `parameters.paper_account`. Required fields are `initial_capital`, `sizing_mode`, `max_daily_loss`, `max_concurrent_positions`, and `max_trades_per_day`, plus the selected sizing inputs:

- `FIXED_LOTS`: `fixed_lots` and `lot_size`.
- `FIXED_RUPEE_RISK`: `fixed_rupee_risk` and `lot_size`; quantity is risk budget divided by entry-to-stop distance and rounded down to a lot.
- `FIXED_PERCENT`: `fixed_risk_percent` and `lot_size`; the budget is current equity times the configured percentage, then divided by entry-to-stop distance and rounded down to a lot.

Missing or invalid configuration rejects actionable signals with a persisted reason. No default capital or risk threshold is invented.

Current equity is initial capital plus realized and unrealized P&L. Realized P&L is closed gross P&L less all recorded fill fees; open-entry fees therefore reduce equity immediately. Margin is current notional times the configured margin rate. Available margin and buying power are equity less margin used. Recovery is the amount recovered from the maximum recorded drawdown relative to current drawdown. Sharpe remains an explicit placeholder until a return-series sampling policy is approved.

## Event bus and lineage

The internal publish/subscribe bus records the required lifecycle events. IDs are deterministic or immutable. Each downstream entity carries parent IDs and lineage. Duplicate evaluation IDs are idempotent. The runtime adds immutable journal and replay IDs after execution and then publishes statistics/dashboard lineage.

## GET-only APIs

- `/v1/strategy-lab/paper/portfolio`
- `/v1/strategy-lab/paper/capital`
- `/v1/strategy-lab/paper/positions`
- `/v1/strategy-lab/paper/orders`
- `/v1/strategy-lab/paper/fills`
- `/v1/strategy-lab/paper/statistics`
- `/v1/strategy-lab/paper/open-trades`
- `/v1/strategy-lab/paper/closed-trades`

All per-strategy endpoints accept an optional `strategy_id`. They have no mutation counterpart.

## Future portfolio boundary

`portfolio_strategy_lab_default` is the only portfolio. Its projection aggregates independently owned strategy accounts. The schema is ready to identify portfolios later, but multi-portfolio allocation, risk, leaderboard, and routing are intentionally not implemented.
