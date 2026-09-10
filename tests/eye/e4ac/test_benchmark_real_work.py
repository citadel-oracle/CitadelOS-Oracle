"""E4A-C Test for Real Benchmark Execution Work."""

import pytest
from scripts.benchmark_eye_e3e_real import run_e3e_benchmarks


def test_benchmark_execution_real_work():
    res = run_e3e_benchmarks()
    assert res == "PASS"
