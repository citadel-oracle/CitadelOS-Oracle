"""E4A-D Test for Dedicated Option Evidence Benchmark Work."""

import pytest
from scripts.benchmark_eye_e4a import run_e4a_benchmarks


def test_dedicated_option_evidence_benchmark_execution():
    res = run_e4a_benchmarks()
    assert res == "PASS"
