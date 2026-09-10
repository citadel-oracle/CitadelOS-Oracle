"""Explicit deterministic order lifecycle transitions."""

TERMINAL_STATES = {"FILLED", "CANCELLED", "REJECTED", "EXPIRED", "FAILED"}
TRANSITIONS = {
    "INTENT_CREATED": {"VALIDATED", "REJECTED", "FAILED"},
    "VALIDATED": {"AUTHORIZED", "REJECTED", "FAILED"},
    "AUTHORIZED": {"QUEUED", "CANCELLED", "FAILED"},
    "QUEUED": {"SUBMITTED", "CANCELLED", "REJECTED", "FAILED", "EXPIRED"},
    "SUBMITTED": {"ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "CANCELLED", "REJECTED", "FAILED", "EXPIRED", "RECONCILIATION_REQUIRED"},
    "ACKNOWLEDGED": {"PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "CANCELLED", "REJECTED", "FAILED", "EXPIRED", "RECONCILIATION_REQUIRED"},
    "PARTIALLY_FILLED": {"PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "CANCELLED", "FAILED", "EXPIRED", "RECONCILIATION_REQUIRED"},
    "CANCEL_PENDING": {"CANCELLED", "PARTIALLY_FILLED", "FILLED", "FAILED", "RECONCILIATION_REQUIRED"},
    "RECONCILIATION_REQUIRED": {"PARTIALLY_FILLED", "FILLED", "CANCELLED", "FAILED"},
}


def validate_transition(current: str | None, target: str) -> None:
    if current is None:
        if target != "INTENT_CREATED": raise ValueError("first event must be INTENT_CREATED")
        return
    if current in TERMINAL_STATES: raise ValueError("terminal order cannot transition")
    if target not in TRANSITIONS.get(current, set()): raise ValueError(f"invalid transition {current} -> {target}")
