from __future__ import annotations

from app.services.ai_prediction_store import AiPredictionStore


def _record(store: AiPredictionStore, period: str, play_type: str, *, sent: bool = True) -> None:
    store.record_prediction(
        site="pc28",
        period=period,
        action="bet",
        play_type=play_type,
        confidence=72,
        quant_rationale="近 20 期频率偏高",
        reason="存在轻微统计优势",
        model="test-model",
        history_snapshot=[{"period": "99", "result": "小双"}],
        quant_snapshot={"sample_size": 20},
        status="sent" if sent else "recommended",
        sent=sent,
    )


def test_prediction_store_persists_json_and_updates_status(tmp_path):
    store = AiPredictionStore(tmp_path / "predictions.db")

    _record(store, "100", "大", sent=False)
    store.mark_sent("pc28", "100")

    record = store.recent_records("pc28", 1)[0]
    assert record.period == "100"
    assert record.sent is True
    assert record.status == "sent"
    assert record.history_snapshot == [{"period": "99", "result": "小双"}]
    assert record.quant_snapshot == {"sample_size": 20}


def test_prediction_store_settles_sent_bets_and_calculates_dual_accuracy(tmp_path):
    store = AiPredictionStore(tmp_path / "predictions.db")
    _record(store, "100", "大")
    _record(store, "101", "小双")
    _record(store, "102", "单")
    _record(store, "103", "大单", sent=False)

    assert store.settle("pc28", "100", "大双") is True
    assert store.settle("pc28", "101", "小双") is True
    assert store.settle("pc28", "102", "小双") is True
    assert store.settle("pc28", "103", "大单") is True

    summary = store.accuracy_summary("pc28", window=2)
    assert summary["settled_count"] == 3
    assert summary["overall"] == {
        "count": 3,
        "direction_hits": 2,
        "exact_hits": 1,
        "direction_accuracy": 2 / 3,
        "exact_accuracy": 1 / 3,
    }
    assert summary["short"] == {
        "window": 2,
        "count": 2,
        "direction_hits": 1,
        "exact_hits": 1,
        "direction_accuracy": 0.5,
        "exact_accuracy": 0.5,
    }
    assert summary["streak"] == {"result": "miss", "count": 1}

    unsent = next(record for record in store.recent_records("pc28", 10) if record.period == "103")
    assert unsent.actual_result == "大单"
    assert unsent.direction_hit is True
    assert unsent.exact_hit is True


def test_prediction_store_records_skip_and_failure_without_affecting_accuracy(tmp_path):
    store = AiPredictionStore(tmp_path / "predictions.db")
    store.record_prediction(
        site="pc28",
        period="200",
        action="skip",
        confidence=40,
        quant_rationale="样本熵较高",
        reason="没有显著优势",
        model="test-model",
        status="ai_skip",
    )
    store.record_prediction(
        site="pc28",
        period="201",
        action="error",
        reason="API timeout",
        model="test-model",
        status="failed",
    )

    assert [item.status for item in store.recent_records("pc28", 10)] == ["failed", "ai_skip"]
    assert store.accuracy_summary("pc28", window=20)["settled_count"] == 0


def test_prediction_store_builds_prompt_feedback_with_recent_results(tmp_path):
    store = AiPredictionStore(tmp_path / "predictions.db")
    _record(store, "300", "大")
    _record(store, "301", "小")
    store.settle("pc28", "300", "大单")
    store.settle("pc28", "301", "大双")

    context = store.performance_context("pc28", window=20, recent_limit=5)

    assert set(context) == {"overall", "short", "recent_predictions"}
    assert context["overall"]["direction_accuracy"] == 0.5
    assert context["short"]["window"] == 20
    assert context["recent_predictions"] == [
        {
            "period": "301",
            "play_type": "小",
            "confidence": 72,
            "actual_result": "大双",
            "direction_hit": False,
            "exact_hit": False,
        },
        {
            "period": "300",
            "play_type": "大",
            "confidence": 72,
            "actual_result": "大单",
            "direction_hit": True,
            "exact_hit": False,
        },
    ]
