"""Read-only source/verification/time boundary for the cockpit. No market inference."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from zoneinfo import ZoneInfo


def timestamp(value: Any):
    if not isinstance(value, str) or len(value) <= 10:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            result = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
    return result.astimezone(timezone.utc)


def project_world_context(events, quotes, health, now=None):
    """Only verified, timestamped items enter the main surface.

    A source tier, HTTP fetch, hash alone, or market-open flag is not verification.
    Expiry must come from the verifier; no guessed news TTL. Refresh liveness uses
    the existing poll cadence, not a trading threshold.
    """
    now = now or datetime.now(timezone.utc)
    refreshed = timestamp(health.get("last_successful_refresh_at"))
    cadence = health.get("poll_cadence_seconds", 300)
    refresh_age = (now - refreshed).total_seconds() if refreshed else None
    refresh_current = refresh_age is not None and 0 <= refresh_age <= cadence

    def classify(item, quote=False):
        item = dict(item)
        record = item.get("verification_record") or {}
        if not isinstance(record, dict):
            record = {}
        published = timestamp(item.get("provider_timestamp" if quote else "published_at"))
        retrieved = timestamp(item.get("retrieved_at"))
        checked = timestamp(record.get("checked_at"))
        expires = timestamp(record.get("valid_until"))
        provider = item.get("provider")
        if provider in ("rbi", "sebi", "mospi"):
            provider = "official_india"
        elif provider == "upstox":
            provider = "twelve_data"
        source_checked = timestamp((health.get("provider_success_at") or {}).get(provider))
        source_current = source_checked is not None and 0 <= (now - source_checked).total_seconds() <= cadence
        verified = (item.get("verification_status") == "VERIFIED" and record.get("status") == "MATCH"
            and bool(record.get("verifier_id")) and bool(item.get("raw_hash"))
            and record.get("payload_hash") == item.get("raw_hash") and checked is not None and checked <= now)
        status, reason = "UNAVAILABLE", "VERIFICATION_NOT_PROVEN"
        if verified:
            if not published or not retrieved or published > retrieved or retrieved > now:
                reason = "SOURCE_TIME_NOT_PROVEN"
            elif not expires:
                reason = "VALIDITY_WINDOW_NOT_PROVEN"
            elif expires < now or not refresh_current or not source_current:
                status, reason = "STALE", "SOURCE_REFRESH_OR_VALIDITY_EXPIRED"
            elif quote and item.get("data_age") not in ("LIVE", "SESSION_LAST"):
                reason = "SOURCE_SESSION_NOT_PROVEN"
            elif item.get("event_type") in ("GLOBAL_SHOCK_RADAR", "MACRO_DATA_CALENDAR") or item.get("verification_tier") == "TIER_C_GLOBAL_RADAR":
                reason = "RAW_CONTEXT_DETAIL_ONLY"
            else:
                status, reason = (item.get("data_age", "LIVE") if quote else "LIVE"), None

        if not quote and not item.get("category_context"):
            tags = item.get("market_tags", [])
            if "RBI" in tags:
                item["category_context"] = "MONETARY_POLICY_BANKING"
            elif "SEBI" in tags:
                item["category_context"] = "SECURITIES_REGULATION"
            elif "NIFTY" in tags:
                item["category_context"] = "BENCHMARK_EQUITY_INDEX"
            elif item.get("provider") == "official_india":
                item["category_context"] = "OFFICIAL_REGULATORY_DISCLOSURE"
            elif item.get("country") == "IN":
                item["category_context"] = "DOMESTIC_FINANCIAL_MARKETS"
            else:
                item["category_context"] = "GLOBAL_MACRO_CONTEXT"

        item.update(display_status=status, display_reason=reason,
                    session_context=status,
                    verification_status="VERIFIED" if verified else "UNVERIFIED",
                    age_seconds=(now - published).total_seconds() if published and published <= now else None,
                    retrieved_age_seconds=(now - retrieved).total_seconds() if retrieved and retrieved <= now else None,
                    published_at_utc=published.isoformat() if published else None,
                    retrieved_at_utc=retrieved.isoformat() if retrieved else None)
        return item

    event_rows = [classify(event) for event in events]
    quote_rows = [classify(quote, True) for quote in quotes]
    usable_events = [row for row in event_rows if row["display_status"] in ("LIVE", "SESSION_LAST")]
    usable_quotes = [row for row in quote_rows if row["display_status"] in ("LIVE", "SESSION_LAST")]
    usable_events.sort(key=lambda row: row["published_at_utc"], reverse=True)
    # Primary news is today's verified context, not a re-fetched old headline.
    # Relevance uses provider-supplied geography/tags only; no invented impact score.
    today = now.astimezone(ZoneInfo("Asia/Kolkata")).date()
    top_stories = [row for row in usable_events
        if timestamp(row["published_at_utc"]).astimezone(ZoneInfo("Asia/Kolkata")).date() == today
        and (row.get("country") == "IN" or row.get("market_tags"))]
    top_stories.sort(key=lambda row: row.get("country") == "IN", reverse=True)
    if not top_stories and usable_events:
        india_events = [row for row in usable_events if (row.get("country") == "IN" or row.get("market_tags"))]
        top_stories = (india_events if india_events else usable_events)[:2]
    else:
        top_stories = top_stories[:2]
    usable = usable_events + usable_quotes
    status = ("LIVE" if any(row["display_status"] == "LIVE" for row in usable) else
              "SESSION_LAST" if usable else
              "STALE" if any(row["display_status"] == "STALE" for row in event_rows + quote_rows) else "UNAVAILABLE")
    return {"status": status, "headline": usable_events[0] if usable_events else None,
            "top_stories": top_stories,
            "story_selection": "TODAY_IST_VERIFIED_INDIA_THEN_TAGGED_GLOBAL_NEWEST",
            "quotes": usable_quotes, "events": event_rows, "quote_details": quote_rows,
            "last_successful_refresh_at": health.get("last_successful_refresh_at"),
            "refresh_age_seconds": refresh_age if refresh_age is not None and refresh_age >= 0 else None,
            "refresh_status": "CURRENT" if refresh_current else "STALE" if refreshed else "UNAVAILABLE",
            "refresh_receipt_id": health.get("refresh_receipt_id") if refresh_current else None,
            "poll_cadence_seconds": cadence,
            "unavailable_reason": None if usable else "No verified, time-valid context is available. See source details."}
