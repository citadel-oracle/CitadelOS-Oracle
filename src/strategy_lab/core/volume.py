"""Stateless SMA volume confirmation."""

from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass(frozen=True)
class VolumeFilterResult:
    confirmed: bool
    average: Optional[float]
    threshold: Optional[float]


class VolumeFilter:
    @staticmethod
    def sma(values: Sequence[float], length: int) -> Optional[float]:
        if length < 1:
            raise ValueError("volume SMA length must be positive")
        if len(values) < length:
            return None
        window = [float(value) for value in values[-length:]]
        return sum(window) / length

    @classmethod
    def evaluate(
        cls,
        volumes: Sequence[float],
        *,
        length: int,
        multiplier: float,
        enabled: bool = True,
    ) -> VolumeFilterResult:
        if multiplier < 0:
            raise ValueError("volume multiplier cannot be negative")
        average = cls.sma(volumes, length)
        threshold = None if average is None else average * multiplier
        confirmed = not enabled or (
            bool(volumes) and threshold is not None and float(volumes[-1]) > threshold
        )
        return VolumeFilterResult(confirmed, average, threshold)
