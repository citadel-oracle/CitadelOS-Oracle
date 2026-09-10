"""E4A-C Test for Local Dataset Classification Integrity."""

import pytest
from src.eye.option_evidence.sources import DataClassification, SourceProvenance, SourceType


def test_local_dataset_classifications():
    p_exact = SourceProvenance(
        source_type=SourceType.LOCAL_EXACT_CONTRACT_HISTORY,
        data_classification=DataClassification.EXACT_CONTRACT_CANDLE,
    )
    assert p_exact.data_classification == DataClassification.EXACT_CONTRACT_CANDLE

    p_proxy = SourceProvenance(
        source_type=SourceType.DHAN_ROLLING_EXPIRED_OPTIONS,
        data_classification=DataClassification.ROLLING_MONEYNESS_PROXY,
    )
    assert p_proxy.data_classification == DataClassification.ROLLING_MONEYNESS_PROXY
    assert p_proxy.data_classification != DataClassification.EXACT_CONTRACT_CANDLE
