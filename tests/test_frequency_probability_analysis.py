from __future__ import annotations

from app.models.auto_bet import DrawResult
from app.services.frequency_probability_analysis import FrequencyProbabilityAnalyzer


def test_analyzer_derives_number_and_all_play_probabilities():
    analysis = FrequencyProbabilityAnalyzer().analyze(
        "pc28",
        [
            DrawResult("1", "pc28", "小单", total=13),
            DrawResult("2", "pc28", "大双", total=14),
            DrawResult("3", "pc28", "大单", total=15),
            DrawResult("4", "pc28", "小双", total=12),
        ],
        history_count=20,
        confidence_threshold=60,
    )

    assert analysis.sample_count == 4
    assert analysis.number_sample_count == 4
    assert analysis.number_probabilities == {13: 25.0, 14: 25.0}
    assert analysis.play_probabilities == {
        "小": 50.0,
        "单": 50.0,
        "大": 50.0,
        "双": 50.0,
        "小单": 25.0,
        "大双": 25.0,
        "小双": 25.0,
        "大单": 25.0,
    }
    assert analysis.excluded_play == "小单"
    assert analysis.selected_plays == ("大双", "小双", "大单")
    assert analysis.highest_selected_probability == 25.0
    assert analysis.should_bet is False


def test_analyzer_filters_target_period_and_uses_any_selected_play_for_threshold():
    analysis = FrequencyProbabilityAnalyzer().analyze(
        "pc28",
        [
            DrawResult("1000", "pc28", "大单", total=15),
            DrawResult("1001", "pc28", "大单", total=15),
            DrawResult("1002", "pc28", "小双", total=12),
        ],
        history_count=20,
        confidence_threshold=60,
        target_period="1002",
    )

    assert analysis.sample_count == 2
    assert analysis.excluded_play == "小单"
    assert analysis.selected_plays == ("大双", "小双", "大单")
    assert analysis.highest_selected_probability == 100.0
    assert analysis.should_bet is True


def test_analyzer_uses_fixed_order_when_composite_probabilities_tie():
    analysis = FrequencyProbabilityAnalyzer().analyze(
        "pc28",
        [
            DrawResult("1", "pc28", "小单"),
            DrawResult("2", "pc28", "大双"),
            DrawResult("3", "pc28", "小双"),
            DrawResult("4", "pc28", "大单"),
        ],
        history_count=20,
        confidence_threshold=0,
    )

    assert analysis.excluded_play == "小单"
    assert analysis.selected_plays == ("大双", "小双", "大单")
    assert analysis.should_bet is True


def test_analyzer_uses_actual_available_sample_and_skips_unknown_results():
    analysis = FrequencyProbabilityAnalyzer().analyze(
        "pc28",
        [
            DrawResult("1", "pc28", "未知", total=13),
            DrawResult("2", "pc28", "小单", total=None),
        ],
        history_count=20,
        confidence_threshold=50,
    )

    assert analysis.sample_count == 1
    assert analysis.number_sample_count == 1
    assert analysis.number_probabilities == {13: 100.0, 14: 0.0}
    assert analysis.should_bet is True
