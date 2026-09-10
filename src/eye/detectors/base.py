"""Base Atomic Detector Abstract Interface."""

from abc import ABC, abstractmethod
from typing import Sequence
from src.eye.detectors.input_model import DetectorBar, DetectorContext
from src.eye.detectors.detector_result import DetectorResult


class BaseAtomicDetector(ABC):
    @abstractmethod
    def detect(
        self,
        bars: Sequence[DetectorBar],
        context: DetectorContext,
    ) -> DetectorResult:
        """Processes bars and context to produce deterministic DetectorResult."""
        pass
