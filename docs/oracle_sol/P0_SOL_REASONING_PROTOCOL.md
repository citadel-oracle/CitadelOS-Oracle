# CITADEL ORACLE SOL MARKET BRAIN — P0.1 REASONING PROTOCOL
## 9-PASS COGNITIVE REASONING SPECIFICATION (HARDENED)

> **Protocol Version**: `2.0.0-sol-p0.1`  
> **Module Path**: `src/oracle_sol/reasoning_protocol.py`

---

## 1. THE 9-PASS STRUCTURED SEQUENCE (ZERO FIXED PRIORS)

```
PASS 1: OBSERVE ─────────► What objectively changed in canonical market facts?
PASS 2: SEQUENCE ────────► Reconstruct chronological order from timestamps.
                           Ask: "What actually occurred first in the evidence timeline?"
                           (No presumed lead/lag prior).
PASS 3: POSITIONING ─────► What strike-wise positioning is forming or unwinding?
PASS 4: CALL CASE ───────► Construct the strongest factual Bull thesis.
PASS 5: PUT CASE ────────► Construct the strongest factual Bear thesis.
PASS 6: NO-TRADE CASE ───► Construct the strongest case why option buyers should AVOID trading.
PASS 7: SELF-ATTACK ─────► Actively challenge the favored interpretation against counter-evidence.
PASS 8: EVALUATIONS ─────► Evaluate previous pre-registered expectations (SUPPORTED,
                           PARTIALLY_SUPPORTED, CONTRADICTED, UNRESOLVED).
PASS 9: PRE-REGISTER ────► Update thesis state and pre-register testable forward expectations
                           with explicit invalidation conditions.
```

---

## 2. GROUNDING & SAFETY CONTROLS
* **No Invented Contradictions**: If evidence shows clean structural alignment without contradiction, Sol outputs `strongest_contradiction = "NONE_OBSERVED"`.
* **Honest Model Reporting**: Distinguishes `configured_model` (e.g. `gpt-5.6-sol`) from `actually_invoked_model` (which is `NONE` if no API call succeeded).
* **System Status vs Market Thesis**: When data or provider is unavailable, the system outputs `system_status = UNAVAILABLE` with `market_verdict = null`. It NEVER outputs fake `NO_TRADE`.
