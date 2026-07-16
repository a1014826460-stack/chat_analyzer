from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib.request import Request, urlopen

from app.models.auto_bet import DrawResult, StrategyConfig, allowed_play_types_for_config


VALID_PLAY_TYPES = frozenset({"大", "小", "单", "双", "大单", "小单", "大双", "小双"})
_SYSTEM_PROMPT = (
    "你是量化开奖分析助手。根据历史、量化特征和预测表现判断是否存在优势。"
    "若存在弱但具体的方向性证据，输出低置信度 bet；"
    "只有没有可验证方向依据时才 skip，不要仅因证据不强就跳过。"
    "confidence 必须是 0 至 100 的整数，表示量化优势的校准置信度。"
    "仅当 action=skip 时 confidence 可以为 0；action=bet 时 confidence 必须为 1 至 100，"
    "并且必须与 quant_rationale 的证据强度一致。"
    "bet 必须严格使用策略约束中的严格允许玩法，不能把单项玩法扩展为复合玩法。"
    "只能输出 JSON 对象，不要 Markdown 或其他文字："
    '{"action":"bet|skip","play_type":"玩法或空","confidence":72,'
    '"quant_rationale":"量化依据","reason":"简短结论"}。'
)


class AiBetClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class AiRecommendation:
    action: str
    play_type: str
    confidence: int
    quant_rationale: str
    reason: str


class AiBetClient:
    def __init__(self, opener: Callable[..., Any] | None = None, timeout_sec: int = 60) -> None:
        self._opener = opener or urlopen
        self._timeout_sec = timeout_sec

    def recommend(
        self,
        config: StrategyConfig,
        results: list[DrawResult],
        quant_context: dict[str, Any] | None = None,
        performance_context: dict[str, Any] | None = None,
    ) -> AiRecommendation:
        url, headers, payload = self._build_request(config, results, quant_context, performance_context)
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
        return self._parse_recommendation(
            self._response_text(config.ai_provider, response_payload),
            allowed_play_types_for_config(config),
        )

    def _build_request(
        self,
        config: StrategyConfig,
        results: list[DrawResult],
        quant_context: dict[str, Any] | None = None,
        performance_context: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        provider = str(config.ai_provider or "openai_compatible")
        base_url = str(config.ai_base_url or "").rstrip("/")
        if not base_url or not config.ai_model or not config.ai_api_key:
            raise AiBetClientError("请填写 AI Base URL、模型名和 API Key")
        user_prompt = self._user_prompt(config.site, results, quant_context, performance_context, config)
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
                    "max_tokens": 4096,
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
    def _user_prompt(
        site: str,
        results: list[DrawResult],
        quant_context: dict[str, Any] | None = None,
        performance_context: dict[str, Any] | None = None,
        config: StrategyConfig | None = None,
    ) -> str:
        history = [
            {"period": str(result.period), "result": str(result.result)}
            for result in results
        ]
        return (
            f"站点: {site}\n"
            f"最近开奖记录（旧到新）: {json.dumps(history, ensure_ascii=False)}\n"
            f"量化特征: {json.dumps(quant_context or {}, ensure_ascii=False)}\n"
            f"AI 历史表现: {json.dumps(performance_context or {}, ensure_ascii=False)}\n"
            f"策略约束: {json.dumps(_strategy_constraints(config), ensure_ascii=False)}"
        )

    @staticmethod
    def _response_text(provider: str, payload: Any) -> str:
        if not isinstance(payload, dict):
            raise AiBetClientError("AI 返回不是 JSON 对象")
        if provider == "anthropic":
            content = payload.get("content")
            if isinstance(content, str) and content.strip():
                return content
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, str) and item.strip():
                        return item
                    if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip():
                        return item["text"]
            block_types = [
                str(item.get("type") or "unknown")
                for item in content
                if isinstance(item, dict)
            ] if isinstance(content, list) else []
            stop_reason = str(payload.get("stop_reason") or "unknown")
            details = f"stop_reason={stop_reason}, content_blocks={','.join(block_types) or 'none'}"
            raise AiBetClientError(f"Anthropic 返回中没有文本内容 ({details})")
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str):
                return content
        raise AiBetClientError("OpenAI 兼容返回中没有消息内容")

    @staticmethod
    def _parse_recommendation(content: str, allowed_play_types: list[str] | None = None) -> AiRecommendation:
        try:
            value = json.loads(content.strip())
        except (AttributeError, json.JSONDecodeError) as exc:
            raise AiBetClientError("AI 返回不是严格 JSON 建议") from exc
        if not isinstance(value, dict):
            raise AiBetClientError("AI 建议必须是 JSON 对象")
        action = str(value.get("action") or "").strip().lower()
        play_type = str(value.get("play_type") or "").strip()
        quant_rationale = str(value.get("quant_rationale") or "").strip()
        reason = str(value.get("reason") or "").strip()
        try:
            confidence = min(100, max(0, int(float(value.get("confidence")))))
        except (TypeError, ValueError):
            raise AiBetClientError("AI 建议缺少合法置信度")
        if action not in {"bet", "skip"}:
            raise AiBetClientError(f"AI 返回非法 action: {action or '空'}")
        if action == "bet" and play_type not in VALID_PLAY_TYPES:
            raise AiBetClientError(f"AI 返回非法玩法: {play_type or '空'}")
        if action == "bet" and allowed_play_types is not None and play_type not in allowed_play_types:
            allowed_text = "、".join(allowed_play_types) or "无"
            raise AiBetClientError(f"AI 返回玩法不在当前允许玩法：{play_type}（允许：{allowed_text}）")
        if action == "bet" and confidence == 0:
            raise AiBetClientError("下注建议置信度必须为 1 至 100")
        if action == "skip":
            play_type = ""
        if not quant_rationale:
            raise AiBetClientError("AI 建议缺少量化依据")
        if not reason:
            raise AiBetClientError("AI 建议缺少理由")
        return AiRecommendation(
            action=action,
            play_type=play_type,
            confidence=confidence,
            quant_rationale=quant_rationale,
            reason=reason,
        )


def _strategy_constraints(config: StrategyConfig | None) -> dict[str, Any]:
    if config is None:
        return {}
    names = {
        "flat": "平推",
        "martingale": "固定倍投",
        "trend_following": "趋势反打",
    }
    constraints: dict[str, Any] = {
        "策略": names.get(config.strategy_type, config.strategy_type),
        "严格允许玩法": allowed_play_types_for_config(config),
    }
    if config.strategy_type == "trend_following":
        constraints["连续阈值"] = config.trigger_threshold
        constraints["观察窗口"] = config.observation_window
    return constraints
