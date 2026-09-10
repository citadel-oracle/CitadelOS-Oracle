# Strategy Argus Dual-Mode Architecture Plan

## Executive Summary
This document outlines the architecture for onboarding the **Nifty Trend Catcher** and **Nifty Bull Pulse** strategies into the CitadelOS Strategy Lab framework. Both strategies are options-buying algorithms designed to execute in two primary comparison states:
1. **MODE A (Native Only):** The pure native strategy running independently of ARGUS.
2. **MODE B (ARGUS-Assisted):** The exact same native strategy running with option filters, scoring, or execution limits assisted by ARGUS telemetry.

Dual-mode comparison runs support five distinct modes (`OFF`, `SHADOW`, `FILTER`, `SCORING`, `FULL`) evaluated side-by-side using shared signal IDs, enabling counterfactual P&L attribution and rigorous ablation studies.

---

## 1. Nifty Trend Catcher: Extracted Rules
* **Market/Instrument:** Nifty 50 Index Options (PE only - Bearish).
* **Option Type:** Put Option Buying.
* **DTE (Days to Expiry):** 1 DTE calendar-wise (typically trades on Wednesday for Thursday weekly expiry).
* **Lots:** 1.
* **Strike Selection:** OTM2 PE (strike 2 intervals below ATM strike; resolved using actual weekly option intervals).
* **Expiry Selection:** Weekly (nearest weekly eligible contract resolved via calendar).
* **Session Window:** 
  * **Entry Checks:** Starts at `09:35`.
  * **Exit Checks/Square-off:** Active until `15:15`.
* **Indicators & Parameters:**
  * **Simple Momentum:** Leg-level premium momentum of 40% (monitors option premium changes).
* **Entry Conditions:** The premium of the selected OTM2 PE option increases by 40% from its initial 09:35 reference value.
* **Long Conditions:** Not applicable (PE-only strategy).
* **Short Conditions:** Standard option purchase upon PE momentum trigger.
* **Stop-Loss Rules:** 
  * **Leg Stop-Loss:** 30 points (fixed relative to entry premium).
* **Target Rules:** Overall Strategy Target is OFF.
* **Trailing Rules:** 
  * **Leg Trailing SL:** Trail SL by 10 points for every completed 10 points increase in premium from the entry fill.
* **Overall Strategy Stop-Loss:** Max Loss of Rs 1,000.
* **Overall Trailing Options:** Lock Profit: If strategy profit reaches Rs 1,000, lock a minimum of Rs 500 profit. No further trailing.
* **Exit Conditions:**
  * Leg Stop-Loss hit (30 points relative SL or trailing SL).
  * Strategy Max Loss hit (Rs 1,000).
  * Time-based square-off at `15:15`.
* **Re-entry Rules:** OFF (No re-entry after `09:35` switch is ON).
* **Cooldown Rules:** Not specified.
* **No-Trade Conditions:** Not specified.
* **Risk Limits:** Max Loss Rs 1,000 per session.

---

## 2. Nifty Bull Pulse: Extracted Rules
* **Market/Instrument:** Nifty 50 Index Options (CE only - Bullish).
* **Option Type:** Call Option Buying.
* **DTE (Days to Expiry):** 4 DTE calendar-wise (typically trades on Friday for Thursday weekly expiry).
* **Lots:** 1.
* **Strike Selection:** OTM2 CE (strike 2 intervals above ATM strike; resolved using actual weekly option intervals).
* **Expiry Selection:** Weekly (nearest weekly eligible contract resolved via calendar).
* **Session Window:**
  * **Entry Checks:** Starts at `10:30`.
  * **Exit Checks/Square-off:** Active until `15:00`.
* **Indicators & Parameters:**
  * **Overall Momentum:** Strategy-level premium momentum of 10% (monitors combined strategy premium changes from session start time).
* **Entry Conditions:** Combined strategy premium (value of the single CE leg) increases by 10% from its `10:30` reference price.
* **Long Conditions:** Standard option purchase upon CE overall momentum trigger.
* **Short Conditions:** Not applicable (CE-only strategy).
* **Stop-Loss Rules:**
  * **Leg Stop-Loss:** 20% (percentage relative to entry premium).
* **Target Rules:** Overall Strategy Target is OFF.
* **Trailing Rules:** Leg trailing SL is OFF.
* **Overall Strategy Stop-Loss:** Max Loss of Rs 1,200.
* **Overall Trailing Options:** Lock and Trail (ON):
  * *If profit reaches:* Rs 3,000.
  * *Lock profit:* Rs 2,500.
  * *For every increase in profit by:* Rs 100.
  * *Trail profit by:* Rs 100.
* **Exit Conditions:**
  * Leg Stop-Loss hit (20% relative SL).
  * Strategy Max Loss hit (Rs 1,200).
  * Trailing locked profit hit.
  * Time-based square-off at `15:00`.
