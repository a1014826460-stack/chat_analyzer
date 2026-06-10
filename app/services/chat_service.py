from __future__ import annotations

import csv
import json
import logging
import re
import sqlite3
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
except ImportError:
    A4 = None
    pdfmetrics = None
    TTFont = None
    canvas = None

from app.models import ChatGroup, ChatMessage, ParseOptions, StatsResult
from app.services.storage_service import ensure_parent


logger = logging.getLogger(__name__)
PLAY_TYPES = ["大", "小", "单", "双", "大双", "小单", "大单", "小双"]
PLAY_PATTERN = "|".join(sorted((re.escape(item) for item in PLAY_TYPES), key=len, reverse=True))
TXT_LINE_PATTERN = re.compile(
    r"^\[(?P<ts>[^\]]+)\]\s*(?P<group>[^\t]+)[\t ]+(?P<user>[^\t]+)[\t ]+(?P<content>.+)$"
)
SIMPLE_BET_PATTERN = re.compile(rf"(?P<play>{PLAY_PATTERN})\s*(?P<amount>\d[\d,]*(?:\.\d+)?)")
PLAY_TOKENS = tuple(sorted(PLAY_TYPES, key=len, reverse=True))
NUMBER_TOKEN_AT_PATTERN = re.compile(r"\d[\d,]*(?:\.\d+)?")
DIRECT_CLOSE_HINT_PATTERN = re.compile(r"濡備笅璁㈠崟宸插彇娑?")
RECEIPT_MATCH_WINDOW = timedelta(minutes=2)
DIRECT_GROUP_PERIOD_WINDOW = timedelta(minutes=20)


@dataclass
class PendingUserMessage:
    username: str
    sender_id: str
    bettor: str
    period: str
    ts: datetime


@dataclass
class DirectPeriodContext:
    period: str
    start: datetime
    end: datetime


