"""LLM classifiers and the config-driven fallback chain."""

import logging

from skywatch.providers.llm.base import (
    Classifier,
    ClassifierError,
    ClassifyRequest,
    LLMVerdict,
    parse_verdict,
)
from skywatch.providers.llm.gemini import GeminiClassifier
from skywatch.providers.llm.groq import GroqClassifier
from skywatch.providers.llm.ollama import OllamaClassifier
from skywatch.settings import LLMSettings

__all__ = [
    "Classifier",
    "ClassifierError",
    "ClassifyRequest",
    "GeminiClassifier",
    "GroqClassifier",
    "LLMVerdict",
    "OllamaClassifier",
    "build_classifier_chain",
    "parse_verdict",
]

logger = logging.getLogger(__name__)


def build_classifier_chain(
    settings: LLMSettings,
    *,
    gemini_api_key: str | None,
    groq_api_key: str | None,
) -> list[Classifier]:
    """Ordered classifiers to try per clip: primary provider, then fallbacks.

    ``none`` terminates the chain (prefilter-only from there on); providers
    whose credentials are missing are skipped with a warning rather than
    failing at runtime.
    """
    chain: list[Classifier] = []
    for name in [settings.provider, *settings.fallback]:
        if name == "none":
            break
        if name == "gemini":
            if not gemini_api_key:
                logger.warning("gemini in the classifier chain but GEMINI_API_KEY unset")
                continue
            chain.append(GeminiClassifier(api_key=gemini_api_key, model=settings.model))
        elif name == "groq":
            if not groq_api_key:
                logger.warning("groq in the classifier chain but GROQ_API_KEY unset")
                continue
            chain.append(GroqClassifier(api_key=groq_api_key, model=settings.groq_model))
        elif name == "ollama":
            chain.append(
                OllamaClassifier(base_url=settings.ollama_url, model=settings.ollama_model)
            )
    return chain
