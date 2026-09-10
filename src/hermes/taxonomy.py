"""Central India/global HERMES event taxonomy and default scope."""

from __future__ import annotations

from dataclasses import dataclass

from src.hermes.models import AffectedScope, EventType, Impact


@dataclass(frozen=True)
class TaxonomyDefinition:
    event_type: EventType
    impact: Impact
    scope: AffectedScope
    tags: tuple[str, ...]


INDIA_SCOPE = AffectedScope(
    country="IN",
    market="INDIA",
    indices=("NIFTY", "BANKNIFTY"),
    currency="INR",
)
US_SCOPE = AffectedScope(
    country="US",
    market="US",
    indices=("S&P500", "NASDAQ"),
    currency="USD",
    global_scope=True,
)
GLOBAL_SCOPE = AffectedScope(market="GLOBAL", global_scope=True)


EVENT_TAXONOMY: dict[str, TaxonomyDefinition] = {
    "RBI_RATE_DECISION": TaxonomyDefinition(EventType.CENTRAL_BANK, Impact.CRITICAL, INDIA_SCOPE, ("RBI", "RATE_DECISION")),
    "RBI_SPEECH": TaxonomyDefinition(EventType.CENTRAL_BANK, Impact.MEDIUM, INDIA_SCOPE, ("RBI", "SPEECH")),
    "INDIA_CPI": TaxonomyDefinition(EventType.ECONOMIC, Impact.HIGH, INDIA_SCOPE, ("CPI", "INFLATION")),
    "INDIA_WPI": TaxonomyDefinition(EventType.ECONOMIC, Impact.MEDIUM, INDIA_SCOPE, ("WPI", "INFLATION")),
    "INDIA_PMI": TaxonomyDefinition(EventType.ECONOMIC, Impact.MEDIUM, INDIA_SCOPE, ("PMI",)),
    "INDIA_GDP": TaxonomyDefinition(EventType.ECONOMIC, Impact.HIGH, INDIA_SCOPE, ("GDP",)),
    "INDIA_IIP": TaxonomyDefinition(EventType.ECONOMIC, Impact.MEDIUM, INDIA_SCOPE, ("IIP",)),
    "INDIA_BUDGET": TaxonomyDefinition(EventType.POLITICAL, Impact.CRITICAL, INDIA_SCOPE, ("BUDGET",)),
    "INDIA_ELECTION_RESULT": TaxonomyDefinition(EventType.POLITICAL, Impact.CRITICAL, INDIA_SCOPE, ("ELECTION",)),
    "SEBI_REGULATORY_EVENT": TaxonomyDefinition(EventType.REGULATORY, Impact.HIGH, INDIA_SCOPE, ("SEBI", "REGULATION")),
    "EXCHANGE_CIRCULAR": TaxonomyDefinition(EventType.MARKET_STRUCTURE, Impact.MEDIUM, INDIA_SCOPE, ("EXCHANGE", "CIRCULAR")),
    "FED_RATE_DECISION": TaxonomyDefinition(EventType.CENTRAL_BANK, Impact.CRITICAL, US_SCOPE, ("FED", "RATE_DECISION")),
    "FOMC_MINUTES": TaxonomyDefinition(EventType.CENTRAL_BANK, Impact.HIGH, US_SCOPE, ("FOMC", "MINUTES")),
    "US_CPI": TaxonomyDefinition(EventType.ECONOMIC, Impact.HIGH, US_SCOPE, ("CPI", "INFLATION")),
    "US_PPI": TaxonomyDefinition(EventType.ECONOMIC, Impact.MEDIUM, US_SCOPE, ("PPI", "INFLATION")),
    "US_NFP": TaxonomyDefinition(EventType.ECONOMIC, Impact.HIGH, US_SCOPE, ("NFP", "JOBS")),
    "US_UNEMPLOYMENT": TaxonomyDefinition(EventType.ECONOMIC, Impact.HIGH, US_SCOPE, ("UNEMPLOYMENT", "JOBS")),
    "US_GDP": TaxonomyDefinition(EventType.ECONOMIC, Impact.HIGH, US_SCOPE, ("GDP",)),
    "US_PMI": TaxonomyDefinition(EventType.ECONOMIC, Impact.MEDIUM, US_SCOPE, ("PMI",)),
    "ECB_RATE_DECISION": TaxonomyDefinition(EventType.CENTRAL_BANK, Impact.HIGH, GLOBAL_SCOPE, ("ECB", "RATE_DECISION")),
    "BOE_RATE_DECISION": TaxonomyDefinition(EventType.CENTRAL_BANK, Impact.HIGH, GLOBAL_SCOPE, ("BOE", "RATE_DECISION")),
    "GEOPOLITICAL_EVENT": TaxonomyDefinition(EventType.GEOPOLITICAL, Impact.HIGH, GLOBAL_SCOPE, ("GEOPOLITICAL",)),
    "MAJOR_ELECTION_OUTCOME": TaxonomyDefinition(EventType.POLITICAL, Impact.HIGH, GLOBAL_SCOPE, ("ELECTION",)),
    "MAJOR_TARIFF_ANNOUNCEMENT": TaxonomyDefinition(EventType.POLITICAL, Impact.HIGH, GLOBAL_SCOPE, ("TARIFF", "TRADE")),
    "OFFICIAL_SOCIAL_MEDIA_STATEMENT": TaxonomyDefinition(EventType.SOCIAL_MEDIA, Impact.HIGH, GLOBAL_SCOPE, ("OFFICIAL_POST",)),
}


def taxonomy_for(key: str | None) -> TaxonomyDefinition | None:
    return EVENT_TAXONOMY.get(str(key or "").strip().upper())
