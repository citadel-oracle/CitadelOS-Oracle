"""Durable Thesis Memory & Prediction Ledger Subsystem (P0.3A Hardened).

Maintains persistent structured market narrative, thesis transition logs,
immutable pre-registered expectation records, and separate evaluation logs
with disk persistence across process restarts and session boundary isolation.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from src.oracle_sol.contracts import (
    DevelopingState,
    ExpectationEvaluationRecord,
    ExpectationRecord,
    ExpectationResult,
    MarketThesisVerdict,
    ThesisState,
)

IST = ZoneInfo("Asia/Kolkata")


class ThesisMemory:
    """Thread-safe and disk-durable thesis store and prediction ledger."""

    def __init__(
        self,
        storage_dir: Optional[str] = None,
        configured_model: str = "gemini-3.8-flash",
    ) -> None:
        self._lock = threading.RLock()
        self.configured_model = configured_model
        self.storage_dir = Path(storage_dir or "data/sol_shadow")
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self._session_date: str = datetime.now(IST).strftime("%Y-%m-%d")
        self.last_analyzed_event_id: Optional[str] = None
        now_utc = datetime.now(IST).isoformat()

        self._active_thesis = ThesisState(
            thesis_id=f"ths_init_{uuid.uuid4().hex[:8]}",
            created_at_utc=now_utc,
            updated_at_utc=now_utc,
            market_verdict=None,
            developing_state=DevelopingState.UNRESOLVED,
            core_narrative="Initializing market reasoning context.",
            what_changed="Engine boot.",
            positioning_story="Baseline observation.",
            oi_story="Awaiting closed-window confirmation.",
            flow_story="Awaiting order flow stream.",
            option_response_story="Awaiting strike quote ladder.",
            call_case="Insufficient evidence.",
            put_case="Insufficient evidence.",
            no_trade_case="Engine initializing; market story unresolved.",
            strongest_contradiction="NONE_OBSERVED",
            active_expectations=[],
            evaluation_history=[],
            data_gaps=["AWAITING_FIRST_SESSION_SNAPSHOT"],
            evidence_references=[],
            configured_model=self.configured_model,
            actually_invoked_model="NONE",
        )
        self._history: List[ThesisState] = []
        self._all_predictions: List[ExpectationRecord] = []
        self._all_evaluations: List[ExpectationEvaluationRecord] = []

        self.thesis_store_status = "OK"
        self.last_successful_write_utc: Optional[str] = None
        self.last_persistence_error: Optional[str] = None

        # Attempt recovery from disk for current session
        self.hydrate_from_disk(self._session_date)

    def _get_thesis_file(self, session_date: str) -> Path:
        return self.storage_dir / f"sol_active_thesis_{session_date}.json"

    def _get_expectations_file(self, session_date: str) -> Path:
        return self.storage_dir / f"sol_expectations_{session_date}.jsonl"

    def _get_evaluations_file(self, session_date: str) -> Path:
        return self.storage_dir / f"sol_evaluations_{session_date}.jsonl"

    def hydrate_from_disk(self, session_date: str) -> bool:
        """Hydrate active thesis and expectations from disk for the given session date."""
        thesis_file = self._get_thesis_file(session_date)
        exp_file = self._get_expectations_file(session_date)
        eval_file = self._get_evaluations_file(session_date)

        if not thesis_file.exists():
            return False

        with self._lock:
            try:
                # 1. Restore active thesis
                with open(thesis_file, "r", encoding="utf-8") as f:
                    t_data = json.load(f)

                # 2. Restore expectations
                restored_exps: List[ExpectationRecord] = []
                if exp_file.exists():
                    with open(exp_file, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.strip():
                                ed = json.loads(line)
                                exp = ExpectationRecord(
                                    expectation_id=ed["expectation_id"],
                                    cycle_id=ed["cycle_id"],
                                    thesis_id=ed["thesis_id"],
                                    created_at_utc=ed["created_at_utc"],
                                    evidence_snapshot_id=ed["evidence_snapshot_id"],
                                    expected_condition=ed["expected_condition"],
                                    invalidation_condition=ed["invalidation_condition"],
                                    evidence_refs=ed.get("evidence_refs", []),
                                    model_identifier=ed.get("model_identifier", self.configured_model),
                                )
                                restored_exps.append(exp)

                # 3. Restore evaluations
                restored_evals: List[ExpectationEvaluationRecord] = []
                if eval_file.exists():
                    with open(eval_file, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.strip():
                                vd = json.loads(line)
                                ev_rec = ExpectationEvaluationRecord(
                                    evaluation_id=vd["evaluation_id"],
                                    expectation_id=vd["expectation_id"],
                                    evaluated_at_utc=vd["evaluated_at_utc"],
                                    actual_event_refs=vd.get("actual_event_refs", []),
                                    result=ExpectationResult(vd["result"]),
                                    evaluation_notes=vd.get("evaluation_notes", ""),
                                    evidence_refs=vd.get("evidence_refs", []),
                                )
                                restored_evals.append(ev_rec)

                invoked_model = t_data.get("actually_invoked_model", "NONE")
                v_val = t_data.get("market_verdict")
                # Historical builds could persist NO_TRADE while no provider had
                # produced a market conclusion.  Preserve the file as evidence,
                # but never hydrate that legacy value as an active verdict.
                legacy_unproven_verdict = bool(v_val and invoked_model == "NONE")
                verdict = (
                    None
                    if legacy_unproven_verdict
                    else MarketThesisVerdict(v_val) if v_val else None
                )
                developing_state = (
                    DevelopingState.UNRESOLVED
                    if legacy_unproven_verdict
                    else DevelopingState(t_data.get("developing_state", "UNRESOLVED"))
                )
                data_gaps = list(t_data.get("data_gaps", []))
                if legacy_unproven_verdict:
                    data_gaps.append("LEGACY_UNPROVEN_INTERPRETATION_REJECTED")

                self._session_date = session_date
                self.last_analyzed_event_id = t_data.get("last_analyzed_event_id")
                active_exp_ids = {
                    str(item.get("expectation_id"))
                    for item in t_data.get("active_expectations", [])
                    if isinstance(item, dict) and item.get("expectation_id")
                }
                active_eval_ids = {
                    str(item.get("evaluation_id"))
                    for item in t_data.get("evaluation_history", [])
                    if isinstance(item, dict) and item.get("evaluation_id")
                }
                self._active_thesis = ThesisState(
                    thesis_id=t_data["thesis_id"],
                    created_at_utc=t_data["created_at_utc"],
                    updated_at_utc=t_data["updated_at_utc"],
                    market_verdict=verdict,
                    developing_state=developing_state,
                    core_narrative=t_data["core_narrative"],
                    what_changed=t_data["what_changed"],
                    positioning_story=t_data["positioning_story"],
                    oi_story=t_data["oi_story"],
                    flow_story=t_data["flow_story"],
                    option_response_story=t_data["option_response_story"],
                    call_case=t_data["call_case"],
                    put_case=t_data["put_case"],
                    no_trade_case=t_data["no_trade_case"],
                    strongest_contradiction=t_data.get("strongest_contradiction", "NONE_OBSERVED"),
                    active_expectations=(
                        [item for item in restored_exps if item.expectation_id in active_exp_ids]
                        if "active_expectations" in t_data
                        else restored_exps
                    ),
                    evaluation_history=(
                        [item for item in restored_evals if item.evaluation_id in active_eval_ids]
                        if "evaluation_history" in t_data
                        else restored_evals
                    ),
                    data_gaps=data_gaps,
                    evidence_references=t_data.get("evidence_references", []),
                    configured_model=t_data.get("configured_model", self.configured_model),
                    actually_invoked_model=invoked_model,
                )
                self._all_predictions = list(restored_exps)
                self._all_evaluations = list(restored_evals)
                return True
            except Exception as exc:
                self.thesis_store_status = "DEGRADED"
                self.last_persistence_error = f"Hydration error: {str(exc)}"
                return False

    def _persist_active_thesis(self) -> bool:
        """Persist current active thesis to JSON file."""
        thesis_file = self._get_thesis_file(self._session_date)
        temp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=thesis_file.parent,
                prefix=f".{thesis_file.name}.",
                suffix=".tmp",
                delete=False,
            ) as f:
                temp_path = Path(f.name)
                payload = self._active_thesis.to_dict()
                payload["last_analyzed_event_id"] = self.last_analyzed_event_id
                json.dump(payload, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, thesis_file)
            temp_path = None
            directory_fd = os.open(thesis_file.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            self.last_successful_write_utc = datetime.now(timezone.utc).isoformat()
            self.thesis_store_status = "OK"
            self.last_persistence_error = None
            return True
        except Exception as exc:
            self.thesis_store_status = "ERROR"
            self.last_persistence_error = f"Thesis write error: {str(exc)}"
            return False
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def get_active_thesis(self) -> ThesisState:
        with self._lock:
            return self._active_thesis

    def get_thesis_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self._lock:
            res = []
            for t in reversed(self._history[-limit:]):
                res.append({
                    "thesis_id": t.thesis_id,
                    "created_at_utc": t.created_at_utc,
                    "market_verdict": t.market_verdict.value if t.market_verdict else None,
                    "developing_state": t.developing_state.value if t.developing_state else "UNRESOLVED",
                    "what_changed": t.what_changed,
                    "core_narrative": t.core_narrative,
                    "strongest_contradiction": t.strongest_contradiction,
                    "actually_invoked_model": t.actually_invoked_model,
                })
            return res

    def get_active_expectations(self) -> List[ExpectationRecord]:
        with self._lock:
            return list(self._active_thesis.active_expectations)

    def commit_reasoning_result(
        self,
        new_thesis: ThesisState,
        *,
        last_analyzed_event_id: Optional[str],
        expectations: List[ExpectationRecord],
        evaluations: List[ExpectationEvaluationRecord],
    ) -> None:
        """Durably commit model artifacts before advancing the event cursor."""

        with self._lock:
            for path, records in (
                (self._get_expectations_file(self._session_date), expectations),
                (self._get_evaluations_file(self._session_date), evaluations),
            ):
                if not records:
                    continue
                try:
                    with open(path, "a", encoding="utf-8") as handle:
                        for record in records:
                            handle.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")
                        handle.flush()
                        os.fsync(handle.fileno())
                except Exception as exc:
                    self.thesis_store_status = "ERROR"
                    self.last_persistence_error = f"Reasoning ledger write error: {str(exc)}"
                    raise RuntimeError(self.last_persistence_error) from exc

            previous_thesis = self._active_thesis
            previous_cursor = self.last_analyzed_event_id
            self._active_thesis = new_thesis
            self.last_analyzed_event_id = last_analyzed_event_id
            if not self._persist_active_thesis():
                self._active_thesis = previous_thesis
                self.last_analyzed_event_id = previous_cursor
                raise RuntimeError(self.last_persistence_error or "Thesis commit failed")
            self._history.append(previous_thesis)
            self._all_predictions.extend(expectations)
            self._all_evaluations.extend(evaluations)

    def update_thesis(self, new_thesis: ThesisState) -> None:
        """Compatibility helper for non-reasoning callers."""
        self.commit_reasoning_result(
            new_thesis,
            last_analyzed_event_id=self.last_analyzed_event_id,
            expectations=[],
            evaluations=[],
        )

    def record_expectation(
        self,
        cycle_id: str,
        evidence_snapshot_id: str,
        condition: str,
        invalidation_if: str,
        evidence_refs: Optional[List[str]] = None,
        model_identifier: Optional[str] = None,
    ) -> ExpectationRecord:
        with self._lock:
            exp_id = f"exp_{len(self._all_predictions) + 1:03d}_{uuid.uuid4().hex[:6]}"
            now_utc = datetime.now(IST).isoformat()
            exp = ExpectationRecord(
                expectation_id=exp_id,
                cycle_id=cycle_id,
                thesis_id=self._active_thesis.thesis_id,
                created_at_utc=now_utc,
                evidence_snapshot_id=evidence_snapshot_id,
                expected_condition=condition,
                invalidation_condition=invalidation_if,
                evidence_refs=evidence_refs or [],
                model_identifier=model_identifier or self.configured_model,
            )
            self._active_thesis.active_expectations.append(exp)
            self._all_predictions.append(exp)
            self._persist_active_thesis()

            # Append to expectations JSONL
            exp_file = self._get_expectations_file(self._session_date)
            try:
                with open(exp_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(exp.to_dict(), sort_keys=True) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
            except Exception as exc:
                self.thesis_store_status = "DEGRADED"
                self.last_persistence_error = f"Expectation write error: {str(exc)}"

            return exp

    def record_evaluation(
        self,
        expectation_id: str,
        result: ExpectationResult,
        actual_event_refs: List[str],
        evaluation_notes: str,
        evidence_refs: Optional[List[str]] = None,
    ) -> ExpectationEvaluationRecord:
        with self._lock:
            eval_id = f"eval_{len(self._all_evaluations) + 1:03d}_{uuid.uuid4().hex[:6]}"
            now_utc = datetime.now(IST).isoformat()
            eval_record = ExpectationEvaluationRecord(
                evaluation_id=eval_id,
                expectation_id=expectation_id,
                evaluated_at_utc=now_utc,
                actual_event_refs=actual_event_refs,
                result=result,
                evaluation_notes=evaluation_notes,
                evidence_refs=evidence_refs or [],
            )
            self._active_thesis.evaluation_history.append(eval_record)
            self._all_evaluations.append(eval_record)
            self._persist_active_thesis()

            # Append to evaluations JSONL
            eval_file = self._get_evaluations_file(self._session_date)
            try:
                with open(eval_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(eval_record.to_dict(), sort_keys=True) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
            except Exception as exc:
                self.thesis_store_status = "DEGRADED"
                self.last_persistence_error = f"Evaluation write error: {str(exc)}"

            return eval_record

    def reset_session(self, session_date: Optional[str] = None) -> None:
        """Reset thesis memory for a new market session date (clearing active state without bleeding prior day)."""
        with self._lock:
            self._session_date = session_date or datetime.now(IST).strftime("%Y-%m-%d")
            self.last_analyzed_event_id = None
            self._history.clear()
            self._all_predictions.clear()
            self._all_evaluations.clear()
            now_utc = datetime.now(IST).isoformat()
            self._active_thesis = ThesisState(
                thesis_id=f"ths_session_reset_{uuid.uuid4().hex[:8]}",
                created_at_utc=now_utc,
                updated_at_utc=now_utc,
                market_verdict=None,
                developing_state=DevelopingState.UNRESOLVED,
                core_narrative=f"Session reset for {self._session_date}. Awaiting new opening context.",
                what_changed="Session boundary.",
                positioning_story="Awaiting opening strikes.",
                oi_story="Awaiting opening OI hydration.",
                flow_story="Awaiting opening flow.",
                option_response_story="Awaiting opening chains.",
                call_case="Session start.",
                put_case="Session start.",
                no_trade_case="Session opening.",
                strongest_contradiction="NONE_OBSERVED",
                configured_model=self.configured_model,
                actually_invoked_model="NONE",
            )
            self._persist_active_thesis()

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "session_date": self._session_date,
                "active_thesis": self._active_thesis.to_dict(),
                "history_count": len(self._history),
                "total_predictions_count": len(self._all_predictions),
                "total_evaluations_count": len(self._all_evaluations),
                "thesis_store_status": self.thesis_store_status,
                "last_successful_write_utc": self.last_successful_write_utc,
                "last_persistence_error": self.last_persistence_error,
            }
