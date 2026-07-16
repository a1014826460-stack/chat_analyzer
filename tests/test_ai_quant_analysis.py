from __future__ import annotations

from app.models.auto_bet import DrawResult
from app.services.ai_quant_analysis import build_quant_context


def test_quant_context_calculates_frequencies_streak_transition_entropy_and_concentration():
    results = [
        DrawResult(str(index), "pc28", label)
        for index, label in enumerate(
            ["大双", "小单", "大双", "大双", "小双", "小双", "小双"],
            1,
        )
    ]

    context = build_quant_context(results)

    assert context["sample_size"] == 7
    assert context["tail_streak"] == {"result": "小双", "count": 3}
    assert context["windows"]["20"]["counts"]["小双"] == 3
    assert context["windows"]["50"]["frequencies"]["大双"] == 3 / 7
    assert context["transition_from_latest"]["小双"] == 1.0
    assert context["entropy"] > 0
    assert context["concentration"] == 3 / 7


def test_quant_context_expands_composite_results_into_direction_frequencies():
    context = build_quant_context([
        DrawResult("1", "pc28", "大双"),
        DrawResult("2", "pc28", "小单"),
    ])

    counts = context["windows"]["20"]["counts"]
    assert counts["大"] == 1
    assert counts["小"] == 1
    assert counts["单"] == 1
    assert counts["双"] == 1


def test_quant_context_transition_probability_uses_only_latest_50_draws():
    old = [DrawResult(str(i), "pc28", "大单" if i % 2 == 0 else "小双") for i in range(10)]
    recent = [DrawResult(str(100 + i), "pc28", "小双") for i in range(50)]

    context = build_quant_context(old + recent)

    assert context["transition_from_latest"] == {"小双": 1.0}
