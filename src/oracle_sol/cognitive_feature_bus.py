"""Thin projection of approved Sol fields; no calculation or direction selection."""
from copy import deepcopy
from src.oracle_sol.field_registry import SOL_VOB_FREE_FIELD_REGISTRY
from src.oracle_sol.provenance_guard import ProvenanceGuard


def project_features(snapshot) -> dict:
    raw = snapshot.to_dict()
    ProvenanceGuard.verify_field_level_allowlist(raw, strict=True)
    sources = raw.get("upstream_source_health", {}).get("producer_sources", {})
    features = {}
    for name, metadata in SOL_VOB_FREE_FIELD_REGISTRY.items():
        # OSE composite outputs require separately certified non-VOB lineage.
        if name.startswith("ose_"):
            continue
        value = raw.get(name)
        domain = metadata.domain
        source_group = "order_flow" if domain == "flow" else "market" if domain == "underlying" else "options"
        if name == "session_vwap":
            source_group = "chart"
        source = sources.get(source_group, {})
        pricing = value if name in {"ce_pricing", "pe_pricing"} and isinstance(value, dict) else {}
        security_id = pricing.get("security_id")
        if name == "futures_ltp" or domain == "flow":
            security_id = raw.get("futures_security_id")
        features[name] = {
            "value": deepcopy(value),
            "domain": domain,
            "meaning": metadata.description,
            "producer": metadata.canonical_owner,
            "source_module": metadata.source_module,
            "source_field": name,
            "source_id": source.get("source_id"),
            "source_timestamp": source.get("source_timestamp"),
            "snapshot_timestamp": raw.get("timestamp_utc"),
            "session_id": raw.get("market_session_date"),
            "source_revision": source.get("source_revision"),
            "security_id": security_id,
            "role_identity": "ATM_CE" if name == "ce_pricing" else "ATM_PE" if name == "pe_pricing" else None,
            "exactness": "EXACT" if security_id is not None else "UNSPECIFIED",
            "freshness": "UNAVAILABLE" if value is None else "SOURCE_TIME_PRESENT" if pricing.get("source_timestamp") or source.get("source_timestamp") else "TIMESTAMP_UNKNOWN",
            "lineage_type": metadata.lineage_type.value,
            "availability": raw.get("availability_matrix", {}).get(name, "RECORDED" if value is not None else "UNAVAILABLE"),
        }
    return {"schema_version": "cognitive-features-v1", "snapshot_id": raw["snapshot_id"],
            "session_id": raw["market_session_date"], "market_state": str(getattr(snapshot.system_status, "value", snapshot.system_status)),
            "fields": features}
