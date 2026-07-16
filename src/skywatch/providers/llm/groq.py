"""Groq classifier via its OpenAI-compatible chat completions API."""

import httpx

from skywatch.db.enums import ApiProvider
from skywatch.providers.llm.base import ClassifierError, ClassifyRequest, LLMVerdict, parse_verdict
from skywatch.providers.llm.prompt import SYSTEM_PROMPT, build_user_prompt

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"


class GroqClassifier:
    provider = ApiProvider.GROQ

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
            "model": self.model,
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(request)},
            ],
        }
        try:
            response = self._http.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=body,
            )
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise ClassifierError(f"groq request failed: {exc}") from exc
        return parse_verdict(text, model=self.model)
