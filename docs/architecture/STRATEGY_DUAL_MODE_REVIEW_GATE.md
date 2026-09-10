# Strategy Dual-Mode Review Gate

**Verdict:** PASS 🟢  
**Implementation Readiness:** READY FOR PROMPT A ✅  

---

## 1. Executive Summary
This document serves as the formal gate review for the onboarding of the **Nifty Trend Catcher** and **Nifty Bull Pulse** strategies under the CitadelOS Strategy Lab framework. 

All previously identified ambiguities (momentum rules, timezone exports, holiday shifts, and capital allocations) have been resolved. The implementation plan is now closed and marked **PASS**, enabling Stage 2 (Prompt A: Native Engines implementation) to proceed.

---

## 2. Source-to-Rule Traceability

### Nifty Trend Catcher Traceability
| Rule Name | Exact Rule / Spec | Source Reference | Interpretation | Implementation Representation | Confidence |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Trading Day** | 1 DTE Bearish | Page 6, 14 | Strategy runs on the day before Nifty Weekly Expiry (usually Wednesday). | Run if calendar days to next weekly expiry = 1. | **CONFIRMED** |
| **DTE Definition** | 1 DTE | Page 14 | Calendar days to next weekly expiry. | `days_to_expiry == 1` | **CONFIRMED** |
| **Entry Window** | 09:35 -> 15:15 | Page 14, 15 | Monitoring for entry begins at 09:35 AM IST and ends at 15:15 PM IST. | `09:35:00 <= current_time <= 15:15:00` | **CONFIRMED** |
| **Forced Exit Time** | 15:15 | Page 14, 15 | Open positions are squared off at 15:15 PM IST. | `if current_time >= 15:15:00: exit_all()` | **CONFIRMED** |
| **Option Type** | Buy PE | Page 14 | Put option buying only. | Option Type = PE | **CONFIRMED** |
| **Strike Selection** | OTM2 | Page 14, 16 | Strike 2 intervals below ATM strike (ATM Strike - 100 points). | `strike = atm_strike - 100` | **CONFIRMED** |
| **Expiry Selection** | Weekly | Page 14, 16 | Closest weekly option expiration contract. | Resolve nearest weekly expiry date. | **CONFIRMED** |
| **Momentum Logic** | Simple Momentum 40% | User Confirmation | Premium triggers 40% above the 09:35:00 reference premium. Range Breakout is OFF. | `premium >= reference_premium * 1.40` | **CONFIRMED** |
| **Entry Trigger** | Premium rises by 40% | User Confirmation | Trigger trade when premium rises 40% from 09:35 reference. | `price >= reference_premium * 1.4` | **CONFIRMED** |
| **Leg Stop-Loss** | 30 pts | Page 14, 16 | Fixed stop-loss of 30 points below fill premium. | `sl = fill_price - 30` | **CONFIRMED** |
| **Overall Stop-Loss** | Max Loss Rs 1,000 | Page 14, 16 | Strategy max loss limit per session. | `if strategy_pnl <= -1000: square_off()` | **CONFIRMED** |
| **Trailing Stop** | Trail 10/10 | Page 14, 16 | Trail SL by 10 points for every 10 points premium increase. | `if premium_gain >= 10: sl += 10` | **CONFIRMED** |
| **Lock-Profit Logic** | Rs 1000 -> lock Rs 500 | Page 14, 16 | Lock Rs 500 profit when strategy profit hits Rs 1,000. | `if strategy_pnl >= 1000: lock_profit(500)` | **CONFIRMED** |
| **Re-entry** | OFF | Page 15 | No re-entry allowed after exit. | Max trades per day = 1. | **CONFIRMED** |
| **Maximum Entries**| 1 | Page 15 | Only 1 position entry allowed per session. | Max trades = 1. | **CONFIRMED** |
| **Quantity** | 1 Lot | Page 16 | Standard lot size of 1. | `qty = 1 * lot_size` | **CONFIRMED** |
| **Capital Allocation**| Confirmed dynamic | User Confirmation | Assigned independent virtual capital books for A/B research. | Passed via configuration. | **CONFIRMED** |
| **Charges/Slippage** | Configurable | User Confirmation | Reclassified as execution/replay layer parameters. | Excluded from pure native engines. | **CONFIRMED** |
| **Holiday Handling**| Dynamic Expiry | User Confirmation | DTE computed dynamically from the calendar to shifts. | Shifts trading day automatically. | **CONFIRMED** |

---

