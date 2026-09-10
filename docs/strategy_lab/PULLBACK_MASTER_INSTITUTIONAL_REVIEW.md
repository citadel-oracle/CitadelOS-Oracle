# PULLBACK MASTER — Institutional Strategy Lab Review

## Source identity and deployment verdict

- Authoritative source: `/Users/ayushmudgal/Documents/Codex/2026-05-30/files-mentioned-by-the-user-pasted-2/outputs/PULLBACK_MASTER.pine`
- SHA-256: `e75c83b50c09618fb025ad50772d2e13b04100b4b23d6db7fbc25c0638fa63eb`
- Pine version: 5
- Source length: 2,617 lines
- Classification: **UNDERLYING STRATEGY**
- Directionality: long entries only (`strategy.long`); no native short entry
- Strategy Lab status: `REGISTERED_GATED`
- Parity status: `PROVISIONAL_PENDING_PARITY_VALIDATION`
- Production deployment: no
- Development deployment: no
- Broker execution: disabled

The original Pine file was inspected read-only and was not copied, rewritten, or modified. The checked-in adapter accepts only a hash-matching, closed-candle event emitted by this exact Pine source. It does not claim to be a native Python translation of TradingView's state machine.

## Strategy declaration

The source declares `pyramiding=0`, `process_orders_on_close=true`, `calc_on_every_tick=true`, initial capital 100,000, 100% of equity sizing, zero commission, and `max_bars_back=5000`. Those TradingView simulator settings have not been reinterpreted as option quantity or CITADEL risk settings.

## Inputs

The source audit identifies **157** `input.*` declarations. The machine-readable audit returns each complete declaration, type, and source line from `inspect_pine_source()` in `audit.py`.

