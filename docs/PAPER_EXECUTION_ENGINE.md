# Real-Market Paper Trading Engine

## Production mode

The runtime mode is `REAL_DATA_PAPER_ONLY`. Dhan supplies market candles, option-chain quotes, option security identifiers, top-of-book fields when available, and the instrument-master lot size. The engine never calls an order endpoint, never grants broker authorization, and requires `live_trading_enabled=false`.

The only activated strategy is the existing unchanged `SimplePullbackStrategy`. `StrategyRegistry` permits at most two existing strategies but does not duplicate or rewrite their logic.

## Lifecycle

`RealMarketPaperOrchestrator` is owned by backend application lifecycle, not a GET handler. Every three seconds it may update an existing paper position from a read-only Dhan option quote. Entry evaluation occurs only once per unique completed NIFTY five-minute candle already persisted by the shared canonical candle source. Frontend polling reads projections only and cannot execute a strategy, refresh a model, resolve a contract, or create a fill.

Entry sequence:

1. canonical NSE session must be OPEN/SPECIAL_SESSION;
2. a unique `closed=true` candle with `candle_closed_at <= now` must exist;
3. the unchanged strategy must return one directional signal;
4. ARGUS refreshes the real NIFTY option chain at the controlled backend boundary;
5. the same closed-candle context is converted into typed Technical Intelligence and KRONOS CORE evidence, so AEGIS does not depend on a frontend-created dashboard snapshot;
6. AEGIS must return APPROVE; APPROVE_REDUCED is denied because one exchange lot cannot be fractionally reduced;
7. the ATM CE/PE security and quote are selected from ARGUS;
8. current lot size is resolved from Dhan's detailed instrument master;
9. Paper Risk Authorization must ALLOW every hard limit;
10. an immutable paper-only order intent and simulated-submission events enter the Order & Fill Ledger;
11. the fill model uses observed top ask for BUY, top bid for SELL, otherwise observed LTP with explicit provenance;
12. a complete fill is applied once to authoritative Paper State; partial fills remain ledger-only until continued to the full lot;
13. authoritative Paper State supplies position and P&L projections.

## Hard limits and vetoes

- NIFTY options only.
- One dynamically resolved exchange lot maximum.
- One open position maximum.
- Two entered/completed trades per IST trading day maximum (the stricter entry count is used).
- No averaging or pyramiding.
- No entry after 15:15 IST.
- Mandatory square-off attempt from 15:20 IST.
- No overnight permission; any discovered closed-session position is a blocking breach requiring reconciliation.
- Kill switch must be INACTIVE and healthy.
- Paper State and runtime state must be available.
- Risk daily loss, consecutive loss, duplicate request, freshness, and per-trade maximum-loss gates remain absolute.
- Long-option maximum loss is conservatively the observed entry ask/LTP multiplied by the one-lot quantity. If it exceeds the current configured per-trade risk, no trade opens.
- AEGIS WAIT/REJECT/BLOCK or unavailable contract/lot/quote denies entry.

The existing broker `RiskAuthorizationService` remains unchanged and continues to deny broker mutations while live trading is disabled. `PaperRiskAuthorization` is a separate paper-only projection; `broker_authorization=false` is permanent.

## Fill and exit semantics

`TOP_OF_BOOK_OR_LTP_V1` uses no invented spread or slippage. BUY fills use current ask when supplied by Dhan; SELL fills use current bid; otherwise LTP is disclosed. Displayed partial top-of-book quantity limits a simulated fill. A partial entry does not open Paper State; subsequent backend ticks may fill the remainder, after which the quantity-weighted ledger average is applied exactly once.

Positions are long CE or PE only. The strategy's underlying NIFTY stop and target remain underlying triggers in immutable intent metadata; they are not mislabeled as option-premium stops. Option P&L uses the actual simulated option entry/exit prices and raw exchange quantity. Marks use Dhan market-feed LTP. The exit engine checks stop/target only on a newly completed underlying candle and performs the intraday time exit using the latest option quote.

## Restart and corruption

Paper State and Order & Fill Ledger remain authoritative. The runtime document stores the last evaluated closed candle, last signal/gates/mark, and a bounded timeline using atomic fsync replacement. Exact intent/fill/Paper event identifiers make replay idempotent. A corrupt runtime document blocks evaluation; it is never silently repaired. A pending partial entry is resumed before any new strategy evaluation.

## GET-only API

- `/v1/paper-trading/status`
- `/v1/paper-trading/readiness`
- `/v1/paper-trading/strategies`
- `/v1/paper-trading/timeline`
- `/v1/paper-trading/position`
- `/v1/paper-trading/pnl`
- `/v1/paper-trading/dashboard`

All routes are projections. There is no public start, stop, submit, fill, close, reset, or mutation route.

## Known limitations

No real open-session observation has yet been completed by this new path. Dhan option-chain/instrument-master availability and current risk settings may prevent an otherwise valid setup. Existing AEGIS hard gates remain unchanged: for example, unavailable HERMES or conservative ATHENA state may correctly keep AEGIS at WAIT. Top-of-book absence falls back truthfully to LTP. A process outage near square-off can leave a position requiring explicit reconciliation; the system reports the breach rather than inventing an exit. There is no broker order, tradebook, margin, or fill reconciliation because broker submission is prohibited. Paper fills are simulations, not evidence of executable market liquidity beyond the observed quote/quantity.
