from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class SharedAiClientError(RuntimeError):
    pass


class SharedAiClient:
    """Server-owned AI provider client; no model key comes from clients."""

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        model: str,
        api_key: str,
        opener: Callable[..., Any] | None = None,
        timeout_seconds: float = 30,
        max_retries: int = 1,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self._opener = opener or urlopen
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.max_retries = max(1, int(max_retries))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))

    def recommend_three_doors(
        self, *, site: str, history: list[dict[str, object]], selected_plays: list[str]
    ) -> dict[str, object]:
        prompt = json.dumps({
            "instruction": "仅判断是否执行整组三门；不可修改三门内容。输出严格 JSON："
            '{"action":"execute|skip","confidence":0-100,"reason":"简短原因"}',
            "site": site,
            "history": history,
            "selected_plays": selected_plays,
        }, ensure_ascii=False)
        url, headers, payload = self._request_parts(prompt)
        request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                with self._opener(request, timeout=self.timeout_seconds) as response:
                    response_payload = json.loads(response.read().decode("utf-8"))
                break
            except HTTPError as exc:
                if exc.code in {401, 403}:
                    raise SharedAiClientError("服务器 AI 密钥无效或鉴权失败，请检查后端 AI_API_KEY / AI_PROVIDER / AI_BASE_URL 配置") from exc
                raise SharedAiClientError(f"AI 请求失败: HTTP {exc.code} {exc.reason}") from exc
            except Exception as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_backoff_seconds)
                    continue
                raise SharedAiClientError(f"AI 请求失败: {exc}") from exc
        else:  # pragma: no cover
            raise SharedAiClientError(f"AI 请求失败: {last_error}")
        content = self._response_content(response_payload)
        try:
            result = json.loads(content)
        except json.JSONDecodeError as exc:
            raise SharedAiClientError("AI 返回不是严格 JSON") from exc
        action = str(result.get("action") or "").strip().lower()
        if action not in {"execute", "skip"}:
            raise SharedAiClientError("AI 返回非法执行决策")
        try:
            confidence = min(100, max(0, int(float(result.get("confidence")))))
        except (TypeError, ValueError) as exc:
            raise SharedAiClientError("AI 返回缺少合法置信度") from exc
        reason = str(result.get("reason") or "").strip()
        if not reason:
            raise SharedAiClientError("AI 返回缺少决策原因")
        result = {"action": action, "confidence": confidence, "reason": reason}
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
