from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.request import Request, urlopen


class SharedAiClientError(RuntimeError):
    pass


class SharedAiClient:
    """Server-owned AI provider client; no model key comes from clients."""

    def __init__(
        self, *, provider: str, base_url: str, model: str, api_key: str, opener: Callable[..., Any] | None = None
    ) -> None:
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self._opener = opener or urlopen

    def recommend(self, *, site: str, history: list[dict[str, object]], allowed_plays: list[str]) -> dict[str, object]:
        prompt = json.dumps({"site": site, "history": history, "allowed_plays": allowed_plays}, ensure_ascii=False)
        url, headers, payload = self._request_parts(prompt)
        request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
        try:
            with self._opener(request, timeout=30) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise SharedAiClientError(f"AI 请求失败: {exc}") from exc
        content = self._response_content(response_payload)
        try:
            result = json.loads(content)
        except json.JSONDecodeError as exc:
            raise SharedAiClientError("AI 返回不是严格 JSON") from exc
        play = str(result.get("play_type") or "")
        if result.get("action") == "bet" and play not in allowed_plays:
            raise SharedAiClientError("AI 返回玩法不在允许玩法")
        return result

    def _request_parts(self, prompt: str) -> tuple[str, dict[str, str], dict[str, object]]:
        if self.provider == "anthropic":
            return (
                f"{self.base_url}/v1/messages",
                {"Content-Type": "application/json", "X-Api-Key": self.api_key, "Anthropic-Version": "2023-06-01"},
                {"model": self.model, "max_tokens": 1024, "messages": [{"role": "user", "content": prompt}]},
            )
        return (
            f"{self.base_url}/chat/completions",
            {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            {"model": self.model, "temperature": 0, "messages": [{"role": "user", "content": prompt}]},
        )

    def _response_content(self, payload: dict[str, object]) -> str:
        if self.provider == "anthropic":
            for item in payload.get("content", []):
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    return item["text"]
        choices = payload.get("choices", [])
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
        raise SharedAiClientError("AI 返回没有文本内容")
