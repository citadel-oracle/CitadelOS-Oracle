"""Process-isolated Fast Lane snapshot construction.

The worker owns presentation-only wrapping and JSON encoding.  It never owns
market-data transport or trading calculations.  Inputs are already-calculated
canonical provider snapshots; outputs are immutable encoded REST/SSE bytes.
"""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Mapping

from src.oracle.isolated_execution_boundary import IsolatedExecutionBoundary


def _json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode()


def _timestamp(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    for key in (
        "source_event_time",
        "source_timestamp",
        "observed_at",
        "generated_at",
        "generated_timestamp",
        "updated_at",
        "calculated_at",
    ):
        if value.get(key):
            return str(value[key])
    data = value.get("data")
    if isinstance(data, Mapping):
        tactical = data.get("tactical_edge")
        if isinstance(tactical, Mapping):
            return _timestamp(tactical)
    return None


def wrap_provider_feed(name: str, value: Any, error: str | None) -> dict[str, Any]:
    """Preserve the accepted Fast Lane provider presentation contract."""

    source_timestamp = _timestamp(value)
    status = (
        str(value.get("status") or "AVAILABLE").upper()
        if isinstance(value, Mapping)
        else "AVAILABLE"
    )
    stale = status in {"STALE", "DEGRADED", "DEGRADED_STALE", "LAST_GOOD"}
    unavailable = value is None or status in {"UNAVAILABLE", "FAILED", "ERROR"}
    return {
        "ok": not unavailable,
        "data": value if value is not None else None,
        "error": (
            {
                "code": "ORACLE_FAST_LANE_PROVIDER_UNAVAILABLE",
                "message": error or status,
            }
            if unavailable
            else None
        ),
        "meta": {
            "module": name,
            "health": "OFFLINE" if unavailable else "STALE" if stale else "HEALTHY",
            "readiness": "UNAVAILABLE" if unavailable else "DEGRADED" if stale else "READY",
            "latency_ms": 0.0,
            "last_updated": source_timestamp,
            "source_last_updated": source_timestamp,
            "source_timestamp": source_timestamp,
            "freshness": "UNAVAILABLE" if unavailable else "STALE" if stale else "FRESH",
            "stale_reason": (
                value.get("reason") or value.get("stale_reason")
                if isinstance(value, Mapping) and (stale or unavailable)
                else None
            ),
            "advisory_only": True,
            "execution_influence": 0,
            "publication_path": "ORACLE_FAST_LANE_CACHE_ONLY",
        },
    }


def _make_lean_live_feed(name: str, feed: dict[str, Any]) -> dict[str, Any]:
    """Produce a lean actionable live feed for Fast Lane by separating on-demand historical/research arrays."""
    if not isinstance(feed, Mapping) or not feed.get("ok"):
        return feed
    data = feed.get("data")
    if not isinstance(data, Mapping):
        return feed

    if name == "strategies":
        st_data = dict(data)
        st_data.pop("edge_lab", None)
        st_data.pop("audit", None)
        st_data.pop("versions", None)
        if "notifications" in st_data and isinstance(st_data["notifications"], list):
            st_data["notifications"] = st_data["notifications"][-5:]
        if "closed_trades" in st_data and isinstance(st_data["closed_trades"], list):
            st_data["closed_trades"] = st_data["closed_trades"][-5:]
        if "deployments" in st_data and isinstance(st_data["deployments"], list):
            st_data["deployments"] = [
                {
                    "strategy_id": d.get("strategy_id"),
                    "instance_id": d.get("instance_id"),
                    "name": d.get("name"),
                    "status": d.get("status"),
                    "scheduler": d.get("scheduler"),
                    "positions": d.get("positions"),
                    "pnl": d.get("pnl"),
                    "metrics": d.get("metrics"),
                    "realized_pnl": d.get("realized_pnl"),
                    "unrealized_pnl": d.get("unrealized_pnl"),
                }
                for d in st_data["deployments"]
                if isinstance(d, Mapping)
            ]
        return {**feed, "data": st_data}

    elif name == "strategy_lab":
        sl_data = dict(data)
        if "execution" in sl_data and isinstance(sl_data["execution"], Mapping):
            exec_lean = dict(sl_data["execution"])
            if "timeline" in exec_lean and isinstance(exec_lean["timeline"], list):
                exec_lean["timeline"] = exec_lean["timeline"][-10:]
            if "journal" in exec_lean and isinstance(exec_lean["journal"], list):
                exec_lean["journal"] = exec_lean["journal"][-10:]
            if "closed_trades" in exec_lean and isinstance(exec_lean["closed_trades"], list):
                exec_lean["closed_trades"] = exec_lean["closed_trades"][-5:]
            sl_data["execution"] = exec_lean
        if "strategies" in sl_data and isinstance(sl_data["strategies"], list):
            sl_data["strategies"] = sl_data["strategies"][:5]
        return {**feed, "data": sl_data}

    elif name == "futures_chart":
        fc_data = dict(data)
        if "candles" in fc_data and isinstance(fc_data["candles"], list):
            fc_data["candles"] = fc_data["candles"][-30:]
        if "timeframes" in fc_data and isinstance(fc_data["timeframes"], Mapping):
            tf_5m = dict(fc_data["timeframes"].get("5m", {}))
            if "candles" in tf_5m and isinstance(tf_5m["candles"], list):
                tf_5m["candles"] = tf_5m["candles"][-30:]
            fc_data["timeframes"] = {"5m": tf_5m}
        return {**feed, "data": fc_data}

    elif name == "argus":
        arg_raw = dict(data)
        inner_d = arg_raw.get("data")
        if isinstance(inner_d, Mapping):
            inner_d = dict(inner_d)
            if "tactical_edge" in inner_d and isinstance(inner_d["tactical_edge"], Mapping):
                tac_d = dict(inner_d["tactical_edge"])
                if "argus_prime" in tac_d and isinstance(tac_d["argus_prime"], Mapping):
                    prime_d = dict(tac_d["argus_prime"])
                    prime_d.pop("full_evidence", None)
                    if "strike_spine" in prime_d and isinstance(prime_d["strike_spine"], Mapping):
                        sp = dict(prime_d["strike_spine"])
                        if "strikes" in sp and isinstance(sp["strikes"], list):
                            sp["strikes"] = sp["strikes"][:7]
                        prime_d["strike_spine"] = sp
                    tac_d["argus_prime"] = prime_d
                if "contract_selection" in tac_d and isinstance(tac_d["contract_selection"], Mapping):
                    cs_d = dict(tac_d["contract_selection"])
                    cs_d.pop("all_candidate_ranks", None)
                    tac_d["contract_selection"] = cs_d
                if "decision" in tac_d and isinstance(tac_d["decision"], Mapping):
                    dec_d = dict(tac_d["decision"])
                    dec_d.pop("all_candidate_ranks", None)
                    tac_d["decision"] = dec_d
                inner_d["tactical_edge"] = tac_d
            arg_raw["data"] = inner_d
            return {**feed, "data": arg_raw}

    return feed


class FastLaneSnapshotProcessor:
    """Stateful child-owned builder for one immutable Fast Lane revision."""

    BASE_NAMES = ("oracle", "strategy_lab", "strategies", "eye_oracle_projection")

    def __init__(self) -> None:
        self._feeds: dict[str, dict[str, Any]] = {}
        self._encoded_feeds: dict[str, bytes] = {}
        self._last_source_revisions: tuple[tuple[str, str], ...] | None = None
        self._full_builds = 0
        self._full_serializations = 0
        self._duplicate_builds_avoided = 0
        self._feed_serializations = 0
        self._feed_reuses = 0
        self._previous_serialization_ms: float | None = None

    def __call__(self, kind: str, payload: Any) -> dict[str, Any] | None:
        if kind != "BUILD" or not isinstance(payload, Mapping):
            raise ValueError(f"unsupported Fast Lane publisher input: {kind}")

        source_revisions = tuple(
            sorted(
                (str(name), str(revision))
                for name, revision in (payload.get("source_revisions") or {}).items()
            )
        )
        if source_revisions == self._last_source_revisions:
            self._duplicate_builds_avoided += 1
            return None

        build_started = perf_counter()
        changed = set(str(name) for name in (payload.get("changed") or ()))
        base_updates = payload.get("base_updates") or {}
        provider_updates = payload.get("provider_updates") or {}
        workspace_update = payload.get("workspace_update")
        removed = set(str(name) for name in (payload.get("removed") or ()))

        for name in removed:
            self._feeds.pop(name, None)
            self._encoded_feeds.pop(name, None)

        for name, feed in base_updates.items():
            self._cache_feed(str(name), dict(feed))

        for name, update in provider_updates.items():
            if not isinstance(update, Mapping):
                continue
            self._cache_feed(
                str(name),
                wrap_provider_feed(
                    str(name), update.get("value"), update.get("error")
                ),
            )

        updated_names = set(str(name) for name in base_updates) | set(
            str(name) for name in provider_updates
        )
        if isinstance(workspace_update, Mapping):
            updated_names.add("oracle")
        self._feed_reuses += len(set(self._feeds) - updated_names)

        if isinstance(workspace_update, Mapping):
            existing = self._feeds.get("oracle") or {"data": {}}
            oracle_data = deepcopy(existing.get("data") or {})
            oracle_data["live_workspace"] = deepcopy(workspace_update.get("value"))
            self._cache_feed(
                "oracle",
                wrap_provider_feed(
                    "oracle",
                    oracle_data,
                    workspace_update.get("error"),
                ),
            )
            changed.add("oracle")

        generated_at = datetime.now(timezone.utc).isoformat()
        revision_seed = "|".join(f"{name}:{revision}" for name, revision in source_revisions)
        trace_id = "oracle-fast-" + hashlib.sha256(revision_seed.encode()).hexdigest()[:20]
        source_revisions_dict = dict(source_revisions)
        full_revision = int(payload.get("build_revision") or (self._full_builds + 1))
        event_id = f"oracle-fast-snapshot-{full_revision}"

        assembly_ms = (perf_counter() - build_started) * 1000.0
        serialization_started = perf_counter()
        feed_fragment = self._encoded_feed_fragment()
        polling = {
            "recommended_interval_ms": 30_000,
            "single_request": True,
            "frontend_side_effects": False,
            "delivery": "ORACLE_FAST_LANE",
            "served_from_cache": True,
            "projection_age_ms": 0.0,
            "snapshot_status": "FRESH",
            "oracle_turbo_mode": True,
            "assembly_ms": round(assembly_ms, 3),
            "serialization_ms": (
                round(self._previous_serialization_ms, 3)
                if self._previous_serialization_ms is not None
                else None
            ),
        }
        body = self._compose_document(
            feed_fragment=feed_fragment,
            trace_id=trace_id,
            generated_at=generated_at,
            revision=full_revision,
            source_revisions=source_revisions_dict,
            polling=polling,
        )
        patch_names = sorted(name for name in changed if name in self._encoded_feeds)
        patch_fragment = b",".join(
            _json(name) + b":" + self._encoded_feeds[name] for name in patch_names
        )
        common_event = (
            b'"event_id":' + _json(event_id)
            + b',"published_at":' + _json(generated_at)
            + b',"trace_id":' + _json(trace_id)
            + b',"generated_at":' + _json(generated_at)
            + b',"symbol":"NIFTY"'
            + b',"global_revision":' + _json(full_revision)
            + b',"source_revisions":' + _json(source_revisions_dict)
            + b',"changed_sections":' + _json(patch_names)
        )
        patch_event = (
            b'{"event_type":"ORACLE_FAST_LANE_UPDATED",'
            + common_event
            + b',"feeds":{' + patch_fragment + b'},"full":false}'
        )
        resync_event = (
            b'{"event_type":"ORACLE_FAST_LANE_RESYNC",'
            + common_event
            + b',"feeds":{' + feed_fragment + b'},"full":true}'
        )
        serialization_ms = (perf_counter() - serialization_started) * 1000.0
        self._previous_serialization_ms = serialization_ms
        self._full_builds += 1
        self._full_serializations += 1
        self._last_source_revisions = source_revisions

        core_feeds = {
            name: {
                "present": name in self._feeds,
                "ok": bool((self._feeds.get(name) or {}).get("ok")),
                "readiness": ((self._feeds.get(name) or {}).get("meta") or {}).get("readiness"),
            }
            for name in ("argus", "order_flow", "futures_chart")
        }
        return {
            "role": "fast_lane_publisher",
            "owner_pid": os.getppid(),
            "event_id": event_id,
            "revision": full_revision,
            "source_revisions": source_revisions_dict,
            "changed_sections": patch_names,
            "trace_id": trace_id,
            "generated_at": generated_at,
            "body": body,
            "patch_event": patch_event,
            "resync_event": resync_event,
            "byte_length": len(body),
            "assembly_ms": assembly_ms,
            "serialization_ms": serialization_ms,
            "full_builds": self._full_builds,
            "full_serializations": self._full_serializations,
            "duplicate_builds_avoided": self._duplicate_builds_avoided,
            "feed_serializations": self._feed_serializations,
            "feed_reuses": self._feed_reuses,
            "feed_count": len(self._feeds),
            "core_feeds": core_feeds,
        }

    def _cache_feed(self, name: str, feed: dict[str, Any]) -> None:
        lean_feed = _make_lean_live_feed(name, feed)
        self._feeds[name] = lean_feed
        self._encoded_feeds[name] = _json(lean_feed)
        self._feed_serializations += 1

    def _encoded_feed_fragment(self) -> bytes:
        return b",".join(
            _json(name) + b":" + self._encoded_feeds[name]
            for name in sorted(self._encoded_feeds)
        )

    @staticmethod
    def _compose_document(
        *,
        feed_fragment: bytes,
        trace_id: str,
        generated_at: str,
        revision: int,
        source_revisions: Mapping[str, str],
        polling: Mapping[str, Any],
    ) -> bytes:
        safety = {
            "advisory_only": True,
            "execution_influence": "ZERO",
            "paper_only": True,
            "live_trading_enabled": False,
            "broker_submission": False,
        }
        return b"{" + b",".join((
            b'"api_version":"2.0-oracle-fast-lane"',
            b'"schema_version":2',
            b'"revision":' + _json(revision),
            b'"source_revisions":' + _json(dict(source_revisions)),
            b'"trace_id":' + _json(trace_id),
            b'"generated_at":' + _json(generated_at),
            b'"symbol":"NIFTY"',
            b'"feeds":{' + feed_fragment + b"}",
            b'"polling":' + _json(dict(polling)),
            b'"safety":' + _json(safety),
        )) + b"}"


class FastLanePublisherBoundary(IsolatedExecutionBoundary):
    """One owner-tracked child process for Fast Lane build/serialization."""

    def __init__(self, *, on_snapshot, context_name: str | None = None) -> None:
        super().__init__(
            name="citadel-fast-lane-publisher",
            processor=FastLaneSnapshotProcessor(),
            on_snapshot=on_snapshot,
            input_capacity=16,
            publish_interval_seconds=0.05,
            context_name=context_name,
        )

    def status(self) -> dict[str, Any]:
        return {"role": "fast_lane_publisher", **super().status()}
