# CITADEL Production Monitoring Guide

The authoritative operational projection is exposed at `/v1/strategy-lab/operations` and inside the existing `/v2/dashboard` aggregation. No additional frontend polling loop is required.

Monitor scheduler, broker, WebSocket, quotes, Strategy Lab runtimes, paper engine, latency, CPU, memory, queue depth and exceptions. Alert on FAILED/UNAVAILABLE critical components and DEGRADED resource states.

Structured JSONL events contain timestamp, strategy, runtime mode, correlation ID, symbol, timeframe, event type, latency and status. Secret fields are removed before persistence.

Critical broker, quote, scheduler, reconciliation, duplicate-execution and runtime failures must activate the institutional kill switch. Monitoring must remain active after activation.