* **Re-entry Rules:** OFF.
* **Cooldown/No-Trade/Risk Limits:** Max Loss Rs 1,200 per session.

---

## 3. Confirmed Parameters & Resolutions
1. **Trend Catcher Momentum Entry Rule:** The strategy uses pure leg-wise Simple Momentum (40%) triggered relative to the OTM2 PE premium captured at exactly `09:35:00` (or the first available tick at or after `09:35:00`). No 09:45 Range Breakout is implemented.
2. **Timezone interpretation:** All strategy times are `Asia/Kolkata`. Exported PM/AM anomalies (e.g. `09:34:59 PM` / `03:14:59 PM`) are display defects representing `09:35 AM` and `03:15 PM` IST.
3. **Expiry and Holiday Logic:** Nearest eligible weekly expiry is resolved dynamically from the calendar. DTE is calculated relative to that resolved date. If expiry shifts due to holidays, eligibility days shift automatically. If expiry data is unavailable, strategy returns `EXPIRY_CALENDAR_UNAVAILABLE`.
4. **Capital allocation:** Virtual independent research capital books are assigned to each strategy for A/B testing. For production, a shared atomic capital-reservation ledger handles limits and records `CAPITAL_UNAVAILABLE` while maintaining counterfactual simulations.
5. **Cost Assumptions:** Slippage (1%) and brokerage charges are reclassified as execution-layer/replay assumptions and are not hardcoded inside the pure strategy engines.

---

## 4. Existing Reusable Production Components
* **CompletedCandleContextProvider (`src/strategy_lab/completed_candle.py`):** Feeds completed 1m/3m candles into the strategy adapters, including Spot indices and options contracts.
* **OptionChartCandleFeed (`src/strategy_lab/option_charts.py`):** Ingests live option chain snapshots and resolves weekly option chains.
* **InstitutionalPaperTradingEngine (`src/strategy_lab/paper_engine.py`):** Handles mock order management, trade executions, slippages, and metrics calculations.
* **SharedCorePipeline (`src/strategy_lab/shared_pipeline.py`):** Manages indicators, Supertrend, VWAP, and FVG states.
* **DhanInstrumentMaster (`src/paper_trading/contracts.py`):** Decodes security IDs, trading symbols, lot sizes, and option types.

---

## 5. Proposed Files to Create or Modify
We will create two new strategy packages inside `src/strategy_lab/strategies/`:

### New Files
1. **Trend Catcher Strategy Engine:**
   * `src/strategy_lab/strategies/trend_catcher/__init__.py`
   * `src/strategy_lab/strategies/trend_catcher/strategy.py` (Implements native Trend Catcher logic)
   * `src/strategy_lab/strategies/trend_catcher/adapter.py` (Dual-mode adapter implementing `argus_mode` checks)
   * `src/strategy_lab/strategies/trend_catcher/deployment.py` (Bootstraps the Strategy Lab request)
   * `src/strategy_lab/strategies/trend_catcher/metadata.json` (Strategy registry metadata)
2. **Bull Pulse Strategy Engine:**
   * `src/strategy_lab/strategies/bull_pulse/__init__.py`
   * `src/strategy_lab/strategies/bull_pulse/strategy.py` (Implements native Bull Pulse logic)
   * `src/strategy_lab/strategies/bull_pulse/adapter.py` (Dual-mode adapter implementing `argus_mode` checks)
   * `src/strategy_lab/strategies/bull_pulse/deployment.py` (Bootstraps the Strategy Lab request)
   * `src/strategy_lab/strategies/bull_pulse/metadata.json` (Strategy registry metadata)

### Files to Modify (Register Deployments)
1. `src/strategy_lab/option_deployments.py`: Add Trend Catcher and Bull Pulse option-chart deployment identifiers to `OPTION_CHART_DEPLOYMENTS`.

---

## 6. Shared Strategy Interface
Every strategy adapter must adhere to the `StrategyAdapter` protocol by exposing an `evaluate` method:
```python
class StrategyAdapter(Protocol):
    def evaluate(self, context: Mapping[str, Any]) -> Mapping[str, Any]:
        """Processes the current candle context and returns the strategy directive."""
        ...
```

---

