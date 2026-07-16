"""LLM classifier provider tests (all HTTP via respx; no real calls)."""

import httpx
import pytest
import respx

from skywatch.db.enums import ApiProvider, ClassificationCategory, FrequencyCategory
from skywatch.providers.llm import build_classifier_chain
from skywatch.providers.llm.base import (
    ClassifierError,
    ClassifyRequest,
    LLMVerdict,
    parse_verdict,
)
from skywatch.providers.llm.gemini import GeminiClassifier
from skywatch.providers.llm.groq import GroqClassifier
from skywatch.providers.llm.ollama import OllamaClassifier
from skywatch.providers.llm.prompt import build_user_prompt
from skywatch.settings import LLMSettings

VERDICT_JSON = (
    '{"is_interesting": true, "category": "emergency", "confidence": 0.95,'
    ' "reason": "mayday call with engine failure"}'
)


def _request(text="mayday mayday mayday engine failure") -> ClassifyRequest:
    return ClassifyRequest(
        transcript=text,
        duration_s=9.9,
        frequency_label="Stansted Tower",
        frequency_category=FrequencyCategory.TOWER,
        prefilter_flags=["keyword:mayday"],
        asr_avg_logprob=-0.3,
    )


class TestParseVerdict:
    def test_parses_valid_json(self):
        verdict = parse_verdict(VERDICT_JSON, model="test-model")
        assert verdict == LLMVerdict(
            is_interesting=True,
            category=ClassificationCategory.EMERGENCY,
            confidence=0.95,
            reason="mayday call with engine failure",
            model="test-model",
        )

    def test_unknown_category_maps_to_other(self):
        verdict = parse_verdict(
            '{"is_interesting": true, "category": "alien", "confidence": 0.5, "reason": "?"}',
            model="m",
        )
        assert verdict.category is ClassificationCategory.OTHER

    def test_confidence_clamped(self):
        verdict = parse_verdict(
            '{"is_interesting": false, "category": "routine", "confidence": 1.7, "reason": "r"}',
            model="m",
        )
        assert verdict.confidence == 1.0

    def test_garbage_raises(self):
        with pytest.raises(ClassifierError):
            parse_verdict("not json at all", model="m")

    def test_missing_fields_raise(self):
        with pytest.raises(ClassifierError):
            parse_verdict('{"category": "routine"}', model="m")


class TestPrompt:
    def test_prompt_carries_context(self):
        prompt = build_user_prompt(_request())
        assert "mayday mayday mayday engine failure" in prompt
        assert "Stansted Tower" in prompt
        assert "keyword:mayday" in prompt

    def test_prompt_notes_poor_asr_quality(self):
        req = ClassifyRequest(
            transcript="garbled text",
            duration_s=4.0,
            frequency_label="Guard 121.500",
            frequency_category=FrequencyCategory.GUARD,
            prefilter_flags=[],
            asr_avg_logprob=-1.4,
        )
        assert "low" in build_user_prompt(req).lower()


@respx.mock
def test_gemini_classify():
    route = respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": VERDICT_JSON}]}}]},
        )
    )
    classifier = GeminiClassifier(api_key="test-key", model="gemini-2.5-flash-lite")
    verdict = classifier.classify(_request())
    assert verdict.is_interesting is True
    assert verdict.category is ClassificationCategory.EMERGENCY
    assert verdict.model == "gemini-2.5-flash-lite"
    request = route.calls.last.request
    assert request.headers["x-goog-api-key"] == "test-key"
    body = request.content.decode()
    assert "mayday" in body
    assert "responseMimeType" in body


@respx.mock
def test_gemini_http_error_raises_classifier_error():
    respx.post(url__regex=r"https://generativelanguage\.googleapis\.com/.*").mock(
        return_value=httpx.Response(500, text="boom")
    )
    classifier = GeminiClassifier(api_key="k", model="gemini-2.5-flash-lite")
    with pytest.raises(ClassifierError):
        classifier.classify(_request())


@respx.mock
def test_groq_classify():
    route = respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": VERDICT_JSON}}]})
    )
    classifier = GroqClassifier(api_key="groq-key", model="llama-3.3-70b-versatile")
    verdict = classifier.classify(_request())
    assert verdict.is_interesting is True
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer groq-key"
    assert b"json_object" in request.content


@respx.mock
def test_ollama_classify():
    route = respx.post("http://localhost:11434/api/chat").mock(
        return_value=httpx.Response(
            200, json={"message": {"role": "assistant", "content": VERDICT_JSON}}
        )
    )
    classifier = OllamaClassifier(base_url="http://localhost:11434", model="llama3.2")
    verdict = classifier.classify(_request())
    assert verdict.category is ClassificationCategory.EMERGENCY
    assert route.called


class TestChain:
    def test_none_provider_gives_empty_chain(self):
        chain = build_classifier_chain(
            LLMSettings(provider="none"), gemini_api_key=None, groq_api_key=None
        )
        assert chain == []

    def test_full_chain_order(self):
        chain = build_classifier_chain(
            LLMSettings(provider="gemini", fallback=["groq", "none"]),
            gemini_api_key="g",
            groq_api_key="q",
        )
        assert [c.provider for c in chain] == [ApiProvider.GEMINI, ApiProvider.GROQ]

    def test_providers_without_keys_are_skipped(self):
        chain = build_classifier_chain(
            LLMSettings(provider="gemini", fallback=["groq", "none"]),
            gemini_api_key=None,
            groq_api_key="q",
        )
        assert [c.provider for c in chain] == [ApiProvider.GROQ]

    def test_ollama_needs_no_key(self):
        chain = build_classifier_chain(
            LLMSettings(provider="ollama"), gemini_api_key=None, groq_api_key=None
        )
        assert [c.provider for c in chain] == [ApiProvider.OLLAMA]
