"""E4A-D Test for Spot Candle Taxonomy Truth."""

import pytest
from src.eye.option_evidence.sources import DataClassification, SourceProvenance, SourceType


def test_spot_candles_cannot_be_promoted_to_option_candles():
    prov = SourceProvenance(
        source_type=SourceType.LOCAL_EXACT_CONTRACT_HISTORY,
        data_classification=DataClassification.UNDERLYING_SPOT_CANDLE,
    )
    assert prov.data_classification != DataClassification.EXACT_OPTION_CANDLE
