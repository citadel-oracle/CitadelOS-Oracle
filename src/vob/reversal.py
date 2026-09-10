"""Episode-scoped VOB reversal evidence aggregation with multi-timeframe concurrency (1m, 3m, 5m).

All calculations consumed here are canonical outputs owned elsewhere.  This
module only preserves lineage, correlates evidence, and advances research
semantics; it has zero execution influence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from threading import RLock
from time import perf_counter
from typing import Any, Mapping

from .episodes import VobEpisode, episodes_from_ose, episode_from_ose
from .horsepower import HorsepowerStateEngine
from .shadow_ledger import MatchedShadowLedger


class VobReversalState(str, Enum):
    WATCHING = "WATCHING"
    REVERSAL_BUILDING = "REVERSAL_BUILDING"
    REVERSAL_READY = "REVERSAL_READY"
    REVERSAL_FAILED = "REVERSAL_FAILED"


EVIDENCE_FAMILIES = (
    "failed_aggression",
    "order_flow_rotation",
    "futures_response",
    "opposing_option_failure",
    "target_option_wakeup",
    "argus_confirmation",
    "oi_context",
    "premium_velocity",
)


@dataclass(frozen=True, slots=True)
class EvidenceObservation:
    state: str
    revision: str
    event_time: str | None
    receive_time: str | None
    persistence: int
    persistence_state: str
    quality: str
    known: bool


class VobReversalEngine:
    """Multi-timeframe correlation state machine supporting concurrent 1m, 3m, and 5m episodes."""

    def __init__(self, *, ledger: MatchedShadowLedger | None = None) -> None:
        self._lock = RLock()
        self._ledger = ledger or MatchedShadowLedger()
        self._horsepower = HorsepowerStateEngine()
        self._nifty_horsepower: dict[str, Any] = {}
        self._episodes: dict[str, VobEpisode] = {}
        self._evidence: dict[str, dict[str, EvidenceObservation]] = {}
        self._states: dict[str, VobReversalState] = {}
        self._frozen_option_contracts: dict[str, dict[str, Any]] = {}
        self._episode_current_itm_ids: dict[str, dict[str, str]] = {}
        self._episodes_active: dict[str, bool] = {}
        self._revision = 0
        self._last_argus_direction: str | None = None
        self._option_contracts: dict[str, dict[str, Any]] = {}
        self._current_itm1_contracts: dict[str, dict[str, Any]] = {}
        # Exact-security VOBs for the rotating current ITM-1 cards.  These
        # are deliberately separate from the OSE anchor and frozen episodes.
        self._current_itm_vobs: dict[str, dict[str, Any]] = {}
        self._canonical_market: dict[str, Any] = {
            "reference_price": None,
            "strike_interval": None,
            "atm_strike": None,
            "source": "ARGUS_OPTION_CHAIN_RESOLVER",
        }
        self._option_quotes: dict[str, dict[str, Any]] = {}
        self._option_quote_timestamp: str | None = None
        self._compute_ms: list[float] = []

    @property
    def _episode(self) -> VobEpisode | None:
        """Primary active episode for backward-compatibility (5m -> 3m -> 1m)."""
        for tf in ("5m", "3m", "1m"):
            if tf in self._episodes and self._episodes_active.get(tf, False):
                return self._episodes[tf]
        for tf in ("5m", "3m", "1m"):
            if tf in self._episodes:
                return self._episodes[tf]
        return next(iter(self._episodes.values()), None)

    @_episode.setter
    def _episode(self, value: VobEpisode | None) -> None:
        if value is None:
            self._episodes.clear()
            self._episodes_active.clear()
            self._states.clear()
            self._frozen_option_contracts.clear()
            self._episode_current_itm_ids.clear()
        else:
            tf = value.timeframe.lower()
            self._episodes[tf] = value
            self._episodes_active[tf] = True
            self._states[tf] = VobReversalState.WATCHING
            if tf not in self._evidence:
                self._evidence[tf] = {name: self._unknown("UNOBSERVED") for name in EVIDENCE_FAMILIES}

    @property
    def _state(self) -> VobReversalState:
        """Primary active reversal state."""
        ep = self._episode
        if ep is not None:
            tf = ep.timeframe.lower()
            return self._states.get(tf, VobReversalState.WATCHING)
        return VobReversalState.WATCHING

    @_state.setter
    def _state(self, value: VobReversalState) -> None:
        ep = self._episode
        if ep is not None:
            tf = ep.timeframe.lower()
            self._states[tf] = value

    @property
    def _episode_active(self) -> bool:
        return any(self._episodes_active.values())

    @_episode_active.setter
    def _episode_active(self, value: bool) -> None:
        if not value:
            self._episodes_active.clear()
            self._frozen_option_contracts.clear()

    @property
    def episodes(self) -> dict[str, VobEpisode]:
        """All active timeframe episodes keyed by lowercase timeframe (1m, 3m, 5m)."""
        with self._lock:
            return dict(self._episodes)

    @property
    def states(self) -> dict[str, VobReversalState]:
        """All timeframe reversal states."""
        with self._lock:
            return dict(self._states)

    def ingest_ose(self, projection: Mapping[str, Any]) -> None:
        started = perf_counter()
        candidates_by_tf = episodes_from_ose(projection)
        option_contracts = _extract_option_contracts(projection)
        with self._lock:
            self._option_contracts = option_contracts
            # Check invalidation on active episodes
            for tf, ep in list(self._episodes.items()):
                if self._episodes_active.get(tf, False) and _ose_invalidates(projection, ep):
                    self._states[tf] = VobReversalState.REVERSAL_FAILED
                    self._episodes_active[tf] = False
                    self._frozen_option_contracts.pop(tf, None)
                    self._episode_current_itm_ids.pop(tf, None)
                    self._revision += 1

            if not candidates_by_tf:
                self._record_compute(started)
                return

            # Activate or advance each candidate independently
            for tf, candidate in candidates_by_tf.items():
                existing = self._episodes.get(tf)
                is_active = self._episodes_active.get(tf, False)

                if existing is None or not is_active:
                    self._episodes[tf] = candidate
                    self._frozen_option_contracts[tf] = _freeze_option_contract_pair(option_contracts, candidate)
                    current_ids = _contract_pair_ids(self._current_itm1_contracts)
                    if current_ids:
                        self._episode_current_itm_ids[tf] = current_ids
                    self._episodes_active[tf] = True
                    self._evidence[tf] = {name: self._unknown("UNOBSERVED") for name in EVIDENCE_FAMILIES}
                    self._states[tf] = VobReversalState.WATCHING
                    self._revision += 1
                    self._ledger.begin_episode(candidate, recorded_at=candidate.created_at)
                elif existing.episode_id != candidate.episode_id:
                    # An active episode on this timeframe owns its captured contracts until closed
                    continue
                else:
                    if (
                        existing.vob_revision == candidate.vob_revision
                        and existing.vob_state == candidate.vob_state
                        and existing.approach_at == candidate.approach_at
                        and existing.touch_at == candidate.touch_at
                    ):
                        continue
                    self._episodes[tf] = existing.with_authoritative_update(
                        vob_revision=candidate.vob_revision,
                        vob_state=candidate.vob_state,
                        approach_at=candidate.approach_at,
                        touch_at=candidate.touch_at,
                    )
                    self._revision += 1

            self._evaluate_all()
            self._record_compute(started)

    def ingest_flow(self, projection: Any) -> None:
        started = perf_counter()
        value = projection.to_dict() if hasattr(projection, "to_dict") else projection
        if not isinstance(value, Mapping):
            return
        families = _mapping(value.get("family_values"))
        revision = str(value.get("revision") or value.get("snapshot_id") or "UNKNOWN")
        event_time = _text(value.get("generated_at"))
        receive_time = _latency_receive_time(value)
        with self._lock:
            if not self._episodes:
                self._record_compute(started)
                return

            response = _mapping(families.get("RESPONSE_QUALITY"))
            response_state = str(response.get("state") or "UNKNOWN").upper()
            book = _mapping(families.get("BOOK_PRESSURE"))
            pressure = _number(book.get("book_pressure"))
            option = _mapping(families.get("OPTION_CONFIRMATION"))
            canonical_reversal = _mapping(families.get("REVERSAL"))

            for tf, ep in self._episodes.items():
                if not self._episodes_active.get(tf, False):
                    continue
                direction = ep.direction
                failed_state = (
                    "PRESENT"
                    if (direction == "CALL" and response_state == "SELLERS_ABSORBED")
                    or (direction == "PUT" and response_state == "BUYERS_ABSORBED")
                    else "ABSENT" if response else "UNKNOWN"
                )
                self._put_tf(tf, "failed_aggression", failed_state, revision, event_time, receive_time, response)
                self._put_tf(tf, "futures_response", response_state, revision, event_time, receive_time, response)

                flow_state = "UNKNOWN"
                if pressure is not None:
                    supportive = pressure > 0 if direction == "CALL" else pressure < 0
                    flow_state = "SUPPORTIVE" if supportive else "ADVERSE" if pressure != 0 else "NEUTRAL"
                self._put_tf(tf, "order_flow_rotation", flow_state, revision, event_time, receive_time, book)

                target, opposing = _option_rotation_states(direction, option)
                self._put_tf(tf, "target_option_wakeup", target, revision, event_time, receive_time, option)
                self._put_tf(tf, "opposing_option_failure", opposing, revision, event_time, receive_time, option)

                if canonical_reversal:
                    state = str(canonical_reversal.get("state") or "UNKNOWN").upper()
                    self._evidence[tf]["failed_aggression"] = EvidenceObservation(
                        state=self._evidence[tf]["failed_aggression"].state,
                        revision=revision,
                        event_time=event_time,
                        receive_time=receive_time,
                        persistence=1 if state == "PRESSURE_FLIP" else 2 if state == "REVERSAL_FORMING" else 3 if state == "REVERSAL_CONFIRMED" else 0,
                        persistence_state=state,
                        quality=str(value.get("data_quality") or "UNKNOWN"),
                        known=True,
                    )

            self._revision += 1
            self._evaluate_all()
            self._record_compute(started)

    def ingest_argus(self, projection: Mapping[str, Any]) -> None:
        started = perf_counter()
        data = _mapping(projection.get("data"))
        tactical = _mapping(data.get("tactical_edge"))
        prime = _mapping(tactical.get("argus_prime"))
        direction = str(
            tactical.get("direction")
            or prime.get("raw_direction")
            or prime.get("direction")
            or "HOLD"
        ).upper()
        source_time = _text(_mapping(data.get("underlying")).get("fetched_at"))
        option_quotes = _extract_option_quotes(data)
        canonical_market, current_itm1_contracts = _extract_current_itm1(data)
        revision = str(prime.get("snapshot_id") or source_time or "UNKNOWN")
        with self._lock:
            self._option_quotes = option_quotes
            self._option_quote_timestamp = source_time
            self._canonical_market = canonical_market
            self._current_itm1_contracts = current_itm1_contracts
            current_ids = _contract_pair_ids(current_itm1_contracts)
            if current_ids:
                for timeframe, active in self._episodes_active.items():
                    if active and timeframe not in self._episode_current_itm_ids:
                        self._episode_current_itm_ids[timeframe] = current_ids
            # A resolved contract rollover invalidates old-card VOB state. It
            # must be recomputed for the new security id, never relabelled.
            self._current_itm_vobs = {
                side: value
                for side, value in self._current_itm_vobs.items()
                if _text(value.get("security_id"))
                == _text(_mapping(_mapping(current_itm1_contracts.get(side)).get("contract")).get("security_id"))
            }
            if not self._episodes:
                self._last_argus_direction = direction
                self._record_compute(started)
                return

            for tf, ep in self._episodes.items():
                if not self._episodes_active.get(tf, False):
                    continue
                target = ep.direction
                incumbent = "PUT" if target == "CALL" else "CALL"
                if direction == target:
                    state = "CONFIRMS_TARGET"
                elif direction in {"HOLD", "NEUTRAL", "NO CLEAN SIDE"} and self._last_argus_direction == incumbent:
                    state = "INCUMBENT_DETERIORATING"
                elif direction == incumbent:
                    state = "ADVERSE"
                else:
                    state = "UNKNOWN"
                self._put_tf(tf, "argus_confirmation", state, revision, source_time, None, prime)

            self._last_argus_direction = direction
            self._revision += 1
            self._evaluate_all()
            self._record_compute(started)

    def ingest_current_itm_vobs(self, technicals: Mapping[str, Mapping[str, Any]]) -> None:
        """Publish exact-current-ITM VOB output without changing OSE anchors.

        ``technicals`` is produced by ``OptionsStructureEngine.contract_technicals``
        from the canonical Dhan 1m stream.  A result is accepted only when its
        security id still equals the current ARGUS/Dhan resolved contract.
        """
        started = perf_counter()
        with self._lock:
            accepted: dict[str, dict[str, Any]] = {}
            for side in ("CE", "PE"):
                current = _mapping(self._current_itm1_contracts.get(side))
                contract = _mapping(current.get("contract"))
                technical = _mapping(technicals.get(side))
                security_id = _text(contract.get("security_id"))
                if (
                    not security_id
                    or _text(technical.get("security_id")) != security_id
                    or str(technical.get("status") or "").upper() != "AVAILABLE"
                ):
                    continue
                accepted[side] = _current_itm_vob_payload(contract, technical)
                accepted[side]["horsepower"] = self._horsepower.observe(
                    f"{side}:{security_id}", technical
                )
            self._current_itm_vobs = accepted
            self._revision += 1
            self._record_compute(started)

    def ingest_nifty_horsepower(self, technical: Mapping[str, Any]) -> None:
        """Observe prepared NIFTY candles/zones without calculating VOB again."""
        started = perf_counter()
        with self._lock:
            if str(technical.get("status") or "").upper() != "AVAILABLE":
                self._nifty_horsepower = {
                    "instrument": "NIFTY",
                    "status": "UNAVAILABLE",
                    "reason": technical.get("reason") or "CANONICAL_NIFTY_VOB_UNAVAILABLE",
                    "advisory_only": True,
                    "execution_influence": 0,
                }
            else:
                self._nifty_horsepower = self._horsepower.observe("NIFTY", technical)
                self._nifty_horsepower["quality"] = dict(_mapping(technical.get("quality")))
            self._revision += 1
            self._record_compute(started)

    def projection(self) -> dict[str, Any]:
        with self._lock:
            episode = self._episode
            tf = episode.timeframe.lower() if episode else "5m"
            evidence_map = self._evidence.get(tf, {name: self._unknown("UNOBSERVED") for name in EVIDENCE_FAMILIES})
            evidence = {name: asdict(value) for name, value in evidence_map.items()}
            compute = sorted(self._compute_ms[-512:])
            frozen_contracts = self._frozen_option_contracts.get(tf, {})
            is_active = self._episodes_active.get(tf, False)
            frozen_pair_rolled = bool(
                episode and is_active and frozen_contracts
                and (
                    _contract_pair_identity_changed(frozen_contracts, self._option_contracts)
                    or (
                        _contract_pair_is_independent(
                            self._episode_current_itm_ids.get(tf, {}), frozen_contracts
                        )
                        and _contract_pair_identity_changed(
                            self._episode_current_itm_ids.get(tf, {}),
                            self._current_itm1_contracts,
                        )
                    )
                )
            )
            state_val = self._states.get(tf, VobReversalState.WATCHING).value if (episode and is_active) else (self._states.get(tf, VobReversalState.REVERSAL_FAILED).value if episode else "UNAVAILABLE")

            all_episodes_dict = {k: v.to_dict() for k, v in self._episodes.items()}
            all_states_dict = {k: v.value for k, v in self._states.items()}
            all_evidence_dict = {
                k: {fam: asdict(obs) for fam, obs in ev_map.items()}
                for k, ev_map in self._evidence.items()
            }

            return {
                "schema_version": 5,
                "revision": self._revision,
                "episode_id": episode.episode_id if episode else None,
                "direction": episode.direction if episode else None,
                "timeframe": episode.timeframe if episode else None,
                "vob_state": episode.vob_state if episode else "UNAVAILABLE",
                "reversal_state": state_val,
                "episode": episode.to_dict() if episode else None,
                "evidence": evidence,
                "failed_aggression_state": evidence["failed_aggression"]["state"],
                "flow_rotation_state": evidence["order_flow_rotation"]["state"],
                "option_rotation_state": _combined_option_state(evidence),
                "argus_confirmation_state": evidence["argus_confirmation"]["state"],
                "entry_ref": None,
                "sl_ref": None,
                "target_ref": None,
                "authority": {
                    "vob": "OPTIONS_STRUCTURE_ENGINE_V1",
                    "entry_sl_target_one_use_trail": "PULLBACK_MASTER",
                },
                "shadow": self._ledger.current(episode.episode_id) if episode else {},
                "all_shadow_trades": self._ledger.current_all(),
                "episodes_by_timeframe": all_episodes_dict,
                "states_by_timeframe": all_states_dict,
                "evidence_by_timeframe": all_evidence_dict,
                "option_contracts": _option_contract_projection(
                    frozen_contracts if frozen_pair_rolled else self._option_contracts,
                    self._current_itm1_contracts,
                    self._current_itm_vobs,
                    self._option_quotes,
                    self._option_quote_timestamp,
                    frozen=frozen_pair_rolled,
                ),
                "frozen_episode_contracts": {
                    side: {
                        "contract": dict(_mapping(value.get("contract"))),
                        "vob": dict(_mapping(value.get("vob"))),
                        "quality": dict(_mapping(value.get("quality"))),
                    }
                    for side, value in frozen_contracts.items()
                } if episode and frozen_contracts else {},
                "canonical_market": dict(self._canonical_market),
                "current_itm1_contracts": {
                    side: {
                        "contract": dict(_mapping(value.get("contract"))),
                        "quote": dict(_mapping(value.get("quote"))),
                        "vob": dict(_mapping(self._current_itm_vobs.get(side))),
                    }
                    for side, value in self._current_itm1_contracts.items()
                },
                "current_itm_vobs": {
                    side: dict(value) for side, value in self._current_itm_vobs.items()
                },
                "nifty_horsepower": dict(self._nifty_horsepower),
                "contract_pair_status": "FROZEN_EPISODE" if frozen_pair_rolled else "CURRENT_ITM1",
                "quality": _projection_quality(evidence),
                "unknown_fields": [name for name, row in evidence.items() if not row["known"]],
                "performance": _distribution(compute),
                "execution_influence": "ZERO",
                "paper_only": True,
                "live_trading_enabled": False,
                "broker_submission": False,
            }

    def events(self, *, limit: int = 32) -> list[dict[str, Any]]:
        return self._ledger.events(limit=limit)

    def _put_tf(
        self,
        tf: str,
        family: str,
        state: str,
        revision: str,
        event_time: str | None,
        receive_time: str | None,
        source: Mapping[str, Any],
    ) -> None:
        if tf not in self._evidence:
            self._evidence[tf] = {name: self._unknown("UNOBSERVED") for name in EVIDENCE_FAMILIES}
        previous = self._evidence[tf][family]
        persistence = previous.persistence + 1 if previous.state == state and previous.revision != revision else 1
        known = bool(source) and state != "UNKNOWN" and str(source.get("status") or "").upper() != "UNAVAILABLE"
        quality = str(source.get("status") or source.get("confidence") or "UNKNOWN")
        self._evidence[tf][family] = EvidenceObservation(
            state=state,
            revision=revision,
            event_time=event_time,
            receive_time=receive_time,
            persistence=persistence,
            persistence_state=previous.persistence_state,
            quality=quality,
            known=known,
        )

    def _put(
        self,
        family: str,
        state: str,
        revision: str,
        event_time: str | None,
        receive_time: str | None,
        source: Mapping[str, Any],
    ) -> None:
        """Put observation for primary episode (backward-compatibility)."""
        ep = self._episode
        tf = ep.timeframe.lower() if ep else "5m"
        self._put_tf(tf, family, state, revision, event_time, receive_time, source)

    def _evaluate_all(self) -> None:
        for tf in list(self._episodes.keys()):
            self._evaluate_timeframe(tf)

    def _evaluate_timeframe(self, tf: str) -> None:
        ep = self._episodes.get(tf)
        if ep is None or tf not in self._evidence:
            return
        if not self._episodes_active.get(tf, False) or ep.vob_state == "BROKEN":
            self._states[tf] = VobReversalState.REVERSAL_FAILED
            return

        evidence_map = self._evidence[tf]
        failed = evidence_map["failed_aggression"]
        flow = evidence_map["order_flow_rotation"]
        target = evidence_map["target_option_wakeup"]
        opposing = evidence_map["opposing_option_failure"]
        argus = evidence_map["argus_confirmation"]
        current_state = self._states.get(tf, VobReversalState.WATCHING)

        persistent_failure = failed.state == "PRESENT" and failed.persistence_state in {
            "REVERSAL_FORMING", "REVERSAL_CONFIRMED"
        }
        rotation_begun = flow.state == "SUPPORTIVE" or target.state == "WAKEUP"

        if current_state == VobReversalState.REVERSAL_READY and (
            flow.state == "ADVERSE" or target.state == "FAILED" or opposing.state == "STRENGTHENING"
        ):
            self._states[tf] = VobReversalState.REVERSAL_FAILED
        elif persistent_failure and rotation_begun:
            if target.state == "WAKEUP" and argus.state in {"CONFIRMS_TARGET", "INCUMBENT_DETERIORATING"}:
                self._states[tf] = VobReversalState.REVERSAL_READY
            else:
                self._states[tf] = VobReversalState.REVERSAL_BUILDING
        elif flow.state == "ADVERSE" and failed.state == "ABSENT":
            self._states[tf] = VobReversalState.REVERSAL_FAILED
        else:
            self._states[tf] = VobReversalState.WATCHING

        # Evaluate and record independent shadow ledger trades
        current_variants = self._ledger.current(ep.episode_id)
        quote = self._option_quotes.get(ep.contract_identity.security_id) or {}
        ask_or_ltp = _number(quote.get("ask") or quote.get("ltp"))
        bid_or_ltp = _number(quote.get("bid") or quote.get("ltp"))
        initial_sl = ep.zone_bottom if ep.direction == "CALL" else ep.zone_top

        # Track A: VOB_ONLY entry on zone touch
        vob_only_trade = current_variants.get("VOB_ONLY") or {}
        if ep.touch_at and vob_only_trade.get("entry_time") is None and ask_or_ltp is not None:
            self._ledger.record_entry(
                ep,
                "VOB_ONLY",
                entry_time=ep.touch_at or self._option_quote_timestamp or "UNKNOWN",
                entry_ask=ask_or_ltp,
                initial_sl=initial_sl,
                target=None,
                evidence_missing=[],
            )

        # Track B: CONFIRMED_REVERSAL entry on institutional confirmation
        confirmed_trade = current_variants.get("CONFIRMED_REVERSAL") or {}
        if self._states[tf] == VobReversalState.REVERSAL_READY and confirmed_trade.get("entry_time") is None and ask_or_ltp is not None:
            self._ledger.record_entry(
                ep,
                "CONFIRMED_REVERSAL",
                entry_time=self._option_quote_timestamp or "UNKNOWN",
                entry_ask=ask_or_ltp,
                initial_sl=initial_sl,
                target=None,
                evidence_missing=[],
            )

        # Mark active trades with latest bid
        if bid_or_ltp is not None:
            for variant in ("VOB_ONLY", "EARLY_REVERSAL", "CONFIRMED_REVERSAL"):
                trade = current_variants.get(variant) or {}
                if trade.get("entry_time") is not None and trade.get("exit_time") is None:
                    self._ledger.mark(
                        ep,
                        variant,
                        recorded_at=self._option_quote_timestamp or "UNKNOWN",
                        current_bid=bid_or_ltp,
                    )

    def _evaluate(self) -> None:
        self._evaluate_all()

    def _record_compute(self, started: float) -> None:
        self._compute_ms.append((perf_counter() - started) * 1000.0)
        if len(self._compute_ms) > 2048:
            del self._compute_ms[:1024]

    @staticmethod
    def _unknown(reason: str) -> EvidenceObservation:
        return EvidenceObservation("UNKNOWN", "0", None, None, 0, "UNPROVEN", reason, False)


def _option_rotation_states(direction: str, option: Mapping[str, Any]) -> tuple[str, str]:
    required = ("ce_known_buy", "ce_known_sell", "pe_known_buy", "pe_known_sell")
    if not option or any(option.get(name) is None for name in required):
        return "UNKNOWN", "UNKNOWN"
    ce_buy, ce_sell, pe_buy, pe_sell = (int(option[name]) for name in required)
    if direction == "CALL":
        target = "WAKEUP" if ce_buy > ce_sell else "FAILED"
        opposing = "FAILING" if pe_sell >= pe_buy else "STRENGTHENING"
    else:
        target = "WAKEUP" if pe_buy > pe_sell else "FAILED"
        opposing = "FAILING" if ce_sell >= ce_buy else "STRENGTHENING"
    return target, opposing


def _combined_option_state(evidence: Mapping[str, Mapping[str, Any]]) -> str:
    target = evidence["target_option_wakeup"]["state"]
    opposing = evidence["opposing_option_failure"]["state"]
    if target == "WAKEUP" and opposing == "FAILING":
        return "ROTATING"
    if "UNKNOWN" in {target, opposing}:
        return "UNKNOWN"
    if target == "FAILED" or opposing == "STRENGTHENING":
        return "ADVERSE"
    return "MIXED"


def _projection_quality(evidence: Mapping[str, Mapping[str, Any]]) -> str:
    known = sum(bool(row["known"]) for row in evidence.values())
    return "AVAILABLE" if known >= 4 else "PARTIAL" if known else "UNKNOWN"


def _extract_option_contracts(projection: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Retain only OSE-owned identity and existing nearest demand-zone state."""

    result: dict[str, dict[str, Any]] = {}
    contracts = _mapping(projection.get("contracts"))
    for side in ("CE", "PE"):
        state = _mapping(contracts.get(side))
        contract = dict(_mapping(state.get("contract")))
        structures = _mapping(state.get("structures"))
        selected_zone: dict[str, Any] = {}
        selected_timeframe: str | None = None
        for timeframe in ("5m", "3m", "1m"):
            zone = _mapping(_mapping(structures.get(timeframe)).get("demand"))
            if zone and str(zone.get("status") or "").upper() != "BROKEN":
                selected_zone = dict(zone)
                selected_timeframe = timeframe
                break
        result[side] = {
            "contract": contract,
            "vob": {
                "timeframe": selected_timeframe,
                "zone_bottom": _number(selected_zone.get("zone_low")),
                "zone_top": _number(selected_zone.get("zone_high")),
                "state": str(selected_zone.get("status") or "UNKNOWN").upper(),
                "zone_id": _text(selected_zone.get("zone_id")),
                "touch_at": _text(
                    selected_zone.get("last_tested_time")
                    or selected_zone.get("first_tested_time")
                ),
                "role": _text(selected_zone.get("role")),
                "source": "OSE",
                "primary": False,
            },
            "quality": dict(_mapping(state.get("quality"))),
        }
    return result


