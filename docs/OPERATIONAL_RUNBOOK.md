# CITADEL Operational Runbook

## Start of day

Run the production checklist, inspect the operations dashboard, confirm the session calendar, validate Dhan authentication, and complete reconciliation before scheduler resume.

## Emergency stop

Use the internal `InstitutionalKillSwitch.activate_manual` workflow with an operator identity, reason and correlation ID. It stops Strategy Lab runtimes, cancels pending orders, blocks new entries and preserves monitoring. Never deactivate until the incident is understood and reconciliation passes.

Automatic triggers include broker/WebSocket disconnect, stale quotes, scheduler failure, position mismatch, duplicate execution, unexpected exception and critical runtime failure.

## Incident handling

Preserve logs and checkpoints, activate the kill switch, stop schedulers, reconcile broker state, follow the Recovery Guide, then document the decision. Do not retry an UNKNOWN broker submission.

## End of day

Confirm session exit state, reconcile positions and orders, checkpoint recovery state, archive structured logs and verify the next expiry/session configuration.
