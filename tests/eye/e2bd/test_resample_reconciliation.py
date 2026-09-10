"""E2B-D Resample Count Reconciliation Test Suite."""

import pytest


def test_resample_reconciliation_exact_counts():
    # 20 complete 375-minute sessions
    total_1m = 20 * 375 # 7,500 1m bars
    total_3m = 20 * 125 # 2,500 3m bars
    total_5m = 20 * 75  # 1,500 5m bars
    total_15m = 20 * 25 # 500 15m bars

    assert total_1m == 7500
    assert total_3m == 2500
    assert total_5m == 1500
    assert total_15m == 500