def _extract_option_quotes(data: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Index the already-canonical ARGUS option window by exact security ID."""

    quotes: dict[str, dict[str, Any]] = {}
    for strike_row in data.get("atm_window") or ():
        row = _mapping(strike_row)
        for side in ("ce", "pe"):
            quote = _mapping(row.get(side))
            security_id = _text(quote.get("security_id"))
            if not security_id:
                continue
            quotes[security_id] = {
                "security_id": security_id,
                "strike": _number(row.get("strike")),
                "option_type": side.upper(),
                "ltp": _number(quote.get("ltp")),
                "bid": _number(quote.get("top_bid_price")),
                "ask": _number(quote.get("top_ask_price")),
                "source": "ARGUS_DHAN_OPTION_CHAIN",
            }
    return quotes


def _extract_current_itm1(
    data: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Project the canonical ARGUS/Dhan ATM mapping without recalculating ATM."""

    underlying = _mapping(data.get("underlying"))
    reference_price = _number(underlying.get("ltp"))
    atm_strike = _number(underlying.get("atm_strike"))
    totals = _mapping(data.get("totals"))
    live_pcr = _mapping(data.get("live_pcr"))
    market = {
        "reference_price": reference_price,
        "strike_interval": None,
        "atm_strike": atm_strike,
        "source": "ARGUS_OPTION_CHAIN_RESOLVER",
        "source_timestamp": _text(
            underlying.get("source_event_time")
            or underlying.get("fetched_at")
            or underlying.get("receipt_timestamp")
        ),
    }
    pcr = _number(totals.get("pcr") or live_pcr.get("oi_pcr"))
    change_pcr = _number(totals.get("change_pcr") or totals.get("day_change_pcr"))
    if pcr is not None:
        market["pcr"] = pcr
    if change_pcr is not None:
        market["change_pcr"] = change_pcr
    if atm_strike is None:
        return market, {}

    rows = [
        _mapping(row)
        for row in data.get("atm_window") or ()
        if isinstance(row, Mapping) and _number(row.get("strike")) is not None
    ]
    ce_row = max(
        (row for row in rows if (_number(row.get("strike")) or atm_strike) < atm_strike),
        key=lambda row: _number(row.get("strike")) or float("-inf"),
        default=None,
    )
    pe_row = min(
        (row for row in rows if (_number(row.get("strike")) or atm_strike) > atm_strike),
        key=lambda row: _number(row.get("strike")) or float("inf"),
        default=None,
    )
    if ce_row is None or pe_row is None:
        return market, {}

    ce_strike = _number(ce_row.get("strike"))
    pe_strike = _number(pe_row.get("strike"))
    if ce_strike is None or pe_strike is None:
        return market, {}
    ce_delta = atm_strike - ce_strike
    pe_delta = pe_strike - atm_strike
    if ce_delta <= 0 or pe_delta <= 0 or abs(ce_delta - pe_delta) > 0.001:
        return market, {}
    market["strike_interval"] = ce_delta

    expiry = _text(underlying.get("expiry"))
    result: dict[str, dict[str, Any]] = {}
    for side, row, strike in (("CE", ce_row, ce_strike), ("PE", pe_row, pe_strike)):
        leg = _mapping(row.get(side.lower()))
        security_id = _text(leg.get("security_id"))
        if not security_id:
            continue
        ltp = _number(leg.get("ltp"))
        day_price_change = _number(leg.get("day_price_change") or leg.get("price_change"))
        previous_close = _number(leg.get("previous_close") or leg.get("baseline_ltp"))
        day_change_pct = None
        if day_price_change is not None and previous_close is not None and previous_close > 0:
            day_change_pct = round((day_price_change / previous_close) * 100.0, 2)
        elif ltp is not None and previous_close is not None and previous_close > 0:
            day_change_pct = round(((ltp - previous_close) / previous_close) * 100.0, 2)

        oi = _number(leg.get("oi"))
        change_oi = _number(leg.get("day_change_oi") or leg.get("change_oi") or leg.get("intraday_change_oi"))
        positioning = _text(leg.get("day_positioning") or leg.get("positioning") or leg.get("day_activity") or leg.get("activity"))

        quote = {
            "security_id": security_id,
            "strike": strike,
            "option_type": side,
            "ltp": ltp,
            "bid": _number(leg.get("top_bid_price")),
            "ask": _number(leg.get("top_ask_price")),
            "source": "ARGUS_DHAN_OPTION_CHAIN",
            "timestamp": market["source_timestamp"],
        }
        for field_name, value in {
            "day_price_change": day_price_change,
            "previous_close": previous_close,
            "day_change_pct": day_change_pct,
            "oi": oi,
            "change_oi": change_oi,
            "positioning": positioning,
        }.items():
            if value is not None:
                quote[field_name] = value
        result[side] = {
            "contract": {
                "security_id": security_id,
                "strike": strike,
                "option_type": side,
                "expiry": expiry,
                "source": "ARGUS_OPTION_CHAIN_RESOLVER",
            },
            "quote": quote,
        }
    return market, result


def _freeze_option_contract_pair(
    contracts: Mapping[str, Mapping[str, Any]],
    episode: VobEpisode,
) -> dict[str, dict[str, Any]]:
    """Freeze the existing OSE CE/PE pair without selecting or recalculating it."""

    result: dict[str, dict[str, Any]] = {}
    target_side = episode.contract_identity.option_type
    for side in ("CE", "PE"):
        current = _mapping(contracts.get(side))
        contract = dict(_mapping(current.get("contract")))
        vob = dict(_mapping(current.get("vob")))
        if side == target_side:
            contract = asdict(episode.contract_identity)
            vob = {
                "timeframe": episode.timeframe,
                "zone_bottom": episode.zone_bottom,
                "zone_top": episode.zone_top,
                "state": episode.vob_state,
                "zone_id": episode.source_zone_id,
                "touch_at": episode.touch_at,
                "role": episode.primary_role,
                "source": "OSE",
                "primary": True,
            }
        result[side] = {
            "contract": contract,
            "vob": vob,
            "quality": dict(_mapping(current.get("quality"))),
        }
    return result


def _contract_pair_identity_changed(
    frozen: Mapping[str, Mapping[str, Any]],
    current: Mapping[str, Mapping[str, Any]],
) -> bool:
    """An active episode freezes only after its OSE pair has actually rolled."""

    for side in ("CE", "PE"):
        frozen_id = _contract_security_id(frozen.get(side))
        current_id = _contract_security_id(current.get(side))
        if frozen_id and current_id and frozen_id != current_id:
            return True
    return False


def _contract_pair_ids(
    contracts: Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for side in ("CE", "PE"):
        security_id = _text(
            _mapping(_mapping(contracts.get(side)).get("contract")).get("security_id")
        )
        if security_id:
            result[side] = security_id
    return result


def _contract_pair_is_independent(
    current: Mapping[str, Any], frozen: Mapping[str, Mapping[str, Any]],
) -> bool:
    """The OSE anchor may be a distinct episode pair from current ITM cards."""

    pairs = [
        (_contract_security_id(current.get(side)), _contract_security_id(frozen.get(side)))
        for side in ("CE", "PE")
    ]
    return all(current_id and frozen_id and current_id != frozen_id for current_id, frozen_id in pairs)


def _contract_security_id(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return _text(value)
    mapped = _mapping(value)
    contract = _mapping(mapped.get("contract"))
    return _text(contract.get("security_id") or mapped.get("security_id"))


def _current_itm_vob_payload(
    contract: Mapping[str, Any], technical: Mapping[str, Any],
) -> dict[str, Any]:
    """Select a display zone from an exact contract's canonical VOB lanes."""
    structures = _mapping(technical.get("vob_timeframes"))
    timeframes: dict[str, dict[str, Any]] = {}
    primary_zone: Mapping[str, Any] = {}
    primary_timeframe: str | None = None
    for timeframe in ("1m", "3m", "5m"):
        structure = _mapping(structures.get(timeframe))
        demand = _mapping(structure.get("demand"))
        supply = _mapping(structure.get("supply"))
        timeframes[timeframe] = {
            "demand": dict(demand) if demand else None,
            "supply": dict(supply) if supply else None,
            "state": structure.get("state"),
            "evaluated_through": structure.get("evaluated_through"),
            "completed_bucket": bool(structure.get("completed_bucket")),
            "latest_finalized_bar": dict(_mapping(structure.get("latest_finalized_bar"))) or None,
            "zone_ladder": [dict(zone) for zone in structure.get("zone_ladder") or [] if isinstance(zone, Mapping)],
        }
    for timeframe in ("5m", "3m", "1m"):
        zone = _mapping(timeframes[timeframe].get("demand"))
        if zone and str(zone.get("status") or "").upper() != "BROKEN":
            primary_zone, primary_timeframe = zone, timeframe
            break
    return {
        "security_id": _text(contract.get("security_id")),
        "timeframe": primary_timeframe,
        "zone_bottom": _number(primary_zone.get("zone_low")),
        "zone_top": _number(primary_zone.get("zone_high")),
        "state": str(primary_zone.get("status") or "NO_ACTIVE_VOB").upper(),
        "zone_id": _text(primary_zone.get("zone_id")),
        "touch_at": _text(
            primary_zone.get("last_tested_time") or primary_zone.get("first_tested_time")
        ),
        "role": _text(primary_zone.get("role")),
        "evaluated_at": _text(technical.get("source_timestamp")),
        "source": "CURRENT_ITM_EXACT_SECURITY_ID_CANONICAL_VOB",
        "primary": True,
        "timeframes": timeframes,
    }


def _option_contract_projection(
    contracts: Mapping[str, Mapping[str, Any]],
    current_itm1_contracts: Mapping[str, Mapping[str, Any]],
    current_itm_vobs: Mapping[str, Mapping[str, Any]],
    quotes: Mapping[str, Mapping[str, Any]],
    quote_timestamp: str | None,
    *,
    frozen: bool = False,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for side in ("CE", "PE"):
        current = _mapping(current_itm1_contracts.get(side))
        selected = _mapping(contracts.get(side))
        selected_contract = _mapping(selected.get("contract"))
        contract = (
            dict(selected_contract)
            if frozen and selected_contract
            else dict(_mapping(current.get("contract")))
        )
        same_selected_identity = (
            _text(selected_contract.get("security_id")) is not None
            and _text(selected_contract.get("security_id")) == _text(contract.get("security_id"))
        )
        current_vob = _mapping(current_itm_vobs.get(side))
        same_current_identity = (
            _text(current_vob.get("security_id")) is not None
            and _text(current_vob.get("security_id")) == _text(contract.get("security_id"))
        )
        # Current ITM data wins only when it was evaluated for this exact
        # security. OSE may fill the card only when it already owns that same
        # contract; an anchor is never relabelled as current ITM.
        vob = (
            dict(current_vob)
            if frozen and same_current_identity
            else dict(_mapping(selected.get("vob")))
            if frozen
            else
            dict(current_vob)
            if same_current_identity
            else dict(_mapping(selected.get("vob"))) if same_selected_identity else {}
        )
        security_id = _text(contract.get("security_id"))
        quote = dict(_mapping(current.get("quote"))) if not frozen else {}
        if not quote and security_id:
            quote = dict(_mapping(quotes.get(security_id)))
        quote["timestamp"] = quote.get("timestamp") or quote_timestamp
        quote["freshness"] = str(
            _mapping(current.get("quality")).get("freshness")
            or _mapping(selected.get("quality")).get("freshness")
            or "UNKNOWN"
        ).upper()
        distance = _distance_to_zone(
            _number(quote.get("ltp")),
            _number(vob.get("zone_bottom")),
            _number(vob.get("zone_top")),
        )
        result[side] = {
            "contract": contract,
            "contract_status": "FROZEN_EPISODE" if frozen and security_id else "CURRENT_ITM1" if security_id else "UNKNOWN",
            "quote": quote,
            "vob": vob,
            "distance": distance,
        }
    return result


def _distance_to_zone(
    price: float | None,
    zone_bottom: float | None,
    zone_top: float | None,
) -> dict[str, Any]:
    if price is None or zone_bottom is None or zone_top is None:
        return {
            "distance_to_zone_points": None,
            "distance_to_zone_pct": None,
            "inside_zone": None,
            "nearest_zone_boundary": None,
            "relation": "UNKNOWN",
        }
    low, high = sorted((zone_bottom, zone_top))
    inside = low <= price <= high
    if inside:
        nearest = low if abs(price - low) <= abs(high - price) else high
        points = 0.0
        relation = "TOUCHING" if price == low or price == high else "INSIDE"
    elif price < low:
        nearest = low
        points = low - price
        relation = "BELOW"
    else:
        nearest = high
        points = price - high
        relation = "ABOVE"
    return {
        "distance_to_zone_points": round(points, 6),
        "distance_to_zone_pct": round(points / price * 100.0, 6) if price > 0 else None,
        "inside_zone": inside,
        "nearest_zone_boundary": nearest,
        "relation": relation,
    }


def _ose_invalidates(projection: Mapping[str, Any], episode: VobEpisode) -> bool:
    contracts = _mapping(projection.get("contracts"))
    side = "CE" if episode.direction == "CALL" else "PE"
    structures = _mapping(_mapping(contracts.get(side)).get("structures"))
    structure = _mapping(structures.get(episode.timeframe))
    for zone in structure.get("recently_broken") or []:
        if isinstance(zone, Mapping) and str(zone.get("zone_id")) == episode.source_zone_id:
            return True
    return False


def _distribution(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "p50": None, "p95": None, "p99": None, "max": None}
    def pick(value: float) -> float:
        return round(values[min(len(values) - 1, int((len(values) - 1) * value))], 4)
    return {"count": len(values), "p50": pick(.5), "p95": pick(.95), "p99": pick(.99), "max": round(values[-1], 4)}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    result = str(value).strip() if value is not None else ""
    return result or None


def _latency_receive_time(value: Mapping[str, Any]) -> str | None:
    timestamp = _mapping(value.get("latency_timestamps")).get("t0_packet_receive_ns")
    return str(timestamp) if timestamp is not None else None
