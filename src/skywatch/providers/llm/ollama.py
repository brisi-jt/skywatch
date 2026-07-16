"""Local Ollama classifier: zero-cost, zero-cloud fallback."""

import httpx

from skywatch.db.enums import ApiProvider
from skywatch.providers.llm.base import ClassifierError, ClassifyRequest, LLMVerdict, parse_verdict
from skywatch.providers.llm.prompt import SYSTEM_PROMPT, build_user_prompt


class OllamaClassifier:
    provider = ApiProvider.OLLAMA

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        http: httpx.Client | None = None,
        timeout_s: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self.model = model
        self._http = http or httpx.Client(timeout=timeout_s)

    def classify(self, request: ClassifyRequest) -> LLMVerdict:
        body = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(request)},
            ],
        }
        try:
            response = self._http.post(f"{self._base_url}/api/chat", json=body)
            response.raise_for_status()
            text = response.json()["message"]["content"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ClassifierError(f"ollama request failed: {exc}") from exc
        return parse_verdict(text, model=self.model)
