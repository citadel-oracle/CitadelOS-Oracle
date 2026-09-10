# Authoritative Kill Switch

## State ownership

`src.risk.authorization.RiskControlStore` is the sole authoritative kill-switch store. Its default persistence location is the ignored runtime document `logs/risk_control_state.json`; no frontend, environment variable, AEGIS cache, or second file owns the state. Writes use a same-directory temporary file, `fsync`, and atomic replacement.

The sanitized schema-v1 projection exposes `enabled`, `state` (`ACTIVE`, `INACTIVE`, `UNKNOWN`, or `CORRUPT`), reason, activation/deactivation/update timestamps, source, schema version, persistence health, last valid state, and warnings. It never exposes paths, actor identity, credentials, or raw persistence content.

## Initialization and persistence

At the July 2026 recovery audit, the documented store was genuinely absent: no valid, corrupt, ambiguous, or competing state existed. The one existing store was initialized once under the explicitly authorized policy with `INACTIVE` and reason `INITIALIZED_SAFE_DEFAULT`. Initialization refuses to overwrite an existing document. Metadata was subsequently enriched in place without changing its logical state, reason, or original timestamp.

A valid ACTIVE or INACTIVE state survives service/process restart. Existing valid state is preserved exactly unless the pre-existing internal authorized activation/deactivation contract is explicitly invoked. This milestone added no public mutation route or UI control.

## Fail-closed behavior

Missing state projects `UNKNOWN/MISSING`; malformed JSON, invalid version, or malformed schema projects `CORRUPT/CORRUPT`. Both deny Risk Authorization and block AEGIS. No missing or corrupt document is silently recreated. `last_valid_state` is null when the current document cannot prove a valid state; the system does not invent recovery history.

Risk Authorization consumes this projection as an absolute veto: ACTIVE, UNKNOWN, and CORRUPT deny with distinct reason codes; INACTIVE only allows evaluation to continue through every other configured gate. It is never equivalent to trade approval.

## Read-only exposure

`GET /v1/risk/kill-switch` returns the sanitized projection. `GET /v1/risk/status` returns the same state in its aggregate safety response. The dashboard polls both through its existing three-second read-only loop and shows state, reason, persistence health, and update time without controls.

Live trading remains disabled. The numerical risk configuration remains non-live defaults, not validated production risk settings.
