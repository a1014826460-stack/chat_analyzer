from __future__ import annotations

import math
from collections import Counter, defaultdict

from app.models.auto_bet import DrawResult


PLAY_TYPES = ("大", "小", "单", "双", "大单", "小单", "大双", "小双")


def build_quant_context(results: list[DrawResult]) -> dict[str, object]:
    ordered = sorted(results, key=_period_key)
    labels = [str(result.result or "").strip() for result in ordered if str(result.result or "").strip()]
    exact_counts = Counter(labels)
    total = len(labels)
    probabilities = [count / total for count in exact_counts.values()] if total else []
    entropy = -sum(probability * math.log2(probability) for probability in probabilities)
    concentration = max(probabilities, default=0.0)
    return {
        "sample_size": total,
        "windows": {
            str(size): _window_stats(labels[-size:])
            for size in (20, 50)
        },
        "tail_streak": _tail_streak(labels),
        "transition_from_latest": _transition_from_latest(labels[-50:]),
        "entropy": round(entropy, 6),
        "concentration": concentration,
    }


def _window_stats(labels: list[str]) -> dict[str, object]:
    counts = Counter()
    for label in labels:
        if label in PLAY_TYPES:
            counts[label] += 1
        if len(label) == 2:
            counts[label[0]] += 1
            counts[label[1]] += 1
    sample_size = len(labels)
    return {
        "sample_size": sample_size,
        "counts": {play: counts.get(play, 0) for play in PLAY_TYPES},
        "frequencies": {
            play: counts.get(play, 0) / sample_size if sample_size else 0.0
            for play in PLAY_TYPES
        },
    }


def _tail_streak(labels: list[str]) -> dict[str, object]:
    if not labels:
        return {"result": "", "count": 0}
    latest = labels[-1]
    count = 0
    for label in reversed(labels):
        if label != latest:
            break
        count += 1
    return {"result": latest, "count": count}


def _transition_from_latest(labels: list[str]) -> dict[str, float]:
    if not labels:
        return {}
    latest = labels[-1]
    following = Counter()
    for current, next_value in zip(labels, labels[1:]):
        if current == latest:
            following[next_value] += 1
    total = sum(following.values())
    return {
        label: count / total
        for label, count in following.items()
    } if total else {}


def _period_key(result: DrawResult) -> tuple[int, int | str]:
    period = str(result.period or "")
    return (0, int(period)) if period.isdigit() else (1, period)
