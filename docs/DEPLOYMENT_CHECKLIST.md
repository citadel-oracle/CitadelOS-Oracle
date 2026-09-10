# CITADEL Deployment Checklist

- [ ] All Python suites and production-operation tests pass.
- [ ] `live_trading_enabled` remains `false` during deployment verification.
- [ ] Runtime, journal, replay, order and recovery volumes are persistent and writable.
- [ ] Dhan credentials are supplied through the secret manager, never repository files.
- [ ] Static outbound IP is registered with Dhan.
- [ ] TLS, host clock synchronization and filesystem permissions are verified.
- [ ] `/v2/dashboard` and `/v1/strategy-lab/operations` return HTTP 200.
- [ ] Health states, heartbeat and structured log ingestion are visible.
- [ ] Restart recovery and position reconciliation pass before scheduler resume.
- [ ] Rollback artifact and previous configuration are available.
- [ ] Operator and incident ownership are assigned.

Deployment is blocked if any required item fails.
