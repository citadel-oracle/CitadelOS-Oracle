"""E4A-D Test for Dataset Classification Truth."""

import pytest
from src.eye.option_evidence.sources import DataClassification, SourceProvenance, SourceType


def test_spot_candles_are_classified_as_underlying_spot_candle():
    prov = SourceProvenance(
        source_type=SourceType.LOCAL_EXACT_CONTRACT_HISTORY,
        data_classification=DataClassification.UNDERLYING_SPOT_CANDLE,
    )
    assert prov.data_classification == DataClassification.UNDERLYING_SPOT_CANDLE
    assert prov.data_classification != DataClassification.EXACT_OPTION_CANDLE
