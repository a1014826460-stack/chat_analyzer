from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from app.models.auto_bet import DrawResult, DrawResultProvider
from app.services.history_fetchers import HistoryFetcher


logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS draw_results (
    site         TEXT NOT NULL,
    period       TEXT NOT NULL,
    result       TEXT NOT NULL,
    result_label TEXT,
    open_time    TEXT,
    fetched_at   TEXT NOT NULL,
    PRIMARY KEY (site, period)
);
CREATE INDEX IF NOT EXISTS idx_draw_results_site_period
    ON draw_results(site, period DESC);
"""


class DrawResultStore(DrawResultProvider):
    """SQLite-backed historical draw result provider."""

    _MIN_CACHE = 20

    def __init__(self, db_path: str | Path, fetcher: HistoryFetcher | None = None) -> None:
        self._db_path = Path(db_path)
        self._fetcher = fetcher or HistoryFetcher()
        self._lock = threading.RLock()
        self._ensured: set[str] = set()
        self._init_db()

    def ensure_data(self, site: str, min_count: int = 20) -> None:
        self._ensure_site(site, min_count)

    def refresh_recent_results(self, site: str, count: int = 50) -> int:
        """Always fetch the latest remote window and merge it into the cache."""
        try:
            fetched = self._fetcher.fetch(site, count=max(1, int(count)))
        except Exception as exc:
            logger.warning("Failed to refresh draw result cache for %s: %s", site, exc)
            return 0
        return self.insert_results(site, fetched) if fetched else 0

    def get_recent_results(self, site: str, count: int) -> list[DrawResult]:
        self._ensure_site(site, count * 2)
        with self._lock:
            con = sqlite3.connect(str(self._db_path))
            con.row_factory = sqlite3.Row
            try:
                rows = con.execute(
                    "SELECT site, period, result, result_label, open_time "
                    "FROM draw_results WHERE site = ? "
                    "ORDER BY period DESC LIMIT ?",
                    (site, count),
                ).fetchall()
            finally:
                con.close()

        results = [self._row_to_result(row) for row in rows]
        results.reverse()
        return results

    def get_result(self, site: str, period: str) -> DrawResult | None:
        self._ensure_site(site, 0)
        with self._lock:
            con = sqlite3.connect(str(self._db_path))
            con.row_factory = sqlite3.Row
            try:
                row = con.execute(
                    "SELECT site, period, result, result_label, open_time "
                    "FROM draw_results WHERE site = ? AND period = ?",
                    (site, period),
                ).fetchone()
            finally:
                con.close()
        return self._row_to_result(row) if row is not None else None

    def insert_results(self, site: str, results: list[DrawResult]) -> int:
        now = datetime.now().isoformat()
        inserted = 0
        with self._lock:
            con = sqlite3.connect(str(self._db_path))
            try:
                for result in results:
                    if not result.period:
                        continue
                    con.execute(
                        "INSERT OR REPLACE INTO draw_results "
                        "(site, period, result, result_label, open_time, fetched_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            site,
                            result.period,
                            result.result,
                            result.result,
                            result.open_time.isoformat() if result.open_time else None,
                            now,
                        ),
                    )
                    inserted += 1
                con.commit()
            finally:
                con.close()
        return inserted

    def clear_site(self, site: str) -> None:
        with self._lock:
            con = sqlite3.connect(str(self._db_path))
            try:
                con.execute("DELETE FROM draw_results WHERE site = ?", (site,))
                con.commit()
            finally:
                con.close()
        self._ensured.discard(site)

    def _ensure_site(self, site: str, min_count: int) -> None:
        if site in self._ensured:
            return
        need = max(min_count, self._MIN_CACHE)
        current_count = self._count(site)
        if current_count < need:
            try:
                fetched = self._fetcher.fetch(site, count=need)
            except Exception as exc:
                logger.warning("Failed to ensure draw result cache for %s: %s", site, exc)
                fetched = []
            if fetched:
                self.insert_results(site, fetched)
        self._ensured.add(site)

    def _count(self, site: str) -> int:
        with self._lock:
            con = sqlite3.connect(str(self._db_path))
            try:
                row = con.execute("SELECT COUNT(*) FROM draw_results WHERE site = ?", (site,)).fetchone()
                return int(row[0] if row else 0)
            finally:
                con.close()

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            con = sqlite3.connect(str(self._db_path))
            try:
                con.executescript(_DDL)
                con.commit()
            finally:
                con.close()

    @staticmethod
    def _row_to_result(row: sqlite3.Row) -> DrawResult:
        open_time = None
        raw_open_time = row["open_time"]
        if raw_open_time:
            try:
                open_time = datetime.fromisoformat(str(raw_open_time))
            except (TypeError, ValueError):
                open_time = None
        return DrawResult(
            site=str(row["site"]),
            period=str(row["period"]),
            result=str(row["result_label"] or row["result"]),
            open_time=open_time,
        )
