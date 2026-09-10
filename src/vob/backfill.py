"""Canonical NIFTY 1m backfill for BigBeluga VOB engine.

Fetches real NIFTY index 1m candles from Dhan API in 5-day windows,
merges them (dedup by timestamp) into the canonical vob_1m_candles.json.

Rules:
- Never synthetic candles.
- Never 5m-to-3m reconstruction.
- Write only through canonical VOB candle storage.
- No duplicate external fetches (deduplicated by time epoch).
- advisory_only=True, execution_influence=ZERO.
"""
from __future__ import annotations

import json
import os
import threading
import time as _time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
NSE_OPEN  = (9, 15)
NSE_CLOSE = (15, 30)

NIFTY_SECURITY_ID = "13"
NIFTY_SEGMENT     = "IDX_I"
NIFTY_INSTRUMENT  = "INDEX"

DEFAULT_CANONICAL_PATH = Path(
    os.environ.get("CITADEL_STATE_ROOT", "/Users/ayushmudgal/Developer/CitadelOS/logs")
) / "vob_1m_candles.json"

_LIVE_SYNC_LOCK = threading.Lock()
_LAST_LIVE_SYNC_ATTEMPT = 0.0


def _is_nse_trading_day(d: date) -> bool:
    """Weekday-only check (holidays not filtered — Dhan returns empty for holidays)."""
    return d.weekday() < 5  # Mon–Fri


def _date_windows(start: date, end: date, chunk_days: int = 5) -> List[Tuple[str, str]]:
    """Generate non-overlapping [from_date, to_date] windows of chunk_days."""
    windows = []
    cur = start
    while cur <= end:
        w_end = min(cur + timedelta(days=chunk_days - 1), end)
        windows.append((cur.strftime("%Y-%m-%d"), w_end.strftime("%Y-%m-%d")))
        cur = w_end + timedelta(days=1)
    return windows


def _load_canonical(path: Path) -> Dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"candles": []}


