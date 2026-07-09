from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from app.services.chat_service import ChatLogService


logger = logging.getLogger(__name__)


def capture_message_cursor(msg_db_path: str | Path | None, target_id: str) -> tuple[int, int, int]:
    """Return latest (client_time/time, id, rand) for a target conversation."""
    if msg_db_path is None:
        return (0, 0, 0)
    path = Path(msg_db_path)
    if not path.exists():
        return (0, 0, 0)
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            columns = [str(row[1]) for row in con.execute("PRAGMA table_info(message)").fetchall()]
            if "sid" not in columns:
                return (0, 0, 0)
            time_column = "client_time" if "client_time" in columns else ("time" if "time" in columns else "id")
            id_column = "id" if "id" in columns else "rowid"
            rand_expr = "rand" if "rand" in columns else "0"
            row = con.execute(
                f"SELECT coalesce({time_column}, 0) as cursor_time, "
                f"coalesce({id_column}, 0) as cursor_id, "
                f"coalesce({rand_expr}, 0) as cursor_rand "
                f"FROM message WHERE sid = ? "
                f"ORDER BY cursor_time DESC, cursor_id DESC, cursor_rand DESC LIMIT 1",
                (str(target_id),),
            ).fetchone()
            if row is None:
                return (0, 0, 0)
            return (int(row["cursor_time"] or 0), int(row["cursor_id"] or 0), int(row["cursor_rand"] or 0))
        finally:
            con.close()
    except sqlite3.DatabaseError as exc:
        logger.error("Failed to capture local message cursor %s: %s", path, exc)
        return (0, 0, 0)


def local_message_exists(
    msg_db_path: str | Path | None,
    target_id: str,
    text: str,
    *,
    limit: int = 50,
    after_cursor: tuple[int, int, int] | None = None,
) -> bool:
    """Return True when target group has a recent message containing text.

    Tencent Cloud Chat's local ``message.content`` is often a protobuf BLOB,
    and ``element_descriptions`` may be encrypted/encoded text.  Exact
    ``content = ?`` matching is therefore too strict for send verification.
    """
    if msg_db_path is None:
        return False
    path = Path(msg_db_path)
    if not path.exists():
        return False
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            columns = [str(row[1]) for row in con.execute("PRAGMA table_info(message)").fetchall()]
            select_columns = [name for name in ("content", "element_descriptions") if name in columns]
            if not select_columns or "sid" not in columns:
                return False
            order_column = "client_time" if "client_time" in columns else ("time" if "time" in columns else "id")
            id_column = "id" if "id" in columns else "rowid"
            rand_expr = "rand" if "rand" in columns else "0"
            where = "sid = ?"
            params: list[object] = [str(target_id)]
            if after_cursor is not None:
                cursor_time, cursor_id, cursor_rand = after_cursor
                where += (
                    f" AND (coalesce({order_column}, 0) > ? "
                    f"OR (coalesce({order_column}, 0) = ? AND coalesce({id_column}, 0) > ?) "
                    f"OR (coalesce({order_column}, 0) = ? AND coalesce({id_column}, 0) = ? AND coalesce({rand_expr}, 0) > ?))"
                )
                params.extend([cursor_time, cursor_time, cursor_id, cursor_time, cursor_id, cursor_rand])
            params.append(int(limit))
            rows = con.execute(
                f"SELECT {', '.join(select_columns)} FROM message WHERE {where} "
                f"ORDER BY coalesce({order_column}, 0) DESC, coalesce({id_column}, 0) DESC LIMIT ?",
                params,
            ).fetchall()
            expected = str(text)
            return any(
                any(row_value_contains_text(row[name], expected) for name in select_columns)
                for row in rows
            )
        finally:
            con.close()
    except sqlite3.DatabaseError as exc:
        logger.error("Failed to verify local message db %s: %s", path, exc)
        return False


def row_value_contains_text(value: object, expected: str) -> bool:
    if value is None:
        return False
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="ignore")
    else:
        text = str(value)
    if expected in text:
        return True
    try:
        decoded = ChatLogService()._decode_possible_frontend_ciphertext(text.strip())
    except Exception:
        decoded = ""
    return bool(decoded and expected in decoded)
