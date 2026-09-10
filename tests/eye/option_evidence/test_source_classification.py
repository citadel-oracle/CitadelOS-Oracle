"""E4A Source Classification & Data Category Tests."""

import pytest
from src.eye.option_evidence.sources import SourceType, DataClassification, SourceProvenance


def test_source_provenance_classifications():
    prov_quote = SourceProvenance(
        source_type=SourceType.DHAN_MARKET_QUOTE,
        data_classification=DataClassification.EXACT_CONTRACT_QUOTE,
    )
    assert prov_quote.data_classification == DataClassification.EXACT_CONTRACT_QUOTE

    prov_rolling = SourceProvenance(
        source_type=SourceType.DHAN_ROLLING_EXPIRED_OPTIONS,
        data_classification=DataClassification.ROLLING_MONEYNESS_PROXY,
    )
    assert prov_rolling.data_classification == DataClassification.ROLLING_MONEYNESS_PROXY
    assert prov_rolling.data_classification != DataClassification.EXACT_CONTRACT_QUOTE
