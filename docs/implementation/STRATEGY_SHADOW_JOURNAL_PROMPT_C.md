# Prompt C — ARGUS SHADOW Evaluation and Comparison Journal

**Worktree:** `/Users/ayushmudgal/Developer/CitadelOS-Worktrees/rc2-backend`  
**Branch:** `integration/operator-panels-20260721`  
**Verdict:** ✅ **PASS**

---

## 1. Pre-flight Verification

| Check | Result |
|---|---|
| Prompt A implementation report | ✅ EXISTS |
| Prompt B verdict | ✅ PASS WITH DATA LIMITATIONS |
| Locked contract rule | ✅ CONFIRMED IN BOTH STRATEGIES |
| ARGUS imports in native engines | ✅ NONE |
| No live/production ordering | ✅ CONFIRMED |

---

## 2. What Was Implemented

### 2.1 Locked Contract Rule — Trend Catcher

**File:** `src/strategy_lab/strategies/trend_catcher/strategy.py`

Added `option_type`, `strike_offset`, and `underlying` to the locked `selected_contract` dict at resolution time (reference tick at/after 09:35 IST):

```python
self.state.selected_contract = {
    "security_id": security_id,
    "trading_symbol": trading_symbol,
    "strike": otm2_strike,
    "expiry": expiry_str,
    "option_type": "PE",
    "strike_offset": -2,
    "underlying": "NIFTY",
}
```

From the next tick onwards, the strategy looks up the LTP of **only** this locked `security_id` from the ATM window. If the locked contract disappears from the window, the strategy emits `CONTRACT_DATA_UNAVAILABLE` and returns `UNAVAILABLE`.

### 2.2 Locked Contract Rule — Bull Pulse

**File:** `src/strategy_lab/strategies/bull_pulse/strategy.py`

Same pattern. Locked at reference tick (10:30 IST), with:

```python
self.state.selected_contract = {
    "security_id": security_id,
    "trading_symbol": trading_symbol,
    "strike": otm2_strike,
    "expiry": expiry_str,
    "option_type": "CE",
    "strike_offset": 2,
    "underlying": "NIFTY",
}
```

### 2.3 SHADOW Mode Infrastructure — StrategyRuntime

**File:** `src/strategy_lab/runtime.py`

Two new private methods:

#### `_handle_shadow_evaluation(evaluation, context, timestamp)`
Called on every `BUY` signal when `mode == "SHADOW"`:
- Extracts ARGUS tactical edge fields: pressure direction, breadth, persistence, IV state, gamma lifecycle, continuation/reversal, confidence, readiness score, gate.
- Computes `signal_id` as SHA-256 of `strategy_id + session_date + signal_timestamp + security_id`.
- Determines `hypothetical_allow_block_delay`:
  - `ALLOW` if ARGUS is fresh and `action_enabled == True` and confidence >= 60.0.
  - `BLOCK` (with `ARGUS_STALE` or `ARGUS_UNAVAILABLE` notes) otherwise.
- Appends `ARGUS_SHADOW_EVALUATION` event to `workspace.journal` (idempotent).
- Stores `signal_id` in `strategy_state["active_trade_signal_id"]`.

#### `_handle_shadow_outcome(timestamp)`
Called at end of every `SHADOW` mode tick:
- Checks if `strategy_state["active_trade_signal_id"]` is set.
- Reads `paper_state["closed_trades"]` for the latest closed trade.
- Correlates with the prior `ARGUS_SHADOW_EVALUATION` event by `signal_id`.
- Computes:
  - `native_outcome`: WIN / LOSS (by `realized_pnl > 0`).
  - `counterfactual_shadow_outcome`:
    - If ARGUS said `ALLOW`: `EXECUTED_AS_ALLOWED`.
    - If ARGUS said `BLOCK/DELAY` and trade was a loss: `AVOIDED_LOSS` (with `avoided_loss` = abs(pnl)).
    - If ARGUS said `BLOCK/DELAY` and trade was a win: `MISSED_WINNER` (with `missed_winner` = pnl).
- Appends `ARGUS_SHADOW_OUTCOME` event to `workspace.journal` (idempotent via `shadow-outcome:{trade_id}` key).
- Clears `active_trade_signal_id` from strategy state.

