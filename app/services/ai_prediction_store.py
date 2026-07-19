from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


_DDL = """
CREATE TABLE IF NOT EXISTS ai_predictions (
    site               TEXT NOT NULL,
    period             TEXT NOT NULL,
    action             TEXT NOT NULL,
    play_type          TEXT NOT NULL DEFAULT '',
    confidence         INTEGER NOT NULL DEFAULT 0,
    quant_rationale    TEXT NOT NULL DEFAULT '',
    reason             TEXT NOT NULL DEFAULT '',
    model              TEXT NOT NULL DEFAULT '',
    history_snapshot   TEXT NOT NULL DEFAULT '[]',
    quant_snapshot     TEXT NOT NULL DEFAULT '{}',
    sent               INTEGER NOT NULL DEFAULT 0,
    actual_result      TEXT NOT NULL DEFAULT '',
    direction_hit      INTEGER,
    exact_hit          INTEGER,
    status             TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    settled_at         TEXT,
    PRIMARY KEY (site, period)
);
CREATE INDEX IF NOT EXISTS idx_ai_predictions_site_created
    ON ai_predictions(site, created_at DESC);
CREATE TABLE IF NOT EXISTS auto_bet_sent_groups (
    site               TEXT NOT NULL,
    period             TEXT NOT NULL,
    group_id           TEXT NOT NULL,
    sent_at            TEXT NOT NULL,
    PRIMARY KEY (site, period, group_id)
);
CREATE TABLE IF NOT EXISTS auto_bet_pending_rounds (
    site               TEXT NOT NULL,
    period             TEXT NOT NULL,
    bets               TEXT NOT NULL,
    strategy_type      TEXT NOT NULL,
    martingale_step    INTEGER NOT NULL,
    odds               TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    PRIMARY KEY (site, period)
);
"""


@dataclass(frozen=True)
class AiPredictionRecord:
    site: str
    period: str
    action: str
    play_type: str
    confidence: int
    quant_rationale: str
    reason: str
    model: str
    history_snapshot: list[dict[str, Any]]
    quant_snapshot: dict[str, Any]
    sent: bool
    actual_result: str
    direction_hit: bool | None
    exact_hit: bool | None
    status: str
    created_at: datetime
    settled_at: datetime | None


@dataclass(frozen=True)
class AutoBetPendingRoundRecord:
    site: str
    period: str
    bets: list[dict[str, Any]]
    strategy_type: str
    martingale_step: int
    odds: dict[str, float]


