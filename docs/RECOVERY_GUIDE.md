# CITADEL Recovery Guide

1. Keep the kill switch active and leave schedulers stopped.
2. Restore the latest atomic operational checkpoint.
3. Validate journal, replay, processed-candle and exactly-once state integrity.
4. Authenticate to Dhan and retrieve current orders and positions read-only.
5. Reconcile broker, runtime, dashboard, journal and replay positions.
6. Resolve every UNKNOWN submission by correlation ID; never resubmit blindly.
7. Restore targets, stops, trailing stops and pending exits.
8. Reconnect the full-quote WebSocket and require a fresh quote.
9. Resume schedulers only after reconciliation returns MATCHED.
10. Record a structured RECOVERY event and obtain operator approval.

Any mismatch leaves trading blocked. Monitoring remains active throughout recovery.
