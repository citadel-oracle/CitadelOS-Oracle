"""Base Eye Adapter and Exact Price Quantization Utilities."""

from abc import ABC, abstractmethod
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Mapping, Optional, Tuple, Sequence

from src.eye.contracts import PriceAtom, EyeContractError
from src.eye.adapter_result import AdapterResult, AdapterDiagnostics


def quantize_price(native_val: float | int | str, quantum: str = "0.01") -> Tuple[PriceAtom, AdapterDiagnostics]:
    """Converts native float/int/str to PriceAtom via Decimal(str(native_val)).

    Never uses Decimal(float_val) directly to prevent binary float representation noise.
    """
    if isinstance(native_val, bool):
        raise EyeContractError("Boolean input rejected for price quantization")
    if isinstance(native_val, float):
        if not (-float("inf") < native_val < float("inf")):
            raise EyeContractError("NaN and Infinity prices are forbidden")

    str_val = str(native_val).strip()
    try:
        dec_val = Decimal(str_val)
        dec_quantum = Decimal(str(quantum))
    except (InvalidOperation, TypeError) as err:
        raise EyeContractError(f"Exact price conversion failed for value {native_val}") from err

    # Quantize ticks (ROUND_HALF_UP)
    ticks = int((dec_val / dec_quantum).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    quantized_atom = PriceAtom(ticks=ticks, quantum=str(dec_quantum.normalize()))

    # Calculate rounding delta
    exact_value = float(quantized_atom.value)
    delta = abs(float(dec_val) - exact_value)

    diag = AdapterDiagnostics(
        original_native_value=str_val,
        quantized_ticks=ticks,
        quantum=quantized_atom.quantum,
        rounding_delta=delta,
    )
    return quantized_atom, diag


class BaseEyeAdapter(ABC):
    @abstractmethod
    def adapt(
        self,
        native_output: Any,
        source_bars: Sequence[Mapping[str, Any]],
        instrument_identity: Any,
        timeframe: str,
        evaluation_context: Any,
        native_configuration: Optional[Mapping[str, Any]] = None,
        source_revision: str = "",
    ) -> AdapterResult:
        """Translates native engine output to canonical AdapterResult."""
        pass
