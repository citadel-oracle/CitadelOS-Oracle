# Next Production Milestone — OPEN-MARKET VERSION 2 PAPER VALIDATION

Real-Market Paper Trading Activation is complete at implementation/readiness scope. The next task is one controlled NSE open-session observation of the real-data, paper-only path.

## Objective

Observe and validate closed-candle scheduling, strategy evaluation, ARGUS/AEGIS/Risk gates, dynamic contract/lot resolution, simulated fills, Paper State marks/exits, P&L, restart behavior, and the single-request Version 2 dashboard projection during real market hours without changing policy or enabling broker submission.

## Boundaries

- Paper only; `live_trading_enabled=false`.
- No Dhan order, tradebook, position, holding, or fund mutation/read dependency.
- No strategy tuning or new strategy.
- No threshold relaxation to force a trade.
- A valid no-trade session is acceptable evidence.
- Do not alter KRONOS ALPHA or CHRONOS-2 SHADOW influence.
- Do not touch the separate research repository or expose secrets.

Do not begin without explicit authorization during an eligible market session.