### Nifty Bull Pulse Traceability
| Rule Name | Exact Rule / Spec | Source Reference | Interpretation | Implementation Representation | Confidence |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Trading Day** | 4 DTE Bullish | Page 6, 18 | Strategy runs on the Friday before weekly expiry (usually Wednesday/Thursday). | Run if calendar days to next weekly expiry = 4. | **CONFIRMED** |
| **DTE Definition** | 4 DTE | Page 18 | Calendar days to next weekly expiry. | `days_to_expiry == 4` | **CONFIRMED** |
| **Entry Window** | 10:30 -> 15:00 | Page 18, 19 | Monitoring for entry begins at 10:30 AM IST and ends at 15:00 PM IST. | `10:30:00 <= current_time <= 15:00:00` | **CONFIRMED** |
| **Forced Exit Time** | 15:00 | Page 18, 19 | Open positions are squared off at 15:00 PM IST. | `if current_time >= 15:00:00: exit_all()` | **CONFIRMED** |
| **Option Type** | Buy CE | Page 18 | Call option buying only. | Option Type = CE | **CONFIRMED** |
| **Strike Selection** | OTM2 | Page 18, 20 | Strike 2 intervals above ATM strike (ATM Strike + 100 points). | `strike = atm_strike + 100` | **CONFIRMED** |
| **Expiry Selection** | Weekly | Page 18, 20 | Closest weekly option expiration contract. | Resolve nearest weekly expiry date. | **CONFIRMED** |
| **Momentum Logic** | Momentum 10% up • overall | Page 18, 19 | Strategy waits for overall combined strategy premium to increase by 10% from the 10:30 baseline. | `if current_premium >= base_premium_at_10_30 * 1.10` | **CONFIRMED** |
| **Entry Trigger** | Combined premium rises 10% | Page 18 | Trigger trade once overall premium increases by 10%. | `if premium >= base_premium_at_10_30 * 1.1` | **CONFIRMED** |
| **Leg Stop-Loss** | 20% | Page 18, 20 | Stop-loss is 20% below the option entry fill premium. | `sl = fill_price * 0.8` | **CONFIRMED** |
| **Overall Stop-Loss** | Max Loss Rs 1,200 | Page 18, 20 | Strategy max loss limit per session. | `if strategy_pnl <= -1200: square_off()` | **CONFIRMED** |
| **Trailing Stop** | None | Page 20 | No trailing stop-loss on the option leg. | Trailing SL = OFF | **CONFIRMED** |
| **Lock-Profit Logic** | Lock & trail Rs 3,000 -> lock 2,500 | Page 18, 20 | Lock Rs 2,500 profit when profit hits Rs 3,000; trail by Rs 100 for every Rs 100 increase. | `if profit >= 3000 + k*100: locked_profit = 2500 + k*100` | **CONFIRMED** |
| **Re-entry** | OFF | Page 19 | No re-entry allowed after exit. | Max trades per day = 1. | **CONFIRMED** |
| **Maximum Entries**| 1 | Page 19 | Only 1 position entry allowed per session. | Max trades = 1. | **CONFIRMED** |
| **Quantity** | 1 Lot | Page 20 | Standard lot size of 1. | `qty = 1 * lot_size` | **CONFIRMED** |
| **Capital Allocation**| Confirmed dynamic | User Confirmation | Assigned independent virtual capital books for A/B research. | Passed via configuration. | **CONFIRMED** |
| **Charges/Slippage** | Configurable | User Confirmation | Reclassified as execution/replay layer parameters. | Excluded from pure native engines. | **CONFIRMED** |
| **Holiday Handling**| Dynamic Expiry | User Confirmation | DTE computed dynamically from the calendar to shifts. | Shifts trading day automatically. | **CONFIRMED** |

---

## 3. Unresolved User Confirmations
None. All ambiguities have been resolved and closed.

---

## 4. Corrected Mode Invariants
To ensure A/B comparison integrity, the execution variants satisfy these invariants:
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

## 5. Final Deployment Identifiers
Registered strategy IDs:
* `TC_NIFTY_PE_1M` / `TC_NIFTY_PE_3M`
* `BP_NIFTY_CE_1M` / `BP_NIFTY_CE_3M`

---

## 6. Startup Integration Decision
* Strategies are registered in `OPTION_CHART_DEPLOYMENTS` within `src/strategy_lab/option_deployments.py`.
* Registration is decoupled from `app/main.py`; runtimes recover their state from the workspace `logs/strategy_lab/runtimes/<strategy_id>/strategy_state`.
* Runtimes run inside independent daemon thread workers without blocking application startup.

---

## 7. Capital-Reuse Verdict
**Verdict:** CONDITIONAL ⚠️  
The claim of "100% capital reuse" is only valid under these conditions:
1. All positions and pending orders are strictly closed/cancelled intraday, and the broker settles and releases 100% of options premium buying credits before the next strategy's trading day.
2. Market holiday shifts do not cause the execution days (Wednesday and Friday) to overlap.
3. Realized drawdowns do not reduce the account capital below the required margin/premium threshold for the next trade.

---

## 8. Corrected Test Matrix
* **Unit Tests (Parity):** Verify strike selection math (OTM2 calculation) under holiday calendar shifts.
* **Invariant Verification:** Confirm that `evaluate` outputs identical native signals for `OFF` and `SHADOW` modes under high volatility.
* **Counterfactual State Tests:** Verify that blocked signals successfully simulate their performance until normal exit, recording metrics.
* **Integration Tests:** Verify that unloading `com.citadelos.backend` reverts `FILTER` mode runtimes to `OFF` mode gracefully.

---

## 9. Corrected Implementation Sequence
* **Prompt A:** Native engines only, with deterministic unit tests.
* **Prompt B:** Replay/backtest parity for native strategies only.
* **Prompt C:** SHADOW adapter and journal schema.
* **Prompt D:** Production paper deployment in OFF + SHADOW only.
* **Prompt E:** Dashboard comparison panel.
* **Prompt F:** Evidence review and ARGUS attribution.
* **Prompt G:** FILTER/SCORING activation only after manual approval.
* *(Note: FULL mode is omitted from the initial sequence and requires a separate review).*

---

## 10. Remaining Risks
* **Wide Bid-Ask Spreads:** OTM2 weekly options can suffer from wide spreads during high-volatility sessions; limit orders must enforce SEBI-mandated MPP rules.
* **Counterfactual Slip Bias:** Simulated slippages in counterfactual tracking might deviate from actual execution fills; a conservative 1% premium slip must be modeled.
