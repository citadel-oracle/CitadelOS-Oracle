# Order & Fill Ledger Foundation

## Purpose and boundary

`src/order_ledger/` is CITADEL OS's authoritative schema-v1 audit memory for order intentions, lifecycle events, and externally observed fills. It is not an execution engine. It has no submit/place/send/execute method, never calls broker transport, never applies fills to Paper State, and fixes live trading, broker submission, and execution-request flags to false.

The runtime store is the Git-ignored `logs/order_fill_ledger.json`. A missing file is a healthy, truthful empty ledger and GET reads do not create it. Invalid JSON or schema fails closed as corrupt and is never silently repaired.

## Contracts

- `OrderIntent`: immutable identity, instrument/action, integer quantity and lot consistency, prices/reference source, strategy/version, AEGIS and Risk provenance, market/session/kill-switch provenance, and fixed safety flags.
- `OrderEvent`: append-only transition with actor, reason, time, optional broker identifier, and bounded details.
- `FillEvent`: immutable observed fill identity, integer quantity, Decimal price, side, time, and safe broker/source references.
- `FillApplicationRequest`: future Paper Execution contract, always `applied=false` in this foundation.

Requested quantity is immutable. Authorized quantity cannot exceed requested quantity. Fill totals are evaluated against the event-authorized quantity. Excess fill evidence is preserved and moves the reconstructed order to `RECONCILIATION_REQUIRED`.

## Lifecycle

The explicit state machine begins at `INTENT_CREATED`, then permits validation, authorization, queue/submission observation, acknowledgement, partial/final fill, cancel, rejection, expiry, failure, and reconciliation transitions. Invalid skips and every transition out of terminal state fail. Stable event/fill identities make exact replay idempotent; a conflicting payload with the same identity fails.

The service may record that a submission was observed, but it cannot cause submission. Runtime authorization evidence fails closed when Risk is not ALLOW, kill switch is not INACTIVE, AEGIS is not APPROVE/APPROVE_REDUCED, or session is not OPEN/SPECIAL_SESSION. `APPROVE_REDUCED` must produce a genuinely smaller authorized quantity.

## Accounting

Fill prices and derived arithmetic use `Decimal`. Average fill is quantity weighted. Slippage is fill minus reference for BUY and reference minus fill for SELL, so positive is adverse and negative is improvement. Reference provenance is retained; absence reports unavailable.

Cost results are itemized and use an effective, versioned schedule contract with `NOT_CALCULATED`, `ESTIMATED`, `ACTUAL`, `RECONCILED`, or `UNAVAILABLE` semantics. The default foundation schedule is explicitly `ESTIMATED` and `NOT_REGULATORY_OR_BROKER_RECONCILED`; it makes no current statutory/broker accuracy claim.

## Persistence and integrity

One schema-versioned JSON document contains append-only intent, event, fill, and cost-schedule arrays. Writes use a process-local lock, temporary file, file fsync, atomic replacement, and directory fsync. Active orders are never silently deleted. Multi-process coordination and a database-backed retention/reconciliation process remain future work.

Integrity reports orphan evidence and corruption. Broker reconciliation is `NOT_PERFORMED`; raw broker state is not claimed.

## Read-only API

- `GET /v1/orders/status`
- `GET /v1/orders`
- `GET /v1/orders/integrity`
- `GET /v1/orders/{intent_id}`
- `GET /v1/orders/{intent_id}/events`
- `GET /v1/orders/{intent_id}/fills`
- `GET /v1/orders/{intent_id}/costs`
- `GET /v1/orders/{intent_id}/slippage`
- `GET /v1/fills`
- `GET /v1/fills/{fill_id}`

Lists are bounded. No POST, PUT, PATCH, DELETE, execution, broker, Paper, Risk, or kill-switch route exists.

## Frontend

The dashboard adds `ORDER & FILL OPERATIONS` immediately after AEGIS and reuses the existing three-second polling/retry/stale architecture. It always shows ledger health/counts, audit-only mode, Execution Engine NOT ACTIVE, Broker Submission DISABLED, Live Trading FALSE, and an exact empty state. It exposes no control.

## Limitations

Production begins empty with no seeded intents. There is no execution engine, fill acquisition, broker reconciliation, actual broker cost schedule, cross-process lock, automatic Paper State application, order retention compactor, or live path. These are unavailable, not simulated.