def _save_canonical(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def _session_candle(candle: Mapping[str, Any]) -> bool:
    try:
        dt = datetime.fromtimestamp(float(candle["time"]), tz=IST)
        return NSE_OPEN <= (dt.hour, dt.minute) < NSE_CLOSE and all(
            candle.get(key) is not None for key in ("open", "high", "low", "close")
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def _completed_cutoff(reference: datetime) -> datetime:
    session_last = reference.replace(hour=15, minute=29, second=0, microsecond=0)
    return min(reference.replace(second=0, microsecond=0) - timedelta(minutes=1), session_last)


def mark_vob_evaluated(canonical_path: Path, evaluated_through: datetime) -> Dict[str, Any]:
    """Atomically advance the VOB evaluation cursor after successful replay."""
    with _LIVE_SYNC_LOCK:
        data = _load_canonical(canonical_path)
        cursor = dict(data.get("cursor") or {})
        persisted = cursor.get("latest_persisted_1m") or cursor.get("latest_completed_1m")
        evaluated = evaluated_through.astimezone(IST).replace(second=0, microsecond=0).isoformat()
        if persisted and evaluated > persisted:
            raise ValueError("VOB evaluation cursor cannot advance beyond persisted candles")
        cursor.update({
            "latest_evaluated_1m": evaluated,
            "runtime_status": "LIVE" if persisted == evaluated and int(cursor.get("backlog_count") or 0) == 0 else "CATCHING_UP",
            "evaluated_at": datetime.now(tz=IST).isoformat(),
        })
        data["cursor"] = cursor
        _save_canonical(canonical_path, data)
        return dict(cursor)


def sync_current_session(
    canonical_path: Optional[Path] = None,
    client: Optional[Any] = None,
    *,
    now: Optional[datetime] = None,
    minimum_retry_seconds: float = 5.0,
) -> Dict[str, Any]:
    """Append authoritative completed NIFTY spot 1m candles for the live session."""
    global _LAST_LIVE_SYNC_ATTEMPT

    reference = (now or datetime.now(tz=IST)).astimezone(IST)
    path = canonical_path or DEFAULT_CANONICAL_PATH
    if not _is_nse_trading_day(reference.date()) or (reference.hour, reference.minute) < NSE_OPEN:
        return {"status": "WAITING_FOR_SESSION", "runtime_status": "CATCHING_UP", "added": 0}

    completed_cutoff = _completed_cutoff(reference)
    with _LIVE_SYNC_LOCK:
        existing = _load_canonical(path)
        original: List[Dict[str, Any]] = list(existing.get("candles") or [])
        by_epoch = {float(c["time"]): dict(c) for c in original if _session_candle(c)}
        invalid_removed = len(original) - len(by_epoch)
        candles = [by_epoch[key] for key in sorted(by_epoch)]
        today_epochs = {
            epoch for epoch in by_epoch
            if datetime.fromtimestamp(epoch, tz=IST).date() == reference.date() and datetime.fromtimestamp(epoch, tz=IST) <= completed_cutoff
        }
        session_open = reference.replace(hour=9, minute=15, second=0, microsecond=0)
        expected_epochs = [
            (session_open + timedelta(minutes=offset)).timestamp()
            for offset in range(max(0, int((completed_cutoff - session_open).total_seconds() // 60) + 1))
        ]
        missing_before = [epoch for epoch in expected_epochs if epoch not in today_epochs]
        cursor = dict(existing.get("cursor") or {})
        latest_epoch = max(by_epoch, default=None)
        latest_dt = datetime.fromtimestamp(latest_epoch, tz=IST) if latest_epoch is not None else None
        if not missing_before:
            cursor.update({
                "latest_completed_1m": latest_dt.isoformat() if latest_dt else None,
                "latest_persisted_1m": latest_dt.isoformat() if latest_dt else None,
                "backlog_count": 0,
                "runtime_status": "LIVE" if cursor.get("latest_evaluated_1m") == (latest_dt.isoformat() if latest_dt else None) else "CATCHING_UP",
                "source": "DHAN_INDEX_1M",
            })
            if invalid_removed or existing.get("cursor") != cursor:
                updated = dict(existing); updated["candles"] = candles; updated["cursor"] = cursor; _save_canonical(path, updated)
            return {"status": cursor["runtime_status"], "runtime_status": cursor["runtime_status"], "added": 0, "invalid_removed": invalid_removed, "backlog_count": 0, "latest_completed_1m": latest_dt.isoformat() if latest_dt else None}

        attempted_at = _time.monotonic()
        if attempted_at - _LAST_LIVE_SYNC_ATTEMPT < minimum_retry_seconds:
            return {"status": "RETRY_THROTTLED", "added": 0, "latest_completed_1m": latest_dt.isoformat() if latest_dt else None}
        _LAST_LIVE_SYNC_ATTEMPT = attempted_at

        if client is None:
            from src.broker.dhan_client import DhanClient
            client = DhanClient()
        fetched = _fetch_window(client, reference.date().isoformat(), reference.date().isoformat())
        completed = [
            candle for candle in fetched
            if datetime.fromtimestamp(float(candle["time"]), tz=IST) <= completed_cutoff
        ]
        for candle in completed:
            by_epoch.setdefault(float(candle["time"]), candle)
        candles = [by_epoch[key] for key in sorted(by_epoch)]
        additions = [c for c in completed if float(c["time"]) not in today_epochs]
        today_after = {epoch for epoch in by_epoch if datetime.fromtimestamp(epoch, tz=IST).date() == reference.date() and datetime.fromtimestamp(epoch, tz=IST) <= completed_cutoff}
        missing_after = [epoch for epoch in expected_epochs if epoch not in today_after]
        latest_epoch = max(by_epoch, default=None)
        latest_dt = datetime.fromtimestamp(latest_epoch, tz=IST) if latest_epoch is not None else None
        cursor.update({
            "latest_completed_1m": latest_dt.isoformat() if latest_dt else None,
            "latest_persisted_1m": latest_dt.isoformat() if latest_dt else None,
            "backlog_count": len(missing_after),
            "runtime_status": "CATCHING_UP",
            "source": "DHAN_INDEX_1M",
            "fetch_start": datetime.fromtimestamp(missing_before[0], tz=IST).isoformat(),
            "fetch_end": completed_cutoff.isoformat(),
            "persisted_at": reference.isoformat(),
        })
        updated = dict(existing); updated["candles"] = candles; updated["cursor"] = cursor; _save_canonical(path, updated)

        return {
            "status": "CATCHING_UP" if missing_after else "REPLAY_REQUIRED",
            "runtime_status": "CATCHING_UP",
            "added": len(additions),
            "invalid_removed": invalid_removed,
            "backlog_count": len(missing_after),
            "fetch_start": cursor["fetch_start"],
            "fetch_end": cursor["fetch_end"],
            "latest_completed_1m": latest_dt.isoformat() if latest_dt else None,
        }


def _fetch_window(client: Any, from_date: str, to_date: str) -> List[Dict[str, Any]]:
    result = client.get_intraday_candles(
        segment=NIFTY_SEGMENT,
        security_id=NIFTY_SECURITY_ID,
        instrument=NIFTY_INSTRUMENT,
        interval="1",
        from_date=from_date,
        to_date=to_date,
    )
    if not result.get("success"):
        return []
    raw = result.get("candles", [])
    # Keep only candles within NSE session (09:15–15:29 IST) with valid OHLCV
    out = []
    for c in raw:
        t = c.get("time")
        if t is None:
            continue
        dt = datetime.fromtimestamp(float(t), tz=IST)
        if (dt.hour, dt.minute) < NSE_OPEN:
            continue
        if (dt.hour, dt.minute) >= NSE_CLOSE:
            continue
        if any(c.get(k) is None for k in ("open", "high", "low", "close")):
            continue
        out.append({
            "time": float(t),
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
            "volume": float(c.get("volume") or 0.0),
        })
    return out


def backfill(
    from_date: date,
    to_date: date,
    canonical_path: Optional[Path] = None,
    client: Optional[Any] = None,
    sleep_between_calls: float = 0.25,
) -> Dict[str, Any]:
    """Backfill NIFTY 1m candles from from_date to to_date into canonical store.

    Returns summary dict with keys: added, skipped, total, earliest, latest.
    advisory_only=True, execution_influence=ZERO.
    """
    from src.broker.dhan_client import DhanClient

    if canonical_path is None:
        canonical_path = DEFAULT_CANONICAL_PATH
    if client is None:
        client = DhanClient()

    existing = _load_canonical(canonical_path)
    existing_candles: List[Dict] = existing.get("candles", [])

    # Build set of existing epochs
    existing_epochs: set = {c["time"] for c in existing_candles if "time" in c}

    fetched: List[Dict] = []
    windows = _date_windows(from_date, to_date, chunk_days=5)
    for from_str, to_str in windows:
        batch = _fetch_window(client, from_str, to_str)
        fetched.extend(batch)
        if sleep_between_calls > 0:
            _time.sleep(sleep_between_calls)

    new_candles = [c for c in fetched if c["time"] not in existing_epochs]
    added = len(new_candles)
    skipped = len(fetched) - added

    # Merge and sort by time
    all_candles = existing_candles + new_candles
    all_candles.sort(key=lambda c: c["time"])

    _save_canonical(canonical_path, {"candles": all_candles})

    total = len(all_candles)
    earliest = None
    latest   = None
    if all_candles:
        earliest = datetime.fromtimestamp(all_candles[0]["time"], tz=IST).isoformat()
        latest   = datetime.fromtimestamp(all_candles[-1]["time"], tz=IST).isoformat()

    return {
        "added": added,
        "skipped": skipped,
        "total": total,
        "earliest": earliest,
        "latest": latest,
        "windows_fetched": len(windows),
    }


if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="Backfill canonical NIFTY 1m candles")
    parser.add_argument("--from", dest="from_date", default="2026-05-26",
                        help="Start date YYYY-MM-DD (default: 2026-05-26 for 40 days before Jul 7)")
    parser.add_argument("--to", dest="to_date", default="2026-07-15",
                        help="End date YYYY-MM-DD (default: day before current canonical start)")
    parser.add_argument("--path", default=str(DEFAULT_CANONICAL_PATH))
    args = parser.parse_args()

    result = backfill(
        from_date=date.fromisoformat(args.from_date),
        to_date=date.fromisoformat(args.to_date),
        canonical_path=Path(args.path),
    )
    print(json.dumps(result, indent=2))
