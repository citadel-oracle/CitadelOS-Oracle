"""Safe External Context Contract, Provenance & Storage Layer for CITADEL (Gemini Spark).

Consumes structured external market context from Gemini Spark.
Strict Rule: CITADEL NEVER calls a claim VERIFIED or CONFLICTED based on hard-coded keywords,
string matching, or self-declared upstream status.
In the absence of an authentic retrieved authoritative verification record, every live claim
remains strictly UNVERIFIED (or SOURCE_UNAVAILABLE), and the system truthfully reports that
automated source-verification is NOT CONNECTED.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time as datetime_time, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# Hard Prohibited Words in External Context to prevent backdoored trading advice/bias
PROHIBITED_TRADING_WORDS: Set[str] = {
    "call",
    "put",
    "calls",
    "puts",
    "bullish",
    "bearish",
    "buy",
    "sell",
    "long",
    "short",
    "target",
    "targets",
    "stoploss",
    "support",
    "resistance",
    "probability",
    "confidence score",
    "expected direction",
    "overweight",
    "underweight",
}

# Forbidden broker/account keys
PROHIBITED_BROKER_KEYS: Set[str] = {
    "dhan_token",
    "access_token",
    "client_id",
    "account_id",
    "password",
    "secret",
    "api_key",
    "place_order",
    "modify_order",
    "cancel_order",
    "order_type",
    "quantity",
    "trade_id",
}


class FactStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    DEVELOPING = "DEVELOPING"
    UNCONFIRMED = "UNCONFIRMED"


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    CONFLICTED = "CONFLICTED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SYNTHETIC_TEST = "SYNTHETIC_TEST"


class ExternalContextStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID = "INVALID"
    STALE = "STALE"


class SourceVerificationConnectorStatus(str, Enum):
    NOT_CONNECTED = "NOT_CONNECTED"
    CONNECTED = "CONNECTED"


class RadarTimeClassification(str, Enum):
    TODAY = "TODAY"
    STALE = "STALE"
    FUTURE = "FUTURE"
    TIMESTAMP_UNKNOWN = "TIMESTAMP_UNKNOWN"


RADAR_INSTRUMENT_SPECS: Dict[str, Tuple[str, str]] = {
    "S&P 500 Futures": ("US", "FUTURES"),
    "Dow Jones Futures": ("US", "FUTURES"),
    "Nasdaq Futures": ("US", "FUTURES"),
    "Nikkei 225": ("ASIA", "CASH_INDEX"),
    "Hang Seng": ("ASIA", "CASH_INDEX"),
    "Kospi": ("ASIA", "CASH_INDEX"),
    "US 10Y Yield": ("RATES_FX", "RATE"),
    "Dollar Index (DXY)": ("RATES_FX", "FX_INDEX"),
    "USD/INR": ("RATES_FX", "FX_SPOT"),
    "CBOE VIX": ("VOLATILITY", "VOLATILITY_INDEX"),
    "India VIX": ("VOLATILITY", "VOLATILITY_INDEX"),
    "Brent Crude": ("ENERGY", "ENERGY_BENCHMARK"),
    "WTI Crude": ("ENERGY", "ENERGY_BENCHMARK"),
    "GIFT Nifty": ("INDIA_GIFT", "FUTURES"),
}

RADAR_SECTION_LABELS: Tuple[Tuple[str, str], ...] = (
    ("US", "US"),
    ("ASIA", "ASIA"),
    ("RATES_FX", "RATES / FX"),
    ("VOLATILITY", "VOLATILITY"),
    ("ENERGY", "ENERGY"),
    ("INDIA_GIFT", "INDIA / GIFT"),
)


@dataclass(frozen=True)
class AuthoritativeVerificationRecord:
    """Immutable record created when authoritative evidence is independently retrieved and compared."""
    authoritative_source_id: str
    retrieved_at_utc: str
    source_url_or_ref: str
    claim_field: str
    spark_value: str
    authoritative_value: str
    match_verdict: str  # "MATCH" | "DISCREPANCY" | "UNVERIFIABLE"
    evidence_hash: str
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExternalFactItem:
    """A discrete external event or observation with independent CITADEL verification provenance."""
    fact_id: str
    title: str
    factual_summary: str
    status: str = FactStatus.CONFIRMED.value
    event_time_utc: Optional[str] = None
    event_time_ist: Optional[str] = None
    observed_or_published_at: Optional[str] = None
    source_name: str = "UNKNOWN"
    source_url: Optional[str] = None
    source_timestamp: Optional[str] = None
    relevance_note: Optional[str] = None
    upstream_verification_status: str = "UNVERIFIED"  # What Spark self-declared (NOT trusted)
    verification_status: str = VerificationStatus.UNVERIFIED.value  # CITADEL's authoritative verdict
    verification_record: Optional[Dict[str, Any]] = None  # Immutable audit record of comparison
    authoritative_source: Optional[str] = None
    authoritative_value: Optional[str] = None
    conflict_detail: Optional[Dict[str, Any]] = None
    validation_notes: Optional[str] = None
    radar_category: Optional[str] = None
    instrument_label: Optional[str] = None
    instrument_kind: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExternalContextPayload:
    """Canonical external context packet prepared by Spark and validated by CITADEL."""
    external_context_id: str
    market_session_date: str
    generated_at_utc: str
    generated_at_ist: str
    received_at_utc: str
    received_at_ist: str
    provider: str
    source_type: str
    scheduled_events: List[ExternalFactItem] = field(default_factory=list)
    breaking_events: List[ExternalFactItem] = field(default_factory=list)
    overnight_context: List[ExternalFactItem] = field(default_factory=list)
    index_specific_events: List[ExternalFactItem] = field(default_factory=list)
    global_context: List[ExternalFactItem] = field(default_factory=list)
    data_gaps: List[str] = field(default_factory=list)
    sources: List[Dict[str, Any]] = field(default_factory=list)
    is_test_fixture: bool = False
    provenance_hash: str = ""
    schema_version: str = "3.0.0-truthful-provenance"

    def all_items(self) -> List[ExternalFactItem]:
        return (
            self.scheduled_events
            + self.breaking_events
            + self.overnight_context
            + self.index_specific_events
            + self.global_context
        )

    def total_items_count(self) -> int:
        return len(self.all_items())

    def verified_items(self) -> List[ExternalFactItem]:
        return [itm for itm in self.all_items() if itm.verification_status == VerificationStatus.VERIFIED.value]

    def unverified_items(self) -> List[ExternalFactItem]:
        return [itm for itm in self.all_items() if itm.verification_status == VerificationStatus.UNVERIFIED.value]

    def conflicted_items(self) -> List[ExternalFactItem]:
        return [itm for itm in self.all_items() if itm.verification_status == VerificationStatus.CONFLICTED.value]

    def verification_status_counts(self) -> Dict[str, int]:
        counts = {status.value: 0 for status in VerificationStatus}
        counts["OTHER"] = 0
        for item in self.all_items():
            if item.verification_status in counts:
                counts[item.verification_status] += 1
            else:
                counts["OTHER"] += 1
        return counts

    def genuinely_verified_sources_count(self) -> int:
        """Count distinct authoritative sources among genuinely verified items."""
        verified = self.verified_items()
        sources = {itm.authoritative_source or itm.source_name for itm in verified if itm.source_name != "UNKNOWN"}
        return len(sources)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "external_context_id": self.external_context_id,
            "market_session_date": self.market_session_date,
            "generated_at_utc": self.generated_at_utc,
            "generated_at_ist": self.generated_at_ist,
            "received_at_utc": self.received_at_utc,
            "received_at_ist": self.received_at_ist,
            "provider": self.provider,
            "source_type": self.source_type,
            "scheduled_events": [e.to_dict() for e in self.scheduled_events],
            "breaking_events": [e.to_dict() for e in self.breaking_events],
            "overnight_context": [e.to_dict() for e in self.overnight_context],
            "index_specific_events": [e.to_dict() for e in self.index_specific_events],
            "global_context": [e.to_dict() for e in self.global_context],
            "data_gaps": list(self.data_gaps),
            "sources": list(self.sources),
            "is_test_fixture": self.is_test_fixture,
            "provenance_hash": self.provenance_hash,
            "schema_version": self.schema_version,
            "verification_summary": {
                "total_items": self.total_items_count(),
                "verified_count": len(self.verified_items()),
                "unverified_count": len(self.unverified_items()),
                "conflicted_count": len(self.conflicted_items()),
                "genuinely_verified_sources_count": self.genuinely_verified_sources_count(),
                "source_verification_status": (
                    SourceVerificationConnectorStatus.CONNECTED.value
                    if len(self.verified_items()) > 0 or len(self.conflicted_items()) > 0
                    else SourceVerificationConnectorStatus.NOT_CONNECTED.value
                ),
                "status_counts": self.verification_status_counts(),
            }
        }

    def to_projection_dict(self) -> Dict[str, Any]:
        """Project strictly separated verified, unverified, and conflicted evidence into Gemini packet."""
        return {
            "external_context_id": self.external_context_id,
            "market_session_date": self.market_session_date,
            "generated_at_ist": self.generated_at_ist,
            "provider": self.provider,
            "source_type": self.source_type,
            "is_test_fixture": self.is_test_fixture,
            
            # Explicitly separated streams for model reasoning
            "verified_external_context": [e.to_dict() for e in self.verified_items()],
            "unverified_external_context": [e.to_dict() for e in self.unverified_items()],
            "conflicted_external_context": [e.to_dict() for e in self.conflicted_items()],
            "source_unavailable_external_context": [
                e.to_dict() for e in self.all_items()
                if e.verification_status == VerificationStatus.SOURCE_UNAVAILABLE.value
            ],
            "synthetic_test_external_context": [
                e.to_dict() for e in self.all_items()
                if e.verification_status == VerificationStatus.SYNTHETIC_TEST.value
            ],
            
            "verification_summary": {
                "total_items": self.total_items_count(),
                "verified_items_count": len(self.verified_items()),
                "unverified_items_count": len(self.unverified_items()),
                "conflicted_items_count": len(self.conflicted_items()),
                "genuinely_verified_sources_count": self.genuinely_verified_sources_count(),
                "source_verification_status": (
                    SourceVerificationConnectorStatus.CONNECTED.value
                    if len(self.verified_items()) > 0 or len(self.conflicted_items()) > 0
                    else SourceVerificationConnectorStatus.NOT_CONNECTED.value
                ),
                "status_counts": self.verification_status_counts(),
            },
            "data_gaps": list(self.data_gaps),
            "sources": list(self.sources),
            "provenance_hash": self.provenance_hash,
        }


# ── Authoritative Verification Evaluator (NO Hard-Coded Keyword Matching) ──

class CitadelFactVerificationEngine:
    """Evaluates fact items strictly against authentic retrieved verification records.
    
    NO hard-coded strings or heuristic keyword rules promote claims to VERIFIED.
    """

    @staticmethod
    def verify_fact_item(
        item_dict: Dict[str, Any],
        is_test_fixture: bool = False
    ) -> Tuple[str, Optional[str], Optional[str], Optional[Dict[str, Any]], Optional[Dict[str, Any]], str]:
        """Evaluate a single fact item against authoritative verification records.
        
        Returns:
            (verification_status, authoritative_source, authoritative_value, conflict_detail, verification_record, validation_notes)
        """
        source_name = str(item_dict.get("source_name", "")).strip()

        # 1. Non-test live payloads: external payload verification records are UNTRUSTED
        # Real verification must come from a trusted CITADEL-internal source connector (not connected yet).
        if not is_test_fixture:
            if not source_name or source_name.upper() in {"UNKNOWN", "NONE", ""}:
                return (
                    VerificationStatus.SOURCE_UNAVAILABLE.value,
                    None,
                    None,
                    None,
                    None,
                    "No verifiable source name provided in payload."
                )
            return (
                VerificationStatus.UNVERIFIED.value,
                None,
                None,
                None,
                None,
                "Untrusted external payload verification records are rejected. "
                "Automated independent source-verification connector is NOT CONNECTED. Claim remains UNVERIFIED."
            )

        # 2. Test Fixture Path (Permitted strictly inside test suites)
        raw_rec = item_dict.get("verification_record")
        if isinstance(raw_rec, dict) and raw_rec.get("evidence_hash") and raw_rec.get("authoritative_source_id"):
            auth_source = str(raw_rec.get("authoritative_source_id"))
            auth_val = str(raw_rec.get("authoritative_value"))
            spark_val = str(raw_rec.get("spark_value", item_dict.get("event_time_ist") or ""))
            match_verdict = str(raw_rec.get("match_verdict", "UNVERIFIABLE")).upper()
            evidence_hash = str(raw_rec.get("evidence_hash"))
            notes = raw_rec.get("notes")

            if match_verdict == "MATCH":
                return (
                    VerificationStatus.VERIFIED.value,
                    auth_source,
                    auth_val,
                    None,
                    raw_rec,
                    f"Test Fixture verified against mock authoritative record from {auth_source} (hash: {evidence_hash[:8]})."
                )
            elif match_verdict == "DISCREPANCY":
                conflict_detail = {
                    "spark_claim": spark_val,
                    "authoritative_value": auth_val,
                    "authoritative_source": auth_source,
                    "conflict_type": raw_rec.get("conflict_type", "VALUE_DISCREPANCY"),
                    "evidence_hash": evidence_hash,
                    "retrieved_at_utc": raw_rec.get("retrieved_at_utc"),
                    "source_url_or_ref": raw_rec.get("source_url_or_ref"),
                    "reason": notes or f"Authoritative record from {auth_source} differs from Spark claim.",
                }
                return (
                    VerificationStatus.CONFLICTED.value,
                    auth_source,
                    auth_val,
                    conflict_detail,
                    raw_rec,
                    f"Test Fixture discrepancy confirmed by mock authoritative evidence from {auth_source}."
                )

        return (
            VerificationStatus.SYNTHETIC_TEST.value,
            "TEST_FIXTURE",
            None,
            None,
            None,
            "Synthetic test fixture - exempt from live source verification."
        )


def _check_text_for_prohibited_terms(text: Optional[str], field_name: str, errors: List[str]) -> None:
    if not text:
        return
    lower_text = text.lower()
    # 1. Multi-word prohibited phrases
    for phrase in ["confidence score", "expected direction"]:
        if phrase in lower_text:
            errors.append(
                f"Prohibited trading phrase '{phrase}' detected in {field_name}. "
                "External context must contain factual observations only, not trading signals or directional bias."
            )

    # 2. Single token checks
    words = set(re.findall(r"\b[a-zA-Z_\-]+\b", lower_text))
    intersection = words.intersection(PROHIBITED_TRADING_WORDS)
    if intersection:
        errors.append(
            f"Prohibited trading term(s) {sorted(list(intersection))} detected in {field_name}. "
            "External context must contain factual observations only, not trading signals or directional bias."
        )


def _check_dict_for_prohibited_keys(data: Dict[str, Any], prefix: str, errors: List[str]) -> None:
    for k, v in data.items():
        if k.lower() in PROHIBITED_BROKER_KEYS:
            errors.append(f"Prohibited broker/trading key '{prefix}{k}' detected in payload.")
        if isinstance(v, dict):
            _check_dict_for_prohibited_keys(v, f"{prefix}{k}.", errors)
        elif isinstance(v, list):
            for idx, item in enumerate(v):
                if isinstance(item, dict):
                    _check_dict_for_prohibited_keys(item, f"{prefix}{k}[{idx}].", errors)


def validate_external_context_payload(
    raw_payload: Dict[str, Any]
) -> Tuple[bool, List[str], Optional[ExternalContextPayload]]:
    """Strict validation and provenance evaluation for external context payloads."""
    errors: List[str] = []

    if not isinstance(raw_payload, dict):
        return False, ["Payload must be a JSON object."], None

    # 1. Prohibited Broker/Credential Keys Check
    _check_dict_for_prohibited_keys(raw_payload, "", errors)

    # 2. Required Root Fields
    required_roots = [
        "market_session_date",
        "provider",
    ]
    for rf in required_roots:
        if rf not in raw_payload or not raw_payload[rf]:
            errors.append(f"Missing required root field: '{rf}'")

    if errors:
        return False, errors, None

    # Date Format Validation
    session_date = str(raw_payload["market_session_date"]).strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", session_date):
        errors.append(f"Invalid market_session_date format '{session_date}'. Expected YYYY-MM-DD.")

    now_utc_dt = datetime.now(timezone.utc)
    now_ist_dt = datetime.now(IST)
    received_at_utc = raw_payload.get("received_at_utc") or now_utc_dt.isoformat()
    received_at_ist = raw_payload.get("received_at_ist") or now_ist_dt.strftime("%H:%M:%S")

    gen_utc = raw_payload.get("generated_at_utc") or received_at_utc
    gen_ist = raw_payload.get("generated_at_ist") or received_at_ist
    provider = str(raw_payload.get("provider", "gemini_spark")).strip()
    source_type = str(raw_payload.get("source_type", "EXTERNAL_CONTEXT")).strip()
    is_test_fixture = bool(raw_payload.get("is_test_fixture", False) or source_type == "TEST_FIXTURE")

    # 3. Parse and Independently Verify Fact Lists
    def _parse_and_verify_fact_list(field_key: str) -> List[ExternalFactItem]:
        items: List[ExternalFactItem] = []
        raw_items = raw_payload.get(field_key, [])
        if not isinstance(raw_items, list):
            errors.append(f"Field '{field_key}' must be an array of objects.")
            return []

        for idx, itm in enumerate(raw_items):
            if not isinstance(itm, dict):
                errors.append(f"Item {idx} in '{field_key}' must be an object.")
                continue

            title = str(itm.get("title", "")).strip()
            summary = str(itm.get("factual_summary", "")).strip()
            if not title:
                errors.append(f"Item {idx} in '{field_key}' missing required 'title'.")
            if not summary:
                errors.append(f"Item {idx} in '{field_key}' missing required 'factual_summary'.")

            relevance = itm.get("relevance_note")
            if relevance is not None:
                relevance = str(relevance).strip()

            # Check for prohibited terms in title, summary, relevance_note
            _check_text_for_prohibited_terms(title, f"{field_key}[{idx}].title", errors)
            _check_text_for_prohibited_terms(summary, f"{field_key}[{idx}].factual_summary", errors)
            _check_text_for_prohibited_terms(relevance, f"{field_key}[{idx}].relevance_note", errors)

            fact_id = str(itm.get("fact_id") or f"fact_{field_key}_{idx}_{hashlib.sha256(title.encode()).hexdigest()[:8]}")
            status_val = str(itm.get("status", FactStatus.CONFIRMED.value)).upper()
            if status_val not in FactStatus.__members__:
                errors.append(
                    f"Item {idx} in '{field_key}' has invalid status '{status_val}'."
                )
                continue

            # Upstream self-declared claim from Spark (Preserved, NOT trusted)
            upstream_verif = str(itm.get("verification_status") or itm.get("upstream_verification_status", "UNVERIFIED")).upper()

            radar_category = str(itm.get("radar_category") or "").strip().upper() or None
            instrument_label = str(itm.get("instrument_label") or "").strip() or None
            instrument_kind = str(itm.get("instrument_kind") or "").strip().upper() or None
            if any((radar_category, instrument_label, instrument_kind)):
                spec = RADAR_INSTRUMENT_SPECS.get(instrument_label or "")
                if not radar_category or not instrument_label or not instrument_kind:
                    errors.append(
                        f"Item {idx} in '{field_key}' must supply radar_category, "
                        "instrument_label, and instrument_kind together."
                    )
                elif spec != (radar_category, instrument_kind):
                    errors.append(
                        f"Item {idx} in '{field_key}' has unsupported radar instrument semantics "
                        f"for '{instrument_label}'."
                    )

            # CITADEL Truth Evaluation (Requires authentic record or defaults to UNVERIFIED)
            citadel_verif, auth_source, auth_val, conflict_info, verif_rec, val_notes = CitadelFactVerificationEngine.verify_fact_item(
                itm, is_test_fixture=is_test_fixture
            )

            fact_item = ExternalFactItem(
                fact_id=fact_id,
                title=title,
                factual_summary=summary,
                status=status_val,
                event_time_utc=itm.get("event_time_utc"),
                event_time_ist=itm.get("event_time_ist"),
                observed_or_published_at=itm.get("observed_or_published_at"),
                source_name=str(itm.get("source_name", "UNKNOWN")),
                source_url=itm.get("source_url"),
                source_timestamp=itm.get("source_timestamp"),
                relevance_note=relevance,
                upstream_verification_status=upstream_verif,
                verification_status=citadel_verif,
                verification_record=verif_rec,
                authoritative_source=auth_source,
                authoritative_value=auth_val,
                conflict_detail=conflict_info,
                validation_notes=val_notes,
                radar_category=radar_category,
                instrument_label=instrument_label,
                instrument_kind=instrument_kind,
            )
            items.append(fact_item)

        return items

    scheduled_events = _parse_and_verify_fact_list("scheduled_events")
    breaking_events = _parse_and_verify_fact_list("breaking_events")
    overnight_context = _parse_and_verify_fact_list("overnight_context")
    index_specific_events = _parse_and_verify_fact_list("index_specific_events")
    global_context = _parse_and_verify_fact_list("global_context")

    data_gaps = [str(g).strip() for g in raw_payload.get("data_gaps", []) if str(g).strip()]
    sources = [s for s in raw_payload.get("sources", []) if isinstance(s, dict)]

    if errors:
        return False, errors, None

    # Derive stable deterministic context ID and provenance hash
    payload_core = {
        "market_session_date": session_date,
        "provider": provider,
        "source_type": source_type,
        "scheduled_events": [e.to_dict() for e in scheduled_events],
        "breaking_events": [e.to_dict() for e in breaking_events],
        "overnight_context": [e.to_dict() for e in overnight_context],
        "index_specific_events": [e.to_dict() for e in index_specific_events],
        "global_context": [e.to_dict() for e in global_context],
        "data_gaps": data_gaps,
        "sources": sources,
    }
    payload_bytes = json.dumps(payload_core, sort_keys=True, default=str).encode("utf-8")
    provenance_hash = hashlib.sha256(payload_bytes).hexdigest()
    context_id = raw_payload.get("external_context_id") or f"ctx_{provenance_hash[:16]}"

    obj = ExternalContextPayload(
        external_context_id=context_id,
        market_session_date=session_date,
        generated_at_utc=gen_utc,
        generated_at_ist=gen_ist,
        received_at_utc=received_at_utc,
        received_at_ist=received_at_ist,
        provider=provider,
        source_type=source_type,
        scheduled_events=scheduled_events,
        breaking_events=breaking_events,
        overnight_context=overnight_context,
        index_specific_events=index_specific_events,
        global_context=global_context,
        data_gaps=data_gaps,
        sources=sources,
        is_test_fixture=is_test_fixture,
        provenance_hash=provenance_hash,
    )

    return True, [], obj


def _parse_iso_datetime(value: Optional[str], *, assume_tz: Optional[Any] = None) -> Optional[datetime]:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        if assume_tz is None:
            return None
        parsed = parsed.replace(tzinfo=assume_tz)
    return parsed


def classify_radar_item_time(item: ExternalFactItem, session_date: str) -> str:
    """Classify an external fact against the canonical IST market-session date."""
    try:
        canonical_date = date.fromisoformat(session_date)
    except ValueError:
        return RadarTimeClassification.TIMESTAMP_UNKNOWN.value

    candidates = (
        _parse_iso_datetime(item.observed_or_published_at),
        _parse_iso_datetime(item.event_time_utc, assume_tz=timezone.utc),
        _parse_iso_datetime(item.source_timestamp),
    )
    observed = next((candidate for candidate in candidates if candidate is not None), None)

    if observed is None and item.event_time_ist:
        raw_ist = str(item.event_time_ist).strip()
        observed = _parse_iso_datetime(raw_ist, assume_tz=IST)
        if observed is None:
            try:
                parsed_time = datetime_time.fromisoformat(raw_ist)
                observed = datetime.combine(canonical_date, parsed_time, tzinfo=IST)
            except ValueError:
                observed = None

    if observed is None:
        return RadarTimeClassification.TIMESTAMP_UNKNOWN.value

    observed_date = observed.astimezone(IST).date()
    if observed_date < canonical_date:
        return RadarTimeClassification.STALE.value
    if observed_date > canonical_date:
        return RadarTimeClassification.FUTURE.value
    return RadarTimeClassification.TODAY.value


def _radar_fact_projection(item: ExternalFactItem, session_date: str) -> Dict[str, Any]:
    classification = classify_radar_item_time(item, session_date)
    display_time_ist = item.event_time_ist
    if not display_time_ist:
        observed = (
            _parse_iso_datetime(item.observed_or_published_at)
            or _parse_iso_datetime(item.event_time_utc, assume_tz=timezone.utc)
            or _parse_iso_datetime(item.source_timestamp)
        )
        if observed is not None:
            display_time_ist = observed.astimezone(IST).strftime("%H:%M")
    return {
        "fact_id": item.fact_id,
        "title": item.title,
        "factual_summary": item.factual_summary,
        "source_name": item.source_name,
        "verification_status": item.verification_status,
        "time_classification": classification,
        "display_time_ist": display_time_ist,
        "radar_category": item.radar_category,
        "instrument_label": item.instrument_label,
        "instrument_kind": item.instrument_kind,
    }


def build_external_radar_projection(
    payload: Optional[ExternalContextPayload], session_date: str
) -> Dict[str, Any]:
    """Build the only UI-facing Today projection; React must not infer time or instruments."""
    empty_sections = [
        {"key": key, "label": label, "items": []}
        for key, label in RADAR_SECTION_LABELS
    ]
    if payload is None:
        return {
            "status": ExternalContextStatus.UNAVAILABLE.value,
            "reading_status": "UNAVAILABLE",
            "reason": "NO_ACTIVE_SPARK_CONTEXT_FOR_SESSION",
            "session_date": session_date,
            "source_check": SourceVerificationConnectorStatus.NOT_CONNECTED.value,
            "last_scan_ist": "NONE",
            "market_sections": empty_sections,
            "today_news": [],
            "timestamp_unknown_items": [],
            "stale_items_count": 0,
            "future_items_count": 0,
        }

    projected = [_radar_fact_projection(item, session_date) for item in payload.all_items()]
    today_items = [item for item in projected if item["time_classification"] == RadarTimeClassification.TODAY.value]
    unknown_items = [item for item in projected if item["time_classification"] == RadarTimeClassification.TIMESTAMP_UNKNOWN.value]
    stale_count = sum(item["time_classification"] == RadarTimeClassification.STALE.value for item in projected)
    future_count = sum(item["time_classification"] == RadarTimeClassification.FUTURE.value for item in projected)

    market_sections: List[Dict[str, Any]] = []
    for key, label in RADAR_SECTION_LABELS:
        section_items = [
            {
                "fact_id": item["fact_id"],
                "instrument_label": item["instrument_label"],
                "instrument_kind": item["instrument_kind"],
                "value": item["factual_summary"],
                "source_name": item["source_name"],
                "verification_status": item["verification_status"],
                "display_time_ist": item["display_time_ist"],
            }
            for item in today_items
            if item["radar_category"] == key and item["instrument_label"]
        ]
        market_sections.append({"key": key, "label": label, "items": section_items})

    source_connected = bool(payload.verified_items() or payload.conflicted_items())
    source_check = (
        SourceVerificationConnectorStatus.CONNECTED.value
        if source_connected
        else SourceVerificationConnectorStatus.NOT_CONNECTED.value
    )
    reading_status = (
        "UNAVAILABLE"
        if not projected
        else "AVAILABLE"
        if source_connected and today_items
        else "PARTIAL"
    )
    today_news = [item for item in today_items if not item["instrument_label"]]
    return {
        "status": ExternalContextStatus.AVAILABLE.value,
        "reading_status": reading_status,
        "reason": (
            "CURRENT_CONTEXT_AVAILABLE"
            if today_items
            else "NO_TODAY_TIMESTAMPED_CONTEXT"
        ),
        "session_date": session_date,
        "source_check": source_check,
        "last_scan_ist": payload.generated_at_ist or payload.received_at_ist or "NONE",
        "market_sections": market_sections,
        "today_news": today_news,
        "timestamp_unknown_items": unknown_items,
        "stale_items_count": stale_count,
        "future_items_count": future_count,
    }


class ExternalContextStore:
    """Durable append-only store and time-indexed manager for external context."""

    def __init__(self, storage_dir: Optional[str] = None, runtime_mode: str = "TEST") -> None:
        normalized_runtime_mode = str(runtime_mode).strip().upper()
        if normalized_runtime_mode not in {"LIVE", "REPLAY", "TEST"}:
            raise ValueError("runtime_mode must be one of LIVE, REPLAY, or TEST")
        self.runtime_mode = normalized_runtime_mode
        self.storage_dir = Path(storage_dir or "data/sol_shadow")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = self.storage_dir / "external_context_history.jsonl"
        self._active_payloads_by_date: Dict[str, ExternalContextPayload] = {}
        self._all_payloads_chronological: List[ExternalContextPayload] = []
        self._seen_id_hash: Dict[str, str] = {}
        self._lock = threading.RLock()
        self._integrity_status = "OK"
        self._last_error: Optional[str] = None
        self._corrupt_records = 0
        self._skipped_test_fixtures = 0
        self._duplicate_records = 0
        self._identity_collisions = 0
        self._hydrate()

    def reload(self) -> None:
        """Clear in-memory payload cache and rehydrate from history disk file."""
        with self._lock:
            self._all_payloads_chronological.clear()
            self._active_payloads_by_date.clear()
            self._seen_id_hash.clear()
            self._integrity_status = "OK"
            self._last_error = None
            self._corrupt_records = 0
            self._skipped_test_fixtures = 0
            self._duplicate_records = 0
            self._identity_collisions = 0
            self._hydrate()

    @staticmethod
    def _received_at(payload: ExternalContextPayload) -> Optional[datetime]:
        return _parse_iso_datetime(payload.received_at_utc, assume_tz=timezone.utc)

    def _remember(self, payload: ExternalContextPayload) -> bool:
        if self.runtime_mode != "TEST" and payload.is_test_fixture:
            self._skipped_test_fixtures += 1
            self._integrity_status = "DEGRADED"
            self._last_error = "TEST_FIXTURE_SKIPPED_OUTSIDE_TEST_RUNTIME"
            return False

        known_hash = self._seen_id_hash.get(payload.external_context_id)
        if known_hash is not None:
            if known_hash == payload.provenance_hash:
                self._duplicate_records += 1
                return False
            self._identity_collisions += 1
            self._integrity_status = "DEGRADED"
            self._last_error = "EXTERNAL_CONTEXT_IDENTITY_COLLISION"
            return False
        self._seen_id_hash[payload.external_context_id] = payload.provenance_hash
        self._all_payloads_chronological.append(payload)

        current = self._active_payloads_by_date.get(payload.market_session_date)
        current_time = self._received_at(current) if current else None
        payload_time = self._received_at(payload)
        if current is None or (
            payload_time is not None
            and (current_time is None or payload_time >= current_time)
        ):
            self._active_payloads_by_date[payload.market_session_date] = payload
        return True

    def _hydrate(self) -> None:
        """Hydrate historical external context payloads from disk."""
        if not self.history_file.exists():
            return
        try:
            with self.history_file.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        valid, errors, obj = validate_external_context_payload(d)
                        if valid and obj:
                            self._remember(obj)
                        else:
                            self._corrupt_records += 1
                            self._integrity_status = "DEGRADED"
                            self._last_error = errors[0] if errors else "INVALID_EXTERNAL_CONTEXT_RECORD"
                    except Exception as exc:
                        self._corrupt_records += 1
                        self._integrity_status = "DEGRADED"
                        self._last_error = f"EXTERNAL_CONTEXT_HYDRATION_ERROR:{type(exc).__name__}"
                        continue
        except Exception as exc:
            self._integrity_status = "ERROR"
            self._last_error = f"EXTERNAL_CONTEXT_STORE_READ_ERROR:{type(exc).__name__}"

    def append(self, payload: ExternalContextPayload) -> bool:
        """Durably append accepted payload to JSONL and update active in-memory cache."""
        with self._lock:
            if self.runtime_mode != "TEST" and payload.is_test_fixture:
                self._last_error = "TEST_FIXTURE_REJECTED_OUTSIDE_TEST_RUNTIME"
                return False
            known_hash = self._seen_id_hash.get(payload.external_context_id)
            if known_hash is not None:
                if known_hash == payload.provenance_hash:
                    self._duplicate_records += 1
                    return True
                self._identity_collisions += 1
                self._integrity_status = "DEGRADED"
                self._last_error = "EXTERNAL_CONTEXT_IDENTITY_COLLISION"
                return False
            try:
                line = json.dumps(payload.to_dict(), default=str) + "\n"
                with self.history_file.open("a", encoding="utf-8") as f:
                    f.write(line)
                    f.flush()
                    os.fsync(f.fileno())
                self._remember(payload)
                self._last_error = None
                return True
            except Exception as exc:
                self._integrity_status = "ERROR"
                self._last_error = f"EXTERNAL_CONTEXT_STORE_WRITE_ERROR:{type(exc).__name__}"
                return False

    def get_active_context(self, session_date: str) -> Optional[ExternalContextPayload]:
        """Retrieve latest external context for active session date."""
        with self._lock:
            return self._active_payloads_by_date.get(session_date)

    def get_context_as_of(self, session_date: str, as_of_utc: str) -> Optional[ExternalContextPayload]:
        """Reconstruct historical external context strictly as of timestamp (Zero Look-Ahead)."""
        as_of = _parse_iso_datetime(as_of_utc, assume_tz=timezone.utc)
        if as_of is None:
            return None
        with self._lock:
            candidates = [
                (received, payload)
                for payload in self._all_payloads_chronological
                if payload.market_session_date == session_date
                and (received := self._received_at(payload)) is not None
                and received <= as_of
            ]
        if not candidates:
            return None
        return max(candidates, key=lambda entry: entry[0])[1]

    def reset_session(self, session_date: str) -> None:
        """Handle session rotation."""
        pass

    def get_health_summary(self, session_date: str) -> Dict[str, Any]:
        """Return compact health telemetry and truthful verification status for Beacon presentation."""
        active = self.get_active_context(session_date)
        if not active:
            radar = build_external_radar_projection(None, session_date)
            return {
                "status": ExternalContextStatus.UNAVAILABLE.value,
                "reading_status": radar["reading_status"],
                "unavailable_reason": radar["reason"],
                "source_verification_status": SourceVerificationConnectorStatus.NOT_CONNECTED.value,
                "market_session_date": session_date,
                "last_received_ist": "NONE",
                "last_source_time_ist": "NONE",
                "total_items": 0,
                "verified_items_count": 0,
                "unverified_items_count": 0,
                "conflicted_items_count": 0,
                "source_unavailable_items_count": 0,
                "synthetic_test_items_count": 0,
                "other_items_count": 0,
                "verification_status_counts": {
                    **{status.value: 0 for status in VerificationStatus},
                    "OTHER": 0,
                },
                "verification_counts_reconcile": True,
                "verified_sources_count": 0,
                "data_gaps_count": 0,
                "provider": "NONE",
                "is_test_fixture": False,
                "summary_titles": [],
                "conflicted_items": [],
                "scheduled_events": [],
                "breaking_events": [],
                "overnight_context": [],
                "index_specific_events": [],
                "global_context": [],
                "data_gaps": [],
                "sources": [],
                "radar": radar,
                "store_runtime_mode": self.runtime_mode,
                "store_integrity_status": self._integrity_status,
                "store_last_error": self._last_error,
                "corrupt_records_count": self._corrupt_records,
                "skipped_test_fixtures_count": self._skipped_test_fixtures,
                "duplicate_records_count": self._duplicate_records,
                "identity_collisions_count": self._identity_collisions,
            }

        conflicts = [
            {
                "fact_id": itm.fact_id,
                "title": itm.title,
                "spark_claim": itm.event_time_ist or itm.observed_or_published_at or "N/A",
                "authoritative_source": itm.authoritative_source,
                "authoritative_value": itm.authoritative_value,
                "conflict_detail": itm.conflict_detail,
            }
            for itm in active.conflicted_items()
        ]

        titles = [
            f"[{itm.verification_status}] {itm.title}"
            for itm in active.all_items()
        ][:6]

        has_verified_records = len(active.verified_items()) > 0 or len(active.conflicted_items()) > 0

        radar = build_external_radar_projection(active, session_date)
        verification_counts = active.verification_status_counts()
        return {
            "status": ExternalContextStatus.AVAILABLE.value,
            "reading_status": radar["reading_status"],
            "unavailable_reason": None,
            "source_verification_status": (
                SourceVerificationConnectorStatus.CONNECTED.value
                if has_verified_records
                else SourceVerificationConnectorStatus.NOT_CONNECTED.value
            ),
            "external_context_id": active.external_context_id,
            "market_session_date": active.market_session_date,
            "last_received_ist": active.received_at_ist,
            "last_source_time_ist": active.generated_at_ist,
            "total_items": active.total_items_count(),
            "verified_items_count": len(active.verified_items()),
            "unverified_items_count": len(active.unverified_items()),
            "conflicted_items_count": len(active.conflicted_items()),
            "source_unavailable_items_count": verification_counts[VerificationStatus.SOURCE_UNAVAILABLE.value],
            "synthetic_test_items_count": verification_counts[VerificationStatus.SYNTHETIC_TEST.value],
            "other_items_count": verification_counts["OTHER"],
            "verification_status_counts": verification_counts,
            "verification_counts_reconcile": sum(verification_counts.values()) == active.total_items_count(),
            "verified_sources_count": active.genuinely_verified_sources_count(),
            "data_gaps_count": len(active.data_gaps),
            "provider": active.provider,
            "is_test_fixture": active.is_test_fixture,
            "summary_titles": titles,
            "conflicted_items": conflicts,
            "scheduled_events": [e.to_dict() for e in active.scheduled_events],
            "breaking_events": [e.to_dict() for e in active.breaking_events],
            "overnight_context": [e.to_dict() for e in active.overnight_context],
            "index_specific_events": [e.to_dict() for e in active.index_specific_events],
            "global_context": [e.to_dict() for e in active.global_context],
            "data_gaps": list(active.data_gaps),
            "sources": active.sources,
            "provenance_hash": active.provenance_hash[:16],
            "radar": radar,
            "store_runtime_mode": self.runtime_mode,
            "store_integrity_status": self._integrity_status,
            "store_last_error": self._last_error,
            "corrupt_records_count": self._corrupt_records,
            "skipped_test_fixtures_count": self._skipped_test_fixtures,
            "duplicate_records_count": self._duplicate_records,
            "identity_collisions_count": self._identity_collisions,
        }
