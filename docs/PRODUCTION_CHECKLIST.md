# CITADEL Production Checklist

- [ ] Kill-switch persistence is healthy and currently INACTIVE.
- [ ] Broker, WebSocket and quote health are authoritative and fresh.
- [ ] Scheduler and every enabled runtime report a current heartbeat.
- [ ] Broker, runtime, dashboard, journal and replay positions reconcile.
- [ ] No unresolved or UNKNOWN exactly-once submissions exist.
- [ ] Recovery checkpoint contains positions, exits, scheduler, processed candles, journal and replay.
- [ ] CPU, memory, queue depth, latency and exception rates are within limits.
- [ ] Weekly/monthly expiry resolution has passed rollover validation.
- [ ] Paper and LIVE storage roots are isolated.
- [ ] Manual kill-switch drill and automatic failure drill have passed.
- [ ] LIVE activation has independent written approval.

Default state: PAPER; broker submission disabled.
