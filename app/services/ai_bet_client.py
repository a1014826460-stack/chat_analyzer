from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib.request import Request, urlopen

from app.models.auto_bet import DrawResult, StrategyConfig


VALID_PLAY_TYPES = frozenset({"大", "小", "单", "双", "大单", "小单", "大双", "小双"})
_SYSTEM_PROMPT = (
    "你是开奖历史分析助手。仅根据提供的历史结果给出一个下注玩法建议。"
    "只能从 大、小、单、双、大单、小单、大双、小双 中选择。"
    "只能输出 JSON 对象，不要 Markdown 或其他文字："
    '{"play_type":"玩法","reason":"简短理由"}。'
)


class AiBetClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class AiRecommendation:
    play_type: str
    reason: str


class AiBetClient:
    def __init__(self, opener: Callable[..., Any] | None = None, timeout_sec: int = 20) -> None:
        self._opener = opener or urlopen
        self._timeout_sec = timeout_sec

    def recommend(self, config: StrategyConfig, results: list[DrawResult]) -> AiRecommendation:
        url, headers, payload = self._build_request(config, results)
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with self._opener(request, timeout=self._timeout_sec) as response:
                raw_response = response.read().decode("utf-8")
            response_payload = json.loads(raw_response)
        except Exception as exc:
            raise AiBetClientError(f"AI 请求失败: {exc}") from exc
        return self._parse_recommendation(self._response_text(config.ai_provider, response_payload))

    def _build_request(self, config: StrategyConfig, results: list[DrawResult]) -> tuple[str, dict[str, str], dict[str, Any]]:
        provider = str(config.ai_provider or "openai_compatible")
        base_url = str(config.ai_base_url or "").rstrip("/")
        if not base_url or not config.ai_model or not config.ai_api_key:
            raise AiBetClientError("请填写 AI Base URL、模型名和 API Key")
        user_prompt = self._user_prompt(config.site, results)
        if provider == "anthropic":
            return (
                f"{base_url}/v1/messages",
                {
                    "content-type": "application/json",
                    "x-api-key": config.ai_api_key,
                    "anthropic-version": "2023-06-01",
                },
                {
                    "model": config.ai_model,
                    "max_tokens": 300,
                    "system": _SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": user_prompt}],
                },
            )
        return (
            f"{base_url}/chat/completions",
            {
                "content-type": "application/json",
                "authorization": f"Bearer {config.ai_api_key}",
            },
            {
                "model": config.ai_model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )

    @staticmethod
    def _user_prompt(site: str, results: list[DrawResult]) -> str:
        history = [
            {"period": str(result.period), "result": str(result.result)}
            for result in results
        ]
        return f"站点: {site}\n最近开奖记录（旧到新）: {json.dumps(history, ensure_ascii=False)}"

    @staticmethod
    def _response_text(provider: str, payload: Any) -> str:
        if not isinstance(payload, dict):
            raise AiBetClientError("AI 返回不是 JSON 对象")
        if provider == "anthropic":
            content = payload.get("content")
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                        return item["text"]
            raise AiBetClientError("Anthropic 返回中没有文本内容")
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str):
                return content
        raise AiBetClientError("OpenAI 兼容返回中没有消息内容")

    @staticmethod
    def _parse_recommendation(content: str) -> AiRecommendation:
        try:
            value = json.loads(content.strip())
        except (AttributeError, json.JSONDecodeError) as exc:
            raise AiBetClientError("AI 返回不是严格 JSON 建议") from exc
        if not isinstance(value, dict):
            raise AiBetClientError("AI 建议必须是 JSON 对象")
        play_type = str(value.get("play_type") or "").strip()
        reason = str(value.get("reason") or "").strip()
        if play_type not in VALID_PLAY_TYPES:
            raise AiBetClientError(f"AI 返回非法玩法: {play_type or '空'}")
        if not reason:
            raise AiBetClientError("AI 建议缺少理由")
        return AiRecommendation(play_type=play_type, reason=reason)
