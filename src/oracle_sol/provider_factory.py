"""Reasoning Provider Interface & Factory (P0.3B / Gemini Activation).

Provides a unified interface dispatching to either:
- GeminiModelAdapter (Google Gemini 3.7 Flash - default)
- SolModelAdapter (OpenAI GPT-5.6 Sol)
Both consume the identical SolEvidenceSnapshot, ActiveMarketStory, and thesis contracts.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from src.oracle_sol.gemini_adapter import GeminiModelAdapter
from src.oracle_sol.groq_adapter import GroqBrainAdapter
from src.oracle_sol.local_model_adapter import OllamaQwenAdapter
from src.oracle_sol.model_adapter import SolModelAdapter


def get_reasoning_adapter(provider: Optional[str] = None) -> Any:
    """Factory returning active reasoning adapter based on CITADEL_REASONING_PROVIDER or argument."""
    active_provider = (provider or os.getenv("CITADEL_REASONING_PROVIDER", "groq")).strip().lower()

    if active_provider in {"groq", "cloud", "production"}:
        return GroqBrainAdapter()
    elif active_provider in {"qwen", "qwen3.5", "local", "ollama"}:
        return OllamaQwenAdapter()
    elif active_provider in {"openai", "gpt", "gpt-5.6", "sol"}:
        return SolModelAdapter()
    else:
        return GeminiModelAdapter(configured_model="gemini-3.7-flash")
