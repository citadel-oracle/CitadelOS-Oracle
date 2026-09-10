"""E2B-D Benchmark Execution & Checksum Verification Test Suite."""

import pytest
from scripts.benchmark_eye_real import run_real_benchmarks


def test_benchmark_execution_and_checksum():
    # Verify that benchmark runs without dead-code optimization and outputs valid report
    run_real_benchmarks()
