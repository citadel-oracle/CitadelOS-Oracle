"""Parity-tested pure Price Action port outside protected Oracle Development."""

from __future__ import annotations

from typing import Any, Mapping


SOURCE = "src/development/strategy.py:SimplePullbackDevelopment.generate"
PARITY_SCOPE = "DIRECTION_ENTRY_STOP_TARGET_AND_WAIT_REASON"


def evaluate_price_action(context: Mapping[str, Any]) -> dict[str, Any]:
    """Return the protected policy's deterministic result without runtime coupling."""

    indicators = context.get("indicators") if isinstance(context.get("indicators"), Mapping) else {}
    close = indicators.get("close")
    ema21 = indicators.get("ema_21")
    ema38 = indicators.get("ema_38")
    if any(value is None for value in (close, ema21, ema38)):
        return _wait("Missing indicator data")
    bias = str((context.get("kronos") or {}).get("bias") or "")
    if bias == "BULLISH" and close > ema21 and close > ema38:
        return _signal("BUY", close, ema21, context.get("confidence"), "Development Pullback: bullish Kronos + close above EMA21 and EMA38")
    if bias == "BEARISH" and close < ema21 and close < ema38:
        return _signal("SELL", close, ema21, context.get("confidence"), "Development Pullback: bearish Kronos + close below EMA21 and EMA38")
    return _wait("No development pullback setup")


def _signal(side: str, close: float, ema21: float, confidence: Any, reason: str) -> dict[str, Any]:
    risk = abs(float(close) - float(ema21))
    if risk <= 0:
        return _wait("Invalid risk")
    direction = 1 if side == "BUY" else -1
    return {
        "signal": side,
        "confidence": confidence,
        "entry": round(float(close), 2),
        "sl": round(float(ema21), 2),
        "target": round(float(close) + direction * risk * 2, 2),
        "reason": reason,
        "strategy": "Simple Pullback (Development)",
        "profile_version": "DEVELOPMENT_V1",
    }


def _wait(reason: str) -> dict[str, Any]:
    return {
        "signal": "WAIT",
        "confidence": 0,
        "entry": None,
        "sl": None,
        "target": None,
        "reason": reason,
        "strategy": "Simple Pullback (Development)",
        "profile_version": "DEVELOPMENT_V1",
    }
