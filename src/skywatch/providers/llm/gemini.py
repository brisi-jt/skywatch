"""Gemini classifier via the Generative Language REST API (structured JSON)."""

import httpx

from skywatch.db.enums import ApiProvider
from skywatch.providers.llm.base import ClassifierError, ClassifyRequest, LLMVerdict, parse_verdict
from skywatch.providers.llm.prompt import SYSTEM_PROMPT, VERDICT_JSON_SCHEMA, build_user_prompt

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiClassifier:
    provider = ApiProvider.GEMINI

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        http: httpx.Client | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._http = http or httpx.Client(timeout=timeout_s)

    def classify(self, request: ClassifyRequest) -> LLMVerdict:
        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": build_user_prompt(request)}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": VERDICT_JSON_SCHEMA,
                "temperature": 0.0,
            },
        }
        try:
            response = self._http.post(
                f"{self._base_url}/models/{self.model}:generateContent",
                headers={"x-goog-api-key": self._api_key},
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise ClassifierError(f"gemini request failed: {exc}") from exc
        return parse_verdict(text, model=self.model)

    def narrate(self, system_prompt: str, user_prompt: str) -> str:
        """Free-text generation for the daily narrative; raises on failure."""
        body = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"temperature": 0.4},
        }
        try:
            response = self._http.post(
                f"{self._base_url}/models/{self.model}:generateContent",
                headers={"x-goog-api-key": self._api_key},
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
            return str(payload["candidates"][0]["content"]["parts"][0]["text"])
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise ClassifierError(f"gemini narrative request failed: {exc}") from exc
