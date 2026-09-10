"""E4A-E Test for Explicit Multi-Timestamp Model."""

from datetime import datetime, timezone
import pytest
from src.eye.option_evidence.sources import SourceProvenance, SourceType, DataClassification


def test_timestamp_fields_preserved():
    now = datetime(2026, 8, 7, 9, 15, tzinfo=timezone.utc)
    prov = SourceProvenance(
        source_type=SourceType.DHAN_MARKET_QUOTE,
        data_classification=DataClassification.EXACT_OPTION_QUOTE,
        exchange_timestamp=now,
        received_at=now,
        parsed_at=now,
    )
    assert prov.exchange_timestamp == now
    assert prov.received_at == now
    assert prov.parsed_at == now
