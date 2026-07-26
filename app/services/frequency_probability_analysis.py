from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.models.auto_bet import DrawResult


COMPOSITE_PLAY_ORDER = ("小单", "大双", "小双", "大单")
PLAY_ORDER = ("小", "单", "大", "双", *COMPOSITE_PLAY_ORDER)


@dataclass(frozen=True)
class FrequencyProbabilityAnalysis:
    """Historical-frequency snapshot shared by the auto-bet engine and panel."""

    site: str
    period: str
    analyzed_at: datetime
    requested_history_count: int
    sample_count: int
    number_sample_count: int
    number_probabilities: dict[int, float]
    play_probabilities: dict[str, float]
    excluded_play: str
    selected_plays: tuple[str, ...]
    highest_selected_probability: float
    confidence_threshold: int
    should_bet: bool
    reason: str


class FrequencyProbabilityAnalyzer:
    """Calculate display probabilities and the deterministic three-door decision."""

    def analyze(
        self,
        site: str,
        results: list[DrawResult],
        *,
        history_count: int,
        confidence_threshold: int,
        target_period: str = "",
    ) -> FrequencyProbabilityAnalysis:
        requested_count = max(1, int(history_count))
        period = str(target_period or "").strip()
        eligible = self._eligible_results(results, period)[-requested_count:]
        composite_results = [result for result in eligible if result.result in COMPOSITE_PLAY_ORDER]
        numeric_totals = [result.total for result in eligible if isinstance(result.total, int)]

        composite_count = len(composite_results)
        counts = {play: 0 for play in PLAY_ORDER}
        for result in composite_results:
            composite = result.result
            counts[composite] += 1
            counts[composite[0]] += 1
            counts[composite[1]] += 1

        play_probabilities = {
            play: self._percentage(counts[play], composite_count)
            for play in PLAY_ORDER
        }
        number_probabilities = {
            target: self._percentage(sum(total == target for total in numeric_totals), len(numeric_totals))
            for target in (13, 14)
        }

        if composite_count == 0:
            return FrequencyProbabilityAnalysis(
                site=str(site), period=period, analyzed_at=datetime.now(),
                requested_history_count=requested_count, sample_count=0,
                number_sample_count=len(numeric_totals),
                number_probabilities=number_probabilities, play_probabilities=play_probabilities,
                excluded_play="", selected_plays=(), highest_selected_probability=0.0,
                confidence_threshold=int(confidence_threshold), should_bet=False,
                reason="没有可识别的复合玩法历史记录",
            )

        excluded_play = min(
            COMPOSITE_PLAY_ORDER,
            key=lambda play: (play_probabilities[play], COMPOSITE_PLAY_ORDER.index(play)),
        )
        selected_plays = tuple(play for play in COMPOSITE_PLAY_ORDER if play != excluded_play)
        highest_probability = max(play_probabilities[play] for play in selected_plays)
        threshold = int(confidence_threshold)
        should_bet = highest_probability >= threshold
        reason = (
            f"实际样本{composite_count}期，排除{excluded_play}({play_probabilities[excluded_play]:.1f}%)；"
            f"三门{'、'.join(selected_plays)}，最高{highest_probability:.1f}%"
        )
        if should_bet:
            reason += f"达到阈值{threshold}%"
        else:
            reason += f"未达到阈值{threshold}%"
        return FrequencyProbabilityAnalysis(
            site=str(site), period=period, analyzed_at=datetime.now(),
            requested_history_count=requested_count, sample_count=composite_count,
            number_sample_count=len(numeric_totals),
            number_probabilities=number_probabilities, play_probabilities=play_probabilities,
            excluded_play=excluded_play, selected_plays=selected_plays,
            highest_selected_probability=highest_probability,
            confidence_threshold=threshold, should_bet=should_bet, reason=reason,
        )

    @staticmethod
    def _eligible_results(results: list[DrawResult], target_period: str) -> list[DrawResult]:
        if not target_period:
            return list(results)
        if not target_period.isdigit():
            return []
        return [
            result for result in results
            if str(result.period or "").isdigit() and int(result.period) < int(target_period)
        ]

    @staticmethod
    def _percentage(count: int, denominator: int) -> float:
        return (count * 100.0 / denominator) if denominator else 0.0