- Volumetric order blocks and presentation: `obshow`, `oblast`, `obupcs`, `obdncs`, `obshowactivity`, `obactup`, `obactdn`, `obshowbb`, `bbup`, `bbdn`, `obmode`, `len`, `obmiti`, `obtxt`, `showmetric`, `showline`, `overlap`, `wichlap`.
- Fair-value gaps: `fvg_enable`, `what_fvg`, `fvg_num`, `fvg_upcss`, `fvg_dncss`, `fvgbbup`, `fvgbbdn`, `fvg_src`, `fvgthresh`, `fvgoverlap`, `fvgline`, `fvgextend`, `dispraid`, `fvgCandleHighlight`, `fvgBreakawayLength`, `fvgBullCandleColor`, `fvgBearCandleColor`, `fvgBullBreakawayCandleColor`, `fvgBearBreakawayCandleColor`.
- Liquidity sweeps: `vobLiqShow`, `vobLiqUseBuyFilter`, `vobLiqSwingLen`, `vobLiqMode`, `vobLiqBuyLookback`, `vobLiqAfterOBOnly`, `vobLiqSameVOBTouch`, `vobLiqExtend`, `vobLiqMaxBars`, `vobLiqShowBear`, `vobLiqBullColor`, `vobLiqBearColor`, `vobLiqAreaColor`, `vobLiqBearAreaColor`.
- Pullback quality: `vobUsePBTypeFilter`, `vobAllowSweepingPB`, `vobAllowCorrectivePB`, `vobAllowAggressivePB`, `vobAggressiveBodyPct`, `vobAggressiveRangeAtr`.
- HTF/LTF confirmation: `vobUseHTFConfirm`, `vobHTFTF`, `vobHTFMode`, `vobHTFSTLen`, `vobHTFSTFactor`, `vobHTFEMAFast`, `vobHTFEMASlow`, `vobUseLTFConfirm`, `vobLTFTF`, `vobLTFMode`, `vobLTFSTLen`, `vobLTFSTFactor`, `vobLTFEMAFast`, `vobLTFEMASlow`, `vobLTFVolLen`, `vobLTFVolMult`.
- Signals and trade behavior: `vobSignalEnable`, `vobBuyOnClose`, `vobRequireTarget`, `vobEntryMode`, `vobBuyTouchMode`, `vobSellTouchMode`, `vobSLTriggerMode`, `vobRequirePullback`, `vobMinBarsAfterOB`, `vobMoveAwayPoints`, `vobTrailNewBullOB`, `vobUseFVGFilter`, `vobFVGFilterMode`, `vobBrokerSafe`, `vobLatestOnly`, `vobDrawLines`, `vobUseAlerts`, `vobBuyAlertText`, `vobSellAlertText`, `vobSLAlertText`, `vobAlertDetails`, `vobBuyColor`, `vobSLColor`, `vobTargetColor`.
- Exit management: `vobTargetMode`, `vobRRTarget`, `vobUseMinTargetRoom`, `vobMinTargetRoomRR`, `vobUseBearFVGSupplyTarget`, `vobBearFVGTargetLocation`, `vobBearFVGSupplyBuffer`, `vobBearFVGMinGap`, `vobDrawBearFVGSupplyTarget`, `vobUseSupertrendTrail`, `vobSTTrailTF`, `vobSTTrailLen`, `vobSTTrailFactor`, `vobSTTrailOnlyWhenBullish`.
- Profile: `pullbackMode`.
- Visual trade annotation: `vobTradeLabelStyle`, `vobTradeLabelSize`, `vobTradeLabelOffset`, `vobShowTradePrices`, `vobLabelTransparency`, `vobSignalLineWidth`, `vobSignalLineTransparency`.
- Strength, context, and optional confirmations: `vobUseStrengthFilter`, `vobShowStrengthInBuyLabel`, `vobShowStrengthInVOBLabel`, `vobMinStrengthScore`, `vobStrongVolumeSharePct`, `vobRetestVolLen`, `vobRetestVolMult`, `vobZQRelativeVolWeight`, `vobEQRelativeVolWeight`, `vobEQSpreadQualityWeight`, `vobAggressionCloseTopPct`, `vobTinyZonePenaltyPoints`, `vobChopLookback`, `vobChopAtrMult`, `vobContextLookback`, `vobContextAtrBuffer`, `vobFirstTouchBonus`, `vobDeepPiercePenalty`, `vobZQFreshnessWeight`, `vobEQDisplacementBodyPct`, `vobEQDisplacementAtrMult`, `vobEQFVGConfluenceBonus`, `vobEQRepeatedRetestPenalty`, `vobUseOBVScore`, `vobOBVLen`, `vobOBVScoreWeight`, `vobUseMFIScore`, `vobMFILen`, `vobMFIMin`, `vobMFIScoreWeight`, `vobUseVWAPScore`, `vobVWAPScoreWeight`, `vobUseIndexScore`, `vobIndexSymbol`, `vobIndexTF`, `vobIndexMode`, `vobIndexScoreWeight`, `vobRequireEnabledExtraConfirm`.

## Indicators and state

The executable decision path uses market-structure CHoCH/BOS state, bullish and bearish volumetric order blocks, order-block mitigation/breaker state, FVG and breakaway-FVG detection, pivot-confirmed liquidity sweeps, ATR (14 and 200), volume SMA and relative-volume measures, range/chop and context extrema, OBV with EMA, a custom money-flow calculation, VWAP, EMA confirmation, Supertrend confirmation/trailing, candle body/range/close-position quality, target-room RR, and persistent first-touch/retest tracking. The script uses Pine UDTs, persistent `var`/`varip`, mutable arrays, and per-bar drawings; drawings are not decision inputs except where the underlying stored zone state is shared.

## Repainting, lookahead, and `request.security()`

- No explicit future lookahead was found. All five `request.security()` calls specify `barmerge.gaps_off` and `barmerge.lookahead_off`.
- Pivot highs/lows require right-side confirmation (`ta.pivothigh/low(..., swingLen, swingLen)`), so their recognition is delayed rather than future-peeking after confirmation.
- Default `vobBrokerSafe=true` gates BUY/SELL/SL decisions with `barstate.isconfirmed`; order-block mitigation and protective-stop raises are also confirmed-bar operations.
- `calc_on_every_tick=true`, wick-touch rules, TradingView limit-order behavior, `varip`, and the bearish-FVG `strategy.exit(limit=...)` can still produce realtime-vs-historical execution differences. Exact same-bar target/stop priority is not proven.
- HTF values with `lookahead_off` can still change before the higher-timeframe candle closes when optional HTF/index confirmation is enabled. The source does not offset to the last confirmed HTF bar.
- `barcolor(..., offset=-1)` is visual-only. `SFPcords()` contains realtime shifting but is not called by the strategy.