class ChatLogService:
    def __init__(self) -> None:
        self._group_block_rules: dict[str, dict[str, object]] = {}

    def set_group_block_rules(self, rules: dict[str, dict[str, object]] | None) -> None:
        self._group_block_rules = rules or {}

    def extract_groups(self, messages: list[ChatMessage]) -> list[ChatGroup]:
        groups = sorted({msg.group for msg in messages if msg.group})
        return [ChatGroup(group_id=group, group_name=group) for group in groups]

    def list_groups_from_db(self, msg_db: Path) -> list[ChatGroup]:
        try:
            messages = self.load_messages(msg_db, ParseOptions())
        except Exception:
            return []
        return self.extract_groups(messages)

    def load_messages(self, source_path: Path, options: ParseOptions) -> list[ChatMessage]:
        source_path = Path(source_path)
        if source_path.suffix.lower() == ".txt":
            return self.load_messages_from_text(source_path, options)
        return self.load_messages_from_sqlite(source_path, options)

    def load_messages_from_text(self, file_path: Path, options: ParseOptions) -> list[ChatMessage]:
        messages: list[ChatMessage] = []
        for line in file_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            match = TXT_LINE_PATTERN.match(line)
            if match:
                ts = self._parse_text_timestamp(match.group("ts"))
                group = match.group("group").strip()
                username = match.group("user").strip()
                content = match.group("content").strip()
            else:
                parts = re.split(r"\t+", line, maxsplit=3)
                if len(parts) >= 4:
                    ts = self._parse_text_timestamp(parts[0])
                    group, username, content = (parts[1].strip(), parts[2].strip(), parts[3].strip())
                else:
                    continue
            msg = ChatMessage(ts=ts, group=group, username=username, content=content)
            if self._message_matches_options(msg, options):
                messages.append(msg)
        return messages

    def load_messages_from_sqlite(self, msg_db: Path, options: ParseOptions) -> list[ChatMessage]:
        if not msg_db.exists():
            return []

        queries = [
            """
            select
                coalesce(client_time, 0) as client_time,
                coalesce(rand, 0) as rand,
                coalesce(conv_nick_name, conversation_id, 'Unknown') as group_name,
                coalesce(sender_nick_name, sender_id, 'Unknown') as sender_name,
                coalesce(sender_id, '') as sender_id,
                coalesce(msg_text, text_elem, content, '') as content
            from msg
            order by client_time asc, rand asc
            """,
            """
            select
                coalesce(client_time, 0) as client_time,
                coalesce(rand, 0) as rand,
                coalesce(conversation_id, 'Unknown') as group_name,
                coalesce(sender_id, 'Unknown') as sender_name,
                coalesce(sender_id, '') as sender_id,
                coalesce(content, '') as content
            from message
            order by client_time asc, rand asc
            """,
        ]

        messages: list[ChatMessage] = []
        try:
            con = sqlite3.connect(f"file:{msg_db.as_posix()}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            for query in queries:
                try:
                    rows = con.execute(query).fetchall()
                    if rows:
                        for row in rows:
                            ts = self._sqlite_ts_to_datetime(int(row["client_time"] or 0))
                            msg = ChatMessage(
                                ts=ts,
                                group=str(row["group_name"] or "Unknown").strip(),
                                username=str(row["sender_name"] or "Unknown").strip(),
                                content=self._stringify_sqlite_content(row["content"]),
                                sender_id=str(row["sender_id"] or "").strip(),
                                raw_client_time=int(row["client_time"] or 0),
                                raw_rand=int(row["rand"] or 0),
                            )
                            if self._message_matches_options(msg, options):
                                messages.append(msg)
                        break
                except sqlite3.DatabaseError:
                    continue
        except sqlite3.DatabaseError:
            logger.exception("Failed to read sqlite messages from %s", msg_db)
        finally:
            try:
                con.close()
            except Exception:
                pass
        return messages

    def load_messages_with_cache(self, msg_db: Path, options: ParseOptions) -> list[ChatMessage]:
        messages = self.load_messages(msg_db, options)
        if options.incremental_since is not None:
            messages = [msg for msg in messages if msg.ts >= options.incremental_since]
        if options.incremental_cursor_value:
            messages = [
                msg
                for msg in messages
                if (msg.raw_client_time, msg.raw_rand)
                > (options.incremental_cursor_value, options.incremental_cursor_rand)
            ]
        return messages

    def get_cached_cursor(self, messages: list[ChatMessage]) -> tuple[int, int] | None:
        if not messages:
            return None
        latest = max(messages, key=lambda item: (item.raw_client_time, item.raw_rand, item.ts))
        return latest.raw_client_time, latest.raw_rand

    def get_cached_raw_cursor(self, messages: list[ChatMessage]) -> tuple[int, int] | None:
        return self.get_cached_cursor(messages)

    def analyze_bets(
        self,
        messages: list[ChatMessage],
        blocked_names: list[str],
        blocked_ids: list[str] | None,
        period_filter: str,
        site: str,
        period_window_start: datetime | None,
        period_window_end: datetime | None,
        period_interval_sec: int,
    ) -> tuple[list[dict[str, object]], StatsResult]:
        filtered = self.filter_blocked_messages(messages, blocked_names, blocked_ids)
        visual_rows = self.extract_bet_visual_data(
            filtered,
            blocked_names=blocked_names,
            blocked_ids=blocked_ids,
            period_filter=period_filter,
            site=site,
            period_window_start=period_window_start,
            period_window_end=period_window_end,
            period_interval_sec=period_interval_sec,
        )
        totals: dict[str, float] = defaultdict(float)
        for row in visual_rows:
            totals[str(row["play"])] += float(row["amount"])
        return visual_rows, StatsResult(totals=dict(totals), matched_messages=len(filtered))

    def summarize_bets(
        self,
        messages: list[ChatMessage],
        blocked_names: list[str],
        blocked_ids: list[str] | None,
        period_filter: str,
        site: str,
        period_window_start: datetime | None,
        period_window_end: datetime | None,
        period_interval_sec: int,
    ) -> StatsResult:
        return self.analyze_bets(
            messages,
            blocked_names,
            blocked_ids,
            period_filter,
            site,
            period_window_start,
            period_window_end,
            period_interval_sec,
        )[1]

    def filter_blocked_messages(
        self,
        messages: list[ChatMessage],
        blocked_names: list[str],
        blocked_ids: list[str] | None,
    ) -> list[ChatMessage]:
        blocked_name_keys = {self._normalize_text(name) for name in blocked_names}
        blocked_id_keys = {self._normalize_text(item) for item in (blocked_ids or [])}
        filtered: list[ChatMessage] = []
        for msg in messages:
            if self._normalize_text(msg.username) in blocked_name_keys:
                continue
            if self._normalize_text(msg.sender_id) in blocked_id_keys:
                continue
            if self._is_group_blocked_name(msg.group, msg.username):
                continue
            filtered.append(msg)
        return filtered

    def export_filtered_messages(self, messages: list[ChatMessage], export_path: Path) -> int:
        ensure_parent(export_path)
        with export_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["time", "group", "username", "sender_id", "content"])
            for msg in messages:
                writer.writerow([msg.ts.isoformat(sep=" "), msg.group, msg.username, msg.sender_id, msg.content])
        return len(messages)

    def export_stats_excel(self, stats: StatsResult, export_path: Path) -> None:
        ensure_parent(export_path)
        df = pd.DataFrame(
            [{"play": play, "amount": amount} for play, amount in sorted(stats.totals.items())]
        )
        df.to_excel(export_path, index=False)

    def export_stats_pdf(self, stats: StatsResult, export_path: Path) -> None:
        ensure_parent(export_path)
        if canvas is None or A4 is None:
            export_path.write_text(json.dumps(stats.totals, ensure_ascii=False, indent=2), encoding="utf-8")
            return

        pdf = canvas.Canvas(str(export_path), pagesize=A4)
        width, height = A4
        y = height - 48
        if pdfmetrics is not None and TTFont is not None:
            try:
                pdfmetrics.registerFont(TTFont("HelveticaFallback", "C:/Windows/Fonts/msyh.ttc"))
                pdf.setFont("HelveticaFallback", 11)
            except Exception:
                pdf.setFont("Helvetica", 11)
        else:
            pdf.setFont("Helvetica", 11)
        pdf.drawString(48, y, "Bet Summary")
        y -= 24
        for play, amount in sorted(stats.totals.items()):
            pdf.drawString(48, y, f"{play}: {amount:,.2f}")
            y -= 18
        pdf.save()

    def extract_bet_visual_data(
        self,
        messages: list[ChatMessage],
        blocked_names: list[str],
        blocked_ids: list[str] | None,
        period_filter: str,
        site: str,
        period_window_start: datetime | None,
        period_window_end: datetime | None,
        period_interval_sec: int,
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        filtered_messages = self.filter_blocked_messages(messages, blocked_names, blocked_ids)
        group_periods: dict[str, list[tuple[datetime, datetime, str]]] = {}
        for msg in filtered_messages:
            group_key = self._normalize_text(msg.group)
            if group_key in group_periods:
                continue
            group_messages = [item for item in filtered_messages if self._normalize_text(item.group) == group_key]
            group_periods[group_key] = self._build_direct_group_period_ranges(group_messages)

        for index, msg in enumerate(filtered_messages):
            for event_index, (play, amount) in enumerate(self._parse_bets(msg.content)):
                if period_window_start and msg.ts < period_window_start:
                    continue
                if period_window_end and msg.ts > period_window_end:
                    continue
                resolved_period = period_filter or self._resolve_direct_group_period(
                    msg.ts,
                    group_periods.get(self._normalize_text(msg.group), []),
                )
                row = {
                    "time": msg.ts,
                    "group": msg.group,
                    "username": msg.username,
                    "bettor": msg.username,
                    "play": play,
                    "amount": amount,
                    "kind": "bet",
                    "period": resolved_period,
                    "row_id": f"{index}-{event_index}",
                }
                rows.append(row)
        return rows

    def _clean_text(self, value: object) -> str:
        text = str(value or "")
        return text.replace("\ufeff", "").replace("\u200b", "").strip()

    def _normalize_text(self, value: str) -> str:
        return unicodedata.normalize("NFKC", self._clean_text(value)).casefold()

    def _group_block_rules_signature(self) -> tuple:
        items = []
        for key, value in sorted(self._group_block_rules.items()):
            names = tuple(sorted(self._normalize_text(name) for name in value.get("names", [])))
            items.append((key, names))
        return tuple(items)

    def _blocked_names_for_group(self, group: str) -> set[str]:
        group_key = self._normalize_text(group)
        rule = self._group_block_rules.get(group_key) or self._group_block_rules.get(group)
        if not isinstance(rule, dict):
            for candidate in self._group_block_rules.values():
                if self._normalize_text(str(candidate.get("group_name", ""))) == group_key:
                    rule = candidate
                    break
        if not isinstance(rule, dict):
            return set()
        return {self._normalize_text(name) for name in rule.get("names", [])}

    def _is_group_blocked_name(self, group: str, username: str) -> bool:
        return self._normalize_text(username) in self._blocked_names_for_group(group)

    def _parse_bets(self, content: str) -> list[tuple[str, float]]:
        events: list[tuple[str, float]] = []
        for match in SIMPLE_BET_PATTERN.finditer(content):
            amount = self._parse_amount_text(match.group("amount"))
            if amount <= 0:
                continue
            events.append((match.group("play"), amount))
        if events:
            return events
        for _bettor, play, amount in self._parse_compact_bets(content, self._extract_bettor_name(content)):
            if amount > 0:
                events.append((play, amount))
        return events

    def _parse_compact_bets(self, content: str, bettor: str) -> list[tuple[str, str, float]]:
        text = self._clean_text(content)
        matches: list[tuple[int, str, float]] = []
        i = 0
        length = len(text)
        while i < length:
            char = text[i]
            if char.isspace():
                i += 1
                continue
            if char.isdigit():
                number_match = NUMBER_TOKEN_AT_PATTERN.match(text, i)
                if number_match:
                    number_text = number_match.group(0)
                    next_pos = number_match.end()
                    play = self._match_play_token(text, next_pos)
                    if play is not None:
                        matches.append((i, play, self._parse_amount_text(number_text)))
                        i = next_pos + len(play)
                        continue
            play = self._match_play_token(text, i)
            if play is not None:
                amount_match = NUMBER_TOKEN_AT_PATTERN.match(text, i + len(play))
                if amount_match:
                    amount_text = amount_match.group(0)
                    matches.append((i, play, self._parse_amount_text(amount_text)))
                    i = amount_match.end()
                    continue
            i += 1
        matches.sort(key=lambda item: item[0])
        return [(bettor, play, amount) for _pos, play, amount in matches]

    def _parse_amount_text(self, value: str) -> float:
        try:
            return float(self._clean_text(value).replace(",", ""))
        except ValueError:
            return 0.0

    def _match_play_token(self, text: str, start: int) -> str | None:
        for token in PLAY_TOKENS:
            if text.startswith(token, start):
                return token
        return None

    def _extract_direct_group_marker(self, msg: ChatMessage) -> tuple[str, str] | None:
        if not msg.sender_id:
            return None
        if not self._is_group_member_robot(msg.group, msg.sender_id, msg.username):
            return None
        content = self._decode_possible_frontend_ciphertext(self._clean_text(msg.content))
        period = self._extract_period(content)
        if not period:
            return None
        if DIRECT_CLOSE_HINT_PATTERN.search(content):
            return ("end", period)
        if "涓嬫敞鏈熸暟" in content or "鏈湡涓嬫敞" in content:
            return ("start", period)
        return None

    def _build_direct_group_period_ranges(
        self,
        messages: list[ChatMessage],
        direct_period_context: DirectPeriodContext | None = None,
    ) -> list[tuple[datetime, datetime, str]]:
        if not messages:
            return []
        latest_ts = max((msg.ts for msg in messages), default=None)
        if latest_ts is None:
            return []
        if direct_period_context is not None:
            return [(direct_period_context.start, direct_period_context.end, direct_period_context.period)]

        window_start = latest_ts - DIRECT_GROUP_PERIOD_WINDOW
        markers: list[tuple[datetime, str, str]] = []
        for msg in messages:
            if msg.ts < window_start:
                continue
            marker = self._extract_direct_group_marker(msg)
            if marker is not None:
                markers.append((msg.ts, marker[0], marker[1]))

        markers.sort(key=lambda item: item[0])
        periods: list[tuple[datetime, datetime, str]] = []
        current_start: datetime | None = None
        current_period = ""
        for ts, marker_kind, period in markers:
            if marker_kind == "start":
                if current_start is not None and current_period:
                    periods.append((current_start, ts, current_period))
                current_start = ts
                current_period = period
                continue
            if current_start is not None and current_period and (not period or period == current_period):
                periods.append((current_start, ts, current_period))
                current_start = None
                current_period = ""
        if current_start is not None and current_period:
            periods.append((current_start, latest_ts + timedelta(seconds=1), current_period))
        return periods

    def _resolve_direct_group_period(
        self,
        ts: datetime,
        periods: list[tuple[datetime, datetime, str]],
    ) -> str:
        for start, end, period in reversed(periods):
            if start <= ts <= end:
                return period
        return ""

    def _resolve_receipt_owner(
        self,
        event: object,
        msg: ChatMessage,
        period: str,
        pending_by_bettor: dict[str, list[PendingUserMessage]],
        pending_by_user: dict[str, list[PendingUserMessage]],
    ) -> tuple[str, str]:
        bettor_key = self._normalize_text(getattr(event, "bettor", ""))
        candidates = list(pending_by_bettor.get(bettor_key, []))
        if not candidates and bettor_key:
            candidates = list(pending_by_user.get(bettor_key, []))
        candidates = [
            pending
            for pending in candidates
            if (
                (not period or not pending.period or pending.period == period)
                and msg.ts >= pending.ts
                and msg.ts - pending.ts <= RECEIPT_MATCH_WINDOW
            )
        ]
        if candidates:
            chosen = candidates[-1]
            return chosen.username, chosen.sender_id
        return msg.username, msg.sender_id

    def _extract_period(self, content: str) -> str:
        match = re.search(r"(\d{4,})", self._clean_text(content))
        if not match:
            return ""
        return match.group(1)

    def _extract_bettor_name(self, content: str) -> str:
        return ""

    def _is_group_member_robot(self, group: str, sender_id: str, fallback_username: str) -> bool:
        _ = (group, sender_id, fallback_username)
        return False

    def _decode_possible_frontend_ciphertext(self, content: str) -> str:
        return self._clean_text(content)

    def _message_matches_options(self, msg: ChatMessage, options: ParseOptions) -> bool:
        if options.username and self._normalize_text(msg.username) != self._normalize_text(options.username):
            return False
        if options.groups and msg.group not in options.groups:
            return False
        if options.start_time and msg.ts < options.start_time:
            return False
        if options.end_time and msg.ts > options.end_time:
            return False
        return True

    def _parse_text_timestamp(self, raw: str) -> datetime:
        raw = raw.strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
        return datetime.now()

    def _sqlite_ts_to_datetime(self, value: int) -> datetime:
        if value <= 0:
            return datetime.now()
        if value > 10_000_000_000:
            value //= 1000
        return datetime.fromtimestamp(value)

    def _stringify_sqlite_content(self, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="ignore")
        return str(value)