class AiPredictionStore:
    """SQLite history for AI recommendations and their settled outcomes."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._lock = threading.RLock()
        self._init_db()

    def record_prediction(
        self,
        *,
        site: str,
        period: str,
        action: str,
        play_type: str = "",
        confidence: int = 0,
        quant_rationale: str = "",
        reason: str = "",
        model: str = "",
        history_snapshot: list[dict[str, Any]] | None = None,
        quant_snapshot: dict[str, Any] | None = None,
        status: str = "recommended",
        sent: bool = False,
    ) -> None:
        created_at = datetime.now().isoformat()
        values = (
            str(site), str(period), str(action), str(play_type), int(confidence),
            str(quant_rationale), str(reason), str(model),
            json.dumps(history_snapshot or [], ensure_ascii=False),
            json.dumps(quant_snapshot or {}, ensure_ascii=False),
            int(bool(sent)), str(status), created_at,
        )
        with self._connect() as con:
            con.execute(
                "INSERT INTO ai_predictions "
                "(site, period, action, play_type, confidence, quant_rationale, reason, model, "
                "history_snapshot, quant_snapshot, sent, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(site, period) DO UPDATE SET "
                "action=excluded.action, play_type=excluded.play_type, confidence=excluded.confidence, "
                "quant_rationale=excluded.quant_rationale, reason=excluded.reason, model=excluded.model, "
                "history_snapshot=excluded.history_snapshot, quant_snapshot=excluded.quant_snapshot, "
                "sent=excluded.sent, status=excluded.status",
                values,
            )

    def mark_sent(self, site: str, period: str) -> bool:
        with self._connect() as con:
            cursor = con.execute(
                "UPDATE ai_predictions SET sent = 1, status = 'sent' WHERE site = ? AND period = ?",
                (site, period),
            )
            return cursor.rowcount > 0

    def sent_group_ids(self, site: str, period: str) -> set[str]:
        """Return group ids that already received a bet for this draw."""
        with self._connect() as con:
            rows = con.execute(
                "SELECT group_id FROM auto_bet_sent_groups WHERE site = ? AND period = ?",
                (str(site), str(period)),
            ).fetchall()
        return {str(row[0]) for row in rows if str(row[0])}

    def all_sent_group_keys(self) -> set[tuple[str, str, str]]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT site, period, group_id FROM auto_bet_sent_groups"
            ).fetchall()
        return {(str(site), str(period), str(group_id)) for site, period, group_id in rows}

    def record_sent_groups(self, site: str, period: str, group_ids: list[str] | set[str]) -> None:
        """Persist successful sends to prevent a restart from resending the same draw."""
        values = [
            (str(site), str(period), str(group_id), datetime.now().isoformat())
            for group_id in group_ids
            if str(group_id)
        ]
        if not values:
            return
        with self._connect() as con:
            con.executemany(
                "INSERT OR IGNORE INTO auto_bet_sent_groups (site, period, group_id, sent_at) "
                "VALUES (?, ?, ?, ?)",
                values,
            )

    def record_pending_round(
        self,
        *,
        site: str,
        period: str,
        bets: list[dict[str, Any]],
        strategy_type: str,
        martingale_step: int,
        odds: dict[str, float],
    ) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO auto_bet_pending_rounds "
                "(site, period, bets, strategy_type, martingale_step, odds, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(site, period) DO UPDATE SET "
                "bets=excluded.bets, strategy_type=excluded.strategy_type, "
                "martingale_step=excluded.martingale_step, odds=excluded.odds",
                (
                    str(site), str(period), json.dumps(bets, ensure_ascii=False), str(strategy_type),
                    max(0, int(martingale_step)), json.dumps(odds, ensure_ascii=False), datetime.now().isoformat(),
                ),
            )

    def pending_round_records(self) -> list[AutoBetPendingRoundRecord]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT site, period, bets, strategy_type, martingale_step, odds "
                "FROM auto_bet_pending_rounds ORDER BY created_at ASC"
            ).fetchall()
        records: list[AutoBetPendingRoundRecord] = []
        for site, period, bets, strategy_type, martingale_step, odds in rows:
            raw_bets = _json_value(bets, [])
            raw_odds = _json_value(odds, {})
            records.append(AutoBetPendingRoundRecord(
                site=str(site),
                period=str(period),
                bets=list(raw_bets) if isinstance(raw_bets, list) else [],
                strategy_type=str(strategy_type),
                martingale_step=max(0, int(martingale_step)),
            odds=_float_mapping(raw_odds),
            ))
        return records

    def settle_pending_round(self, site: str, period: str) -> bool:
        with self._connect() as con:
            cursor = con.execute(
                "DELETE FROM auto_bet_pending_rounds WHERE site = ? AND period = ?",
                (str(site), str(period)),
            )
            return cursor.rowcount > 0

    def update_status(self, site: str, period: str, status: str) -> bool:
        with self._connect() as con:
            cursor = con.execute(
                "UPDATE ai_predictions SET status = ? WHERE site = ? AND period = ?",
                (status, site, period),
            )
            return cursor.rowcount > 0

    def settle(self, site: str, period: str, actual_result: str) -> bool:
        with self._connect() as con:
            row = con.execute(
                "SELECT play_type, sent FROM ai_predictions WHERE site = ? AND period = ?",
                (site, period),
            ).fetchone()
            if row is None:
                return False
            play_type = str(row[0] or "")
            direction_hit = _direction_hit(play_type, actual_result) if play_type else None
            exact_hit = play_type == str(actual_result) if play_type else None
            con.execute(
                "UPDATE ai_predictions SET actual_result = ?, direction_hit = ?, exact_hit = ?, "
                "status = CASE WHEN sent = 1 THEN 'settled' ELSE status END, settled_at = ? "
                "WHERE site = ? AND period = ?",
                (
                    str(actual_result), _to_db_bool(direction_hit), _to_db_bool(exact_hit),
                    datetime.now().isoformat(), site, period,
                ),
            )
            return True

    def pending_sent_records(self, site: str | None = None) -> list[AiPredictionRecord]:
        query = "SELECT * FROM ai_predictions WHERE sent = 1 AND actual_result = ''"
        params: tuple[Any, ...] = ()
        if site:
            query += " AND site = ?"
            params = (site,)
        query += " ORDER BY created_at ASC"
        return self._fetch_records(query, params)

    def recent_records(self, site: str, limit: int = 20) -> list[AiPredictionRecord]:
        return self._fetch_records(
            "SELECT * FROM ai_predictions WHERE site = ? ORDER BY created_at DESC, period DESC LIMIT ?",
            (site, max(1, int(limit))),
        )

    def accuracy_summary(self, site: str, window: int = 20) -> dict[str, Any]:
        settled = self._fetch_records(
            "SELECT * FROM ai_predictions WHERE site = ? AND sent = 1 "
            "AND actual_result <> '' ORDER BY settled_at ASC, created_at ASC",
            (site,),
        )
        short = settled[-max(1, int(window)):]
        overall_stats = _accuracy(settled)
        short_stats = {"window": max(1, int(window)), **_accuracy(short)}
        return {
            "settled_count": len(settled),
            "overall": overall_stats,
            "short": short_stats,
            "streak": _streak(settled),
        }

    def performance_context(self, site: str, window: int = 20, recent_limit: int = 5) -> dict[str, Any]:
        summary = self.accuracy_summary(site, window)
        settled = [
            item for item in self.recent_records(site, max(recent_limit * 4, recent_limit))
            if item.sent and item.actual_result
        ][:max(0, int(recent_limit))]
        return {
            "overall": summary["overall"],
            "short": summary["short"],
            "recent_predictions": [
            {
                "period": item.period,
                "play_type": item.play_type,
                "confidence": item.confidence,
                "actual_result": item.actual_result,
                "direction_hit": item.direction_hit,
                "exact_hit": item.exact_hit,
            }
            for item in settled
            ],
        }

    def _fetch_records(self, query: str, params: tuple[Any, ...]) -> list[AiPredictionRecord]:
        with self._connect() as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(query, params).fetchall()
        return [_row_to_record(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        self._lock.acquire()
        con = sqlite3.connect(str(self._db_path))

        class _ConnectionContext:
            def __enter__(inner_self) -> sqlite3.Connection:
                return con

            def __exit__(inner_self, exc_type, exc, traceback) -> None:
                try:
                    if exc_type is None:
                        con.commit()
                    else:
                        con.rollback()
                finally:
                    con.close()
                    self._lock.release()

        return _ConnectionContext()  # type: ignore[return-value]

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(_DDL)


def _direction_hit(play_type: str, result: str) -> bool:
    play = str(play_type or "")
    actual = str(result or "")
    if not play or not actual:
        return False
    if len(play) == 1:
        return play in actual
    return play == actual


def _accuracy(records: list[AiPredictionRecord]) -> dict[str, int | float]:
    count = len(records)
    direction_hits = sum(item.direction_hit is True for item in records)
    exact_hits = sum(item.exact_hit is True for item in records)
    return {
        "count": count,
        "direction_hits": direction_hits,
        "exact_hits": exact_hits,
        "direction_accuracy": direction_hits / count if count else 0.0,
        "exact_accuracy": exact_hits / count if count else 0.0,
    }


def _streak(records: list[AiPredictionRecord]) -> dict[str, str | int]:
    if not records:
        return {"result": "", "count": 0}
    latest_hit = records[-1].direction_hit is True
    count = 0
    for item in reversed(records):
        if (item.direction_hit is True) != latest_hit:
            break
        count += 1
    return {"result": "hit" if latest_hit else "miss", "count": count}


def _row_to_record(row: sqlite3.Row) -> AiPredictionRecord:
    return AiPredictionRecord(
        site=str(row["site"]),
        period=str(row["period"]),
        action=str(row["action"]),
        play_type=str(row["play_type"]),
        confidence=int(row["confidence"]),
        quant_rationale=str(row["quant_rationale"]),
        reason=str(row["reason"]),
        model=str(row["model"]),
        history_snapshot=_json_value(row["history_snapshot"], []),
        quant_snapshot=_json_value(row["quant_snapshot"], {}),
        sent=bool(row["sent"]),
        actual_result=str(row["actual_result"]),
        direction_hit=_from_db_bool(row["direction_hit"]),
        exact_hit=_from_db_bool(row["exact_hit"]),
        status=str(row["status"]),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        settled_at=datetime.fromisoformat(str(row["settled_at"])) if row["settled_at"] else None,
    )


def _json_value(raw: Any, default: Any) -> Any:
    try:
        return json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        return default


def _float_mapping(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    values: dict[str, float] = {}
    for key, raw in value.items():
        try:
            values[str(key)] = float(raw)
        except (TypeError, ValueError):
            continue
    return values


def _to_db_bool(value: bool | None) -> int | None:
    return None if value is None else int(value)


def _from_db_bool(value: Any) -> bool | None:
    return None if value is None else bool(value)