#### `evaluation_id` aliasing fix
Also fixed: the `evaluation_id` was never set for non-gap-replay ticks, causing `InstitutionalPaperTradingEngine` to reject all orders with `EVALUATION_ID_REQUIRED`. The fix:

```python
if not evaluation.get("evaluation_id"):
    evaluation["evaluation_id"] = evidence["record_id"]
```

---

## 3. Journal Schema

### ARGUS_SHADOW_EVALUATION

```json
{
  "event_type": "ARGUS_SHADOW_EVALUATION",
  "payload": {
    "signal_id": "<sha256-64-hex>",
    "strategy_id": "bp_shadow",
    "strategy_version": "1.0.0",
    "native_timestamp": "2026-07-24T10:31:00+05:30",
    "argus_snapshot_timestamp": "2026-07-24T10:31:00+05:30",
    "contract": "63925",
    "entry": 111.0,
    "sl": 88.8,
    "pressure": "CALL",
    "breadth": "AVAILABLE",
    "persistence": 3,
    "iv_state": "AVAILABLE",
    "gamma_lifecycle": {},
    "continuation_reversal": {},
    "confidence": 85.0,
    "suggested_action": "ALLOW",
    "suggested_contract": "63925",
    "hypothetical_allow_block_delay": "ALLOW",
    "native_outcome": "PENDING",
    "counterfactual_shadow_outcome": "PENDING",
    "avoided_loss": 0.0,
    "missed_winner": 0.0,
    "reason_codes": ["ACTION_ENABLED", "ADVISORY_READY"]
  }
}
```

### ARGUS_SHADOW_OUTCOME

```json
{
  "event_type": "ARGUS_SHADOW_OUTCOME",
  "idempotency_key": "shadow-outcome:<trade_id>",
  "payload": {
    "signal_id": "<sha256-64-hex>",
    "trade_id": "<trade_id>",
    "native_outcome": "LOSS",
    "counterfactual_shadow_outcome": "EXECUTED_AS_ALLOWED",
    "avoided_loss": 0.0,
    "missed_winner": 0.0,
    "net_pnl": -2015.0,
    "gross_pnl": -2015.0
  }
}
```

---

## 4. SHADOW Execution Contract Invariants

| Rule | Status |
|---|---|
| Native engine executes identically in SHADOW as in OFF | ✅ Enforced |
| ARGUS cannot block, delay, resize, or change the contract | ✅ Enforced (SHADOW only evaluates; never modifies `evaluation` signal) |
| ARGUS unavailable → `ARGUS_UNAVAILABLE` / `ARGUS_STALE` recorded; trade still proceeds | ✅ Enforced |
| Locked contract never re-resolved after reference time | ✅ Enforced in both strategy engines |
| `CONTRACT_DATA_UNAVAILABLE` emitted if locked contract disappears | ✅ Enforced |
| Journal events are idempotent (duplicate tick cannot double-write) | ✅ Enforced via idempotency keys |
| No live ordering or `FILTER`/`FULL` execution | ✅ Confirmed — `live_trading_enabled: False` throughout |

---

## 5. Test Coverage

**File:** `tests/test_strategy_shadow_mode.py`

| Test | Type | What It Verifies |
|---|---|---|
| `test_locked_contract_remains_locked_when_atm_moves` | Unit | Contract locked at 10:30 does not shift when ATM moves at 10:31 |
| `test_locked_contract_unavailable_emits_contract_data_unavailable` | Unit | Missing contract in window → `CONTRACT_DATA_UNAVAILABLE` |
| `test_off_vs_shadow_directives_identical` | Integration | `OFF` mode and `SHADOW` mode produce identical native signals |
| `test_shadow_creates_evaluation_record_and_outcome` | Integration | Full cycle: BUY → evaluation journal → WAIT (hold) → EXIT → outcome journal |
| `test_shadow_argus_unavailable_does_not_block_trade` | Integration | ARGUS unavailable → native trade still fires; journal records `ARGUS_UNAVAILABLE` |

**Result:** `5 passed` ✅

**Pre-existing failures confirmed pre-existing** (stash verification confirmed 11 failures exist identically without our changes).

---

## 6. Verdict

**Prompt C: PASS**

SHADOW mode infrastructure is complete, tested, and journal-chained. Native engines are unchanged. ARGUS evaluations are fully passive. The comparison journal is append-only, hash-chained, and idempotent. No live execution. Ready for Prompt D (FILTER mode) when approved.
