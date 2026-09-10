# CITADEL Production Configuration Guide

Required non-secret configuration includes runtime mode, quote-age threshold, request timeout, status-poll attempts, resource thresholds, queue limit and isolated PAPER/LIVE storage roots.

Secrets must come from the deployment secret manager:

- `DHAN_CLIENT_ID`
- `DHAN_ACCESS_TOKEN`

Never log or persist credentials. LIVE requires three independent conditions: explicit LIVE runtime mode, broker submission enabled, and the authoritative global live-trading gate enabled. Phase 10B intentionally leaves every gate disabled.

FINNIFTY and MIDCPNIFTY require authoritative Dhan underlying metadata before use; values must never be guessed.
