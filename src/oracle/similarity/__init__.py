"""Transparent Phase-4 historical similarity and calibration."""

from .engine import (
    DEFAULT_DATASET_SPLIT, DEFAULT_OUTCOME_DEFINITION, DEFAULT_SAMPLE_POLICY, HistoricalDataset,
    SimilarityEngine, build_feature_vector_from_phase3,
)

__all__ = [
    "DEFAULT_DATASET_SPLIT", "DEFAULT_OUTCOME_DEFINITION", "DEFAULT_SAMPLE_POLICY", "HistoricalDataset",
    "SimilarityEngine", "build_feature_vector_from_phase3",
]