## 7. Configuration Schema
We define a Unified configuration schema for the options buying engines:
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "DualModeOptionsStrategyConfig",
  "type": "object",
  "properties": {
    "trading_mode": { "type": "string", "enum": ["Intraday"] },
    "argus_mode": { "type": "string", "enum": ["OFF", "SHADOW", "FILTER", "SCORING", "FULL"] },
    "dte": { "type": "integer" },
    "option_type": { "type": "string", "enum": ["CE", "PE"] },
    "strike_type": { "type": "string", "enum": ["OTM2", "ATM"] },
    "entry_start_time": { "type": "string", "pattern": "^[0-9]{2}:[0-9]{2}$" },
    "exit_time": { "type": "string", "pattern": "^[0-9]{2}:[0-9]{2}$" },
    "leg_stop_loss_type": { "type": "string", "enum": ["POINTS", "PERCENT"] },
    "leg_stop_loss_value": { "type": "number" },
    "leg_trailing_sl_enabled": { "type": "boolean" },
    "leg_trailing_sl_trigger": { "type": "number" },
    "leg_trailing_sl_step": { "type": "number" },
    "overall_stop_loss_value": { "type": "number" },
    "overall_trailing_enabled": { "type": "boolean" },
    "overall_trailing_trigger": { "type": "number" },
    "overall_trailing_lock": { "type": "number" },
    "overall_trailing_step": { "type": "number" },
    "momentum_type": { "type": "string", "enum": ["SIMPLE", "OVERALL", "NONE"] },
    "momentum_percent": { "type": "number" }
  },
  "required": [
    "trading_mode", "argus_mode", "dte", "option_type", "strike_type",
    "entry_start_time", "exit_time", "leg_stop_loss_type", "leg_stop_loss_value"
  ]
}
```

---

## 8. Dual-Mode Invariants
To maintain rigorous A/B comparison validity:
1. **Identical Candidate Generation:** The native strategy signal generator (and its indicators) is the sole source of trade candidates and must run identically across all modes (`OFF`, `SHADOW`, `FILTER`, `SCORING`, `FULL`).
2. **No Silent Modification in Shadow/Scoring:** 
   * In `OFF` and `SHADOW` modes, the actual executed trade is identical.
   * In `SCORING` mode, the actual executed trade is identical; ARGUS writes scores to the database but does not change the order execution.
3. **No Silent Fallback on Failure:** If ARGUS is offline or returns stale data:
   * `OFF` continues independently.
   * `SHADOW` and `SCORING` execute natively and log `ARGUS_UNAVAILABLE`.
   * `FILTER` and `FULL` modes follow their explicitly configured failure policies (e.g. block entry or notify operator). No silent mutation to `OFF` is permitted.
4. **Shared Signal ID:** All decisions, telemetry, and actual/counterfactual performance records must be linked to the same immutable `signal_id` for that candle.

---

## 9. Deployment Identifiers
To prevent conflicts with existing pullback/breakout strategies, the registered strategy IDs are:
* `TC_NIFTY_PE_1M` / `TC_NIFTY_PE_3M`
* `BP_NIFTY_CE_1M` / `BP_NIFTY_CE_3M`

---

## 10. Startup Architecture
* Strategies are registered in `OPTION_CHART_DEPLOYMENTS` within `src/strategy_lab/option_deployments.py`.
* Registration is decoupled from `app/main.py`; runtimes recover their state from the workspace `logs/strategy_lab/runtimes/<strategy_id>/strategy_state`.
* Runtimes run inside independent daemon thread workers without blocking application startup.

---

## 11. Capital-Reuse Conditions
**Verdict: CONDITIONAL**
The claim of "100% capital reuse" is conditional upon:
1. All positions and pending orders are strictly closed/cancelled intraday, and the broker settles and releases 100% of options premium buying credits before the next strategy's trading day.
2. Market holiday shifts do not cause the execution days (Wednesday and Friday) to overlap.
3. Realized drawdowns do not reduce the account capital below the required margin/premium threshold for the next trade.

---

## 12. Counterfactual Validity Rules
For blocked/delayed signals, simulated execution must remain free of look-ahead bias:
* **Price Source:** Option contract candles (open/high/low/close).
* **Entry Fill:** Close price of the trigger candle. Brokerage and slippage applied at replay layers.
* **Stop/Target Processing:** Subsequent candle high/low evaluated. If a single candle triggers both SL and target, the worst-case (SL) is hit first.
* **Charges:** Standard F&O charges and Rs 20/leg brokerage applied at replay layers.
* **Stale-Data Rejection:** Returns `UNAVAILABLE` if data is stale.
* **Delayed-Entry Expiration:** Delayed signals expire after 5 minutes if conditions do not realign.

---

## 13. Implementation Sequence
* **Prompt A:** Native engines only, with deterministic unit tests.
* **Prompt B:** Replay/backtest parity for native strategies only.
* **Prompt C:** SHADOW adapter and journal schema.
* **Prompt D:** Production paper deployment in OFF + SHADOW only.
* **Prompt E:** Dashboard comparison panel.
* **Prompt F:** Evidence review and ARGUS attribution.
* **Prompt G:** FILTER/SCORING activation only after manual approval.
* *(Note: FULL mode is omitted from the initial sequence and requires a separate review).*