## Session and time filters

V4 and Conservative profiles use exchange-timezone `time()` checks with hard-coded sessions: morning `09:15–12:00`, blocked midday `12:00–14:00`, and V4 afternoon `14:00–15:15`. Other profiles bypass the session filter. No explicit timezone argument or exchange calendar/holiday check is present.

## Entry conditions

The strategy opens only a long `VOB BUY`. It selects the best eligible unused bullish order block. Required gates are: active bullish OB, configured wick/close touch, optional real move-away/retest, optional FVG filter, optional liquidity sweep filter, allowed pullback type, HTF/LTF confirmations, optional OBV/MFI/VWAP/index confirmations, optional strength threshold, profile session permission, OB not invalidated, no higher bullish OB broken on the same candle, target availability when required, minimum target room when enabled, optional close confirmation, and broker-safe confirmed-bar permission. Candidate priority is highest strength score (when filtering) and then the higher OB top; otherwise the higher OB top.

Entry price is the bullish OB top by default, or the candle close when configured. `strategy.entry("VOB BUY", strategy.long)` is issued after state is populated.

## Exit, stop, and target logic

- Target exit: bearish OB, fixed RR, nearest/farthest of bearish OB and RR, or no fixed target/trail-only. Default target mode is nearest active bearish OB bottom. Default fixed-RR value is 4.0 when an RR mode uses it.
- Optional bearish FVG near/inside bearish supply becomes a limit target at the FVG bottom.
- Initial stop: selected bullish OB bottom.
- Stop trigger: wick below the OB by default, or close below when configured. Once trailed to a new higher bullish OB, exit requires confirmed close below the trailed stop.
- Stop may ratchet upward to a newly formed higher bullish OB, Supertrend, break-even, or MFE giveback protection. It never intentionally moves downward.
- Target is evaluated before stop in the explicit `if targetHit ... else if slHit` branch, but TradingView's separate limit-order fill ordering remains a parity item.
- `pyramiding=0`, used-OB tracking, and same-bar action guards prevent intentional repeat entries.

## Option-specific assumptions

The code contains option-buying guidance in tooltips (target-room suggestions and supply-buffer suggestions for NIFTY/BANKNIFTY/SENSEX options), but it never resolves expiry, strike, security ID, option type, lot size, option-chain state, Greeks, IV, or option premium. All decision prices come from the chart symbol. Therefore it is an **Underlying Strategy**, not a Native Option Strategy.

## Unsupported/unproven Pine behavior and parity risks

1. TradingView's exact `strategy.*` fill model with `process_orders_on_close`, same-bar target/stop contact, and the separate FVG limit order.
2. Intrabar persistence (`varip`) and `calc_on_every_tick` transitions versus historical bar replay.
3. `request.security()` bar-merging semantics across arbitrary chart/HTF/LTF combinations, especially incomplete HTF bars.
4. Pine UDT/array mutation and removal ordering across the full market-structure, mitigation, overlap, liquidity, and used-zone state machines.
5. TradingView exchange calendar, session boundary, timezone, DST, and missing-bar behavior.
6. `syminfo.mintick`, volume semantics, and historical feed differences by chart instrument.
7. Strategy sizing and commission assumptions. A 100%-of-equity TradingView position is not mapped to an option lot.
8. Exact alert timing and broker-emulator ordering under realtime wick-touch configurations.

## Deployment and validation boundary

The adapter is loaded only into Strategy Lab and is scheduler-gated. It accepts only a closed, unique event carrying the exact source hash. BUY maps to Strategy Lab BUY; Pine SELL/TARGET/SL actions map to a Strategy Lab SELL while preserving the original Pine action. Missing events produce a truthful WAIT; wrong source hashes fail closed. Default Strategy Lab paper execution remains disabled, so no synthetic fill, quantity, option contract, or P&L is created.

Before live paper validation, exported TradingView fixtures must cover all profiles and critical same-bar order cases; a native state-machine translation must then match those fixtures; symbol/timeframe/feed conventions and session timezone must be frozen; and an isolated paper sizing/fill contract must be defined without reinterpreting TradingView's 100%-equity setting.
