from __future__ import annotations

import base64
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
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
except ImportError:
    AES = None
    unpad = None

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
SUMMARY_SQUARE_BODY_PATTERN = re.compile(r"(?<!-)\[(?P<body>[^\[\]\n\r]+)\]")
RECEIPT_BETTOR_PATTERN = re.compile(r"@\s*(?P<bettor>.+?)\s*[:：]")
RECEIPT_BODY_PATTERN = re.compile(r"下注内容\s*[:：]\s*-+\s*(?P<body>.*?)\s*-+\s*余额", re.S)
RECEIPT_ODDS_PATTERN = re.compile(r"\([^)]*赔率\)")
RECEIPT_ALLOWED_PLAY_BET_PATTERN = re.compile(
    rf"^(?P<play>{PLAY_PATTERN})\s*(?P<amount>\d[\d,]*(?:\.\d+)?)(?:\D.*)?$"
)
RECEIPT_POINT_PLAY_BET_PATTERN = re.compile(r"^(?P<play>\d{1,2})\.(?P<amount>\d[\d,]*)(?:\D.*)?$")
RECEIPT_GENERIC_PLAY_BET_PATTERN = re.compile(r"^(?P<play>.+?)(?P<amount>\d[\d,]*(?:\.\d+)?)(?:\D.*)?$")
DIRECT_CLOSE_HINT_PATTERN = re.compile(r"濡備笅璁㈠崟宸插彇娑?|如下订单已取消")
RECEIPT_MATCH_WINDOW = timedelta(minutes=5)
DIRECT_GROUP_PERIOD_WINDOW = timedelta(minutes=10)
ROBOT_DETECTION_WINDOW = timedelta(minutes=20)
DEFAULT_SQLITE_LOAD_WINDOW = timedelta(minutes=5)
FRONTEND_AAS_KEY = "666888"
LOG_PREVIEW_LIMIT = 120
ZODIAC_GROUP_NAMES = (
    "白羊座",
    "金牛座",
    "双子座",
    "巨蟹座",
    "狮子座",
    "处女座",
    "天秤座",
    "天蝎座",
    "射手座",
    "摩羯座",
    "水瓶座",
    "双鱼座",
)


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
    accept_start: datetime
    accept_end: datetime


@dataclass
class BetEvent:
    bettor: str
    play: str
    amount: float
    kind: str
    source: str = ""
    order_id: str = ""


@dataclass
class RobotSummarySnapshot:
    period: str
    group: str
    ts: datetime
    totals: dict[str, float]
    totals_by_bettor: dict[str, dict[str, float]]


@dataclass
class ResolvedBetEvent:
    group: str
    username: str
    sender_id: str
    ts: datetime
    period: str
    bettor: str
    play: str
    amount: float
    kind: str
    source_kind: str
    order_id: str = ""


class ChatLogService:
    def __init__(self) -> None:
        self._group_block_rules: dict[str, dict[str, object]] = {}
        self._group_robot_ids: dict[str, str] = {}

    def set_group_block_rules(self, rules: dict[str, dict[str, object]] | None) -> None:
        self._group_block_rules = rules or {}

    def set_group_robot_ids(self, robot_ids: dict[str, str] | None) -> None:
        self._group_robot_ids = {
            str(group_id).strip(): str(sender_id).strip()
            for group_id, sender_id in dict(robot_ids or {}).items()
            if str(group_id).strip() and str(sender_id).strip()
        }

    def group_robot_ids(self) -> dict[str, str]:
        return dict(self._group_robot_ids)

    def remember_group_robots(self, messages: list[ChatMessage]) -> dict[str, str]:
        grouped: dict[str, list[ChatMessage]] = defaultdict(list)
        for msg in messages:
            group_key = self._robot_group_key(msg.group, getattr(msg, "group_id", ""))
            if group_key:
                grouped[group_key].append(msg)

        for group_key, group_messages in grouped.items():
            if group_key in self._group_robot_ids:
                continue
            robot_sender = self._detect_group_robot_sender(group_messages)
            if robot_sender:
                self._group_robot_ids[group_key] = robot_sender
        return self.group_robot_ids()

    def extract_groups(self, messages: list[ChatMessage]) -> list[ChatGroup]:
        groups = sorted({msg.group for msg in messages if msg.group})
        return [ChatGroup(group_id=group, group_name=group) for group in groups]

    def list_groups_from_db(self, msg_db: Path) -> list[ChatGroup]:
        msg_db = Path(msg_db)
        if msg_db.suffix.lower() != ".txt":
            return self._list_sqlite_groups(msg_db)
        try:
            messages = self.load_messages(msg_db, ParseOptions())
        except Exception:
            return []
        return self.extract_groups(messages)

    def _list_sqlite_groups(self, msg_db: Path) -> list[ChatGroup]:
        if not msg_db.exists():
            return []
        group_names = self._sqlite_group_name_map(msg_db)
        if not group_names:
            logger.info("No groupinfo groups found for %s; skip message-table group inference", msg_db)
            return []
        return [ChatGroup(group_id=group_id, group_name=group_name) for group_id, group_name in group_names.items()]

    def _sqlite_group_name_map(self, msg_db: Path) -> dict[str, str]:
        im_db = msg_db.parent / "im.db"
        if not im_db.exists():
            return {}
        try:
            con = sqlite3.connect(f"file:{im_db.as_posix()}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "select group_id, group_name from groupinfo "
                "where group_id is not null and group_id != '' "
                "and group_name is not null and group_name != '' "
                "order by group_name collate nocase asc"
            ).fetchall()
            return {
                str(row["group_id"]).strip(): str(row["group_name"] or row["group_id"]).strip()
                for row in rows
                if str(row["group_id"]).strip() and str(row["group_name"] or "").strip()
            }
        except sqlite3.DatabaseError:
            logger.debug("Failed to load group names from %s", im_db, exc_info=True)
            return {}
        finally:
            try:
                con.close()
            except Exception:
                pass

    def _sqlite_sender_name_maps(self, msg_db: Path) -> tuple[dict[tuple[str, str], str], dict[str, str]]:
        im_db = msg_db.parent / "im.db"
        if not im_db.exists():
            return {}, {}
        member_names: dict[tuple[str, str], str] = {}
        user_names: dict[str, str] = {}
        try:
            con = sqlite3.connect(f"file:{im_db.as_posix()}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            try:
                member_rows = con.execute(
                    "select group_id, user_id, remark, name_card, nick_name from groupmemberinfo "
                    "where group_id is not null and group_id != '' "
                    "and user_id is not null and user_id != ''"
                ).fetchall()
                for row in member_rows:
                    group_id = str(row["group_id"] or "").strip()
                    user_id = str(row["user_id"] or "").strip()
                    display_name = self._first_nonempty_text(row["remark"], row["name_card"], row["nick_name"])
                    if group_id and user_id and display_name:
                        member_names[(group_id, user_id)] = display_name
            except sqlite3.DatabaseError:
                logger.debug("No groupmemberinfo sender names found in %s", im_db, exc_info=True)

            try:
                user_rows = con.execute(
                    "select user_id, remark, nick_name from userinfo "
                    "where user_id is not null and user_id != ''"
                ).fetchall()
                for row in user_rows:
                    user_id = str(row["user_id"] or "").strip()
                    display_name = self._first_nonempty_text(row["remark"], row["nick_name"])
                    if user_id and display_name:
                        user_names[user_id] = display_name
            except sqlite3.DatabaseError:
                logger.debug("No userinfo sender names found in %s", im_db, exc_info=True)
        except sqlite3.DatabaseError:
            logger.debug("Failed to load sender names from %s", im_db, exc_info=True)
            return {}, {}
        finally:
            try:
                con.close()
            except Exception:
                pass
        return member_names, user_names

    def _first_nonempty_text(self, *values: object) -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return ""

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
            msg = ChatMessage(ts=ts, group=group, username=username, content=content, group_id=group)
            if self._message_matches_options(msg, options):
                messages.append(msg)
        return messages

    def load_messages_from_sqlite(self, msg_db: Path, options: ParseOptions) -> list[ChatMessage]:
        if not msg_db.exists():
            return []

        queries = [
            """
            select
                coalesce(client_time, time, 0) as client_time,
                coalesce(rand, 0) as rand,
                coalesce(sid, 'Unknown') as group_name,
                coalesce(sender, 'Unknown') as sender_name,
                coalesce(sender, '') as sender_id,
                coalesce(element_descriptions, '') as element_descriptions,
                coalesce(content, '') as content
            from message
            {where_clause}
            order by client_time asc, rand asc
            """,
            """
            select
                coalesce(client_time, 0) as client_time,
                coalesce(rand, 0) as rand,
                coalesce(conv_nick_name, conversation_id, 'Unknown') as group_name,
                coalesce(sender_nick_name, sender_id, 'Unknown') as sender_name,
                coalesce(sender_id, '') as sender_id,
                '' as element_descriptions,
                coalesce(msg_text, text_elem, content, '') as content
            from msg
            {where_clause}
            order by client_time asc, rand asc
            """,
            """
            select
                coalesce(client_time, 0) as client_time,
                coalesce(rand, 0) as rand,
                coalesce(conversation_id, 'Unknown') as group_name,
                coalesce(sender_id, 'Unknown') as sender_name,
                coalesce(sender_id, '') as sender_id,
                '' as element_descriptions,
                coalesce(content, '') as content
            from message
            {where_clause}
            order by client_time asc, rand asc
            """,
        ]

        messages: list[ChatMessage] = []
        try:
            con = sqlite3.connect(f"file:{msg_db.as_posix()}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            client_time_unit = self._detect_sqlite_client_time_unit(con)
            group_name_map = self._sqlite_group_name_map(msg_db)
            member_name_map, user_name_map = self._sqlite_sender_name_maps(msg_db)
            for raw_query in queries:
                query, params = self._apply_sqlite_query_options(raw_query, options, client_time_unit)
                try:
                    rows = con.execute(query, params).fetchall()
                    if rows:
                        for row in rows:
                            ts = self._sqlite_ts_to_datetime(int(row["client_time"] or 0))
                            group_raw = str(row["group_name"] or "Unknown").strip()
                            sender_id = str(row["sender_id"] or "").strip()
                            sender_name = (
                                member_name_map.get((group_raw, sender_id))
                                or user_name_map.get(sender_id)
                                or str(row["sender_name"] or "Unknown").strip()
                            )
                            msg = ChatMessage(
                                ts=ts,
                                group=group_name_map.get(group_raw, group_raw),
                                username=sender_name,
                                content=self._extract_message_text(
                                    row["element_descriptions"],
                                    row["content"],
                                ),
                                sender_id=sender_id,
                                group_id=group_raw,
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
        lock_threshold_sec: int = 0,
        group_types_by_id: dict[str, str] | None = None,
    ) -> tuple[list[dict[str, object]], StatsResult]:
        filtered = self.filter_blocked_messages(messages, [], blocked_ids)
        visual_rows = self.extract_bet_visual_data(
            filtered,
            blocked_names=blocked_names,
            blocked_ids=blocked_ids,
            period_filter=period_filter,
            site=site,
            period_window_start=period_window_start,
            period_window_end=period_window_end,
            period_interval_sec=period_interval_sec,
            lock_threshold_sec=lock_threshold_sec,
            group_types_by_id=group_types_by_id,
        )
        unresolved_receipts: list[dict[str, object]] = []
        filtered_rows: list[dict[str, object]] = []
        for row in visual_rows:
            username = str(row.get("username", "") or "")
            bettor = str(row.get("bettor", "") or "")
            if (
                str(row.get("source_kind", "") or "") == "receipt"
                and bettor
                and bettor != username
                and self._looks_like_robot_identity(
                    username,
                    row.get("sender_id", ""),
                    row.get("group", ""),
                )
            ):
                unresolved_receipts.append(dict(row))
                continue
            filtered_rows.append(row)
        visual_rows = filtered_rows
        totals: dict[str, float] = defaultdict(float)
        totals_by_group: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        non_summary_seen: set[tuple[str, str]] = set()
        summary_fallback_rows: list[dict[str, object]] = []
        for row in visual_rows:
            group = str(row.get("group", "") or "")
            play = str(row["play"])
            source_kind = str(row.get("source_kind", "") or "")
            if source_kind == "summary":
                summary_fallback_rows.append(dict(row))
                continue
            amount = float(row["amount"])
            totals[play] += amount
            if group:
                totals_by_group[group][play] += amount
                non_summary_seen.add((group, play))
        for row in summary_fallback_rows:
            group = str(row.get("group", "") or "")
            play = str(row["play"])
            if group and (group, play) in non_summary_seen:
                continue
            amount = float(row["amount"])
            totals[play] += amount
            if group:
                totals_by_group[group][play] += amount
        summary_check_records = self._build_robot_summary_reconciliations(
            filtered,
            {group: dict(group_totals) for group, group_totals in totals_by_group.items()},
            period_filter,
        )
        summary_check = summary_check_records[0] if summary_check_records else {}
        return visual_rows, StatsResult(
            totals=dict(totals),
            totals_by_group={group: dict(group_totals) for group, group_totals in totals_by_group.items()},
            matched_messages=len(filtered),
            summary_check_period=str(summary_check.get("period", "") or ""),
            summary_check_totals=dict(summary_check.get("robot_totals", {}) or {}),
            summary_check_by_play=dict(summary_check.get("by_play", {}) or {}),
            summary_check_records=summary_check_records,
            unresolved_receipts=unresolved_receipts,
        )

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
        lock_threshold_sec: int = 0,
        group_types_by_id: dict[str, str] | None = None,
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
            lock_threshold_sec,
            group_types_by_id,
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
        lock_threshold_sec: int = 0,
        group_types_by_id: dict[str, str] | None = None,
    ) -> list[dict[str, object]]:
        blocked_name_set = {self._normalize_text(name) for name in blocked_names}
        blocked_id_set = {self._normalize_text(item) for item in (blocked_ids or [])}
        normalized_period_filter = self._normalize_text(period_filter)
        direct_period_context = self._build_direct_period_context(
            site=site,
            period=period_filter,
            start=period_window_start,
            end=period_window_end,
            interval_sec=period_interval_sec,
            lock_threshold_sec=lock_threshold_sec,
        )
        resolved_events = self._dedupe_resolved_events(
            self._resolve_group_bet_events(
                messages,
                direct_period_context=direct_period_context,
                group_types_by_id=group_types_by_id,
            )
        )
        blocked_identity_keys, blocked_sender_keys = self._blocked_event_identity_sets(
            resolved_events,
            blocked_name_set,
        )
        latest: dict[tuple[str, str, str], dict[str, object]] = {}
        direct_totals: dict[tuple[str, str, str], float] = defaultdict(float)

        for event in resolved_events:
            if period_window_start and event.ts < period_window_start:
                continue
            if period_window_end and event.ts > period_window_end:
                continue
            if self._event_misses_period_filter(event, normalized_period_filter):
                continue
            sender_key = self._normalize_text(event.sender_id)
            if sender_key and sender_key in blocked_id_set:
                continue
            group_block_names = self._blocked_names_for_group(event.group)
            event_name_keys = self._event_block_name_keys(event)
            if sender_key and sender_key in blocked_sender_keys:
                continue
            if event_name_keys & blocked_identity_keys:
                continue
            if event_name_keys & blocked_name_set:
                continue
            if event_name_keys & group_block_names:
                continue

            bettor_name = event.bettor or event.username
            bettor_key = self._normalize_text(bettor_name)
            period = event.period

            if event.kind == "bet":
                pk = (bettor_key, period, event.play)
                if event.source_kind == "direct":
                    amount = direct_totals.get(pk, 0.0) + float(event.amount)
                    direct_totals[pk] = amount
                else:
                    prev_amount = float(latest.get(pk, {}).get("amount", 0.0))
                    if float(event.amount) <= prev_amount:
                        continue
                    amount = float(event.amount)
                latest[pk] = {
                    "group": event.group,
                    "username": event.username,
                    "bettor": bettor_name,
                    "play": event.play,
                    "amount": amount,
                    "time": event.ts,
                    "period": period,
                    "sender_id": event.sender_id,
                    "row_id": f"{event.group}|{bettor_name}|{period}|{event.play}|LATEST",
                    "kind": "bet",
                    "source_kind": event.source_kind,
                }
                continue

            if event.kind != "cancel":
                continue

            if not period:
                period = self._find_active_period_by_latest(latest.keys(), bettor_key)
            if event.play:
                pk = (bettor_key, period, event.play)
                latest.pop(pk, None)
                direct_totals.pop(pk, None)
                continue
            to_remove = [key for key in latest if key[0] == bettor_key and key[1] == period]
            for key in to_remove:
                latest.pop(key, None)
                direct_totals.pop(key, None)

        visual_rows = list(latest.values())
        visual_rows.sort(key=lambda row: (row["time"], row["group"], row["username"], row["bettor"], row["play"]))
        return visual_rows

    def _build_direct_period_context(
        self,
        site: str,
        period: str,
        start: datetime | None,
        end: datetime | None,
        interval_sec: int,
        lock_threshold_sec: int = 0,
    ) -> DirectPeriodContext | None:
        period_text = str(period or "").strip()
        if not period_text or end is None:
            return None
        if start is None and interval_sec > 0:
            start = end - timedelta(seconds=interval_sec)
        if start is None:
            return None
        if start >= end:
            return None
        accept_start = start + timedelta(seconds=10)
        accept_end = end - timedelta(seconds=max(0, int(lock_threshold_sec or 0)))
        if accept_start > accept_end:
            return None
        return DirectPeriodContext(period=period_text, start=start, end=end, accept_start=accept_start, accept_end=accept_end)

    def _event_misses_period_filter(self, event: ResolvedBetEvent, normalized_period_filter: str) -> bool:
        if not normalized_period_filter:
            return False
        return self._normalize_text(event.period) != normalized_period_filter

    def _resolve_group_bet_events(
        self,
        messages: list[ChatMessage],
        direct_period_context: DirectPeriodContext | None = None,
        group_types_by_id: dict[str, str] | None = None,
    ) -> list[ResolvedBetEvent]:
        grouped: dict[str, list[ChatMessage]] = defaultdict(list)
        for msg in sorted(messages, key=lambda item: (item.ts, int(item.raw_client_time or 0), int(item.raw_rand or 0))):
            grouped[self._message_group_key(msg)].append(msg)

        resolved: list[ResolvedBetEvent] = []
        for group_messages in grouped.values():
            resolved.extend(
                self._resolve_single_group_bet_events(
                    group_messages,
                    direct_period_context,
                    group_types_by_id=group_types_by_id,
                )
            )
        resolved.sort(key=lambda item: (item.ts, item.group, item.username, item.bettor, item.play, item.kind))
        return resolved

    def _message_group_key(self, msg: ChatMessage) -> str:
        group_id = str(getattr(msg, "group_id", "") or "").strip()
        if group_id:
            return f"id:{self._normalize_text(group_id)}"
        return f"name:{self._normalize_text(msg.group)}"

    def _dedupe_resolved_events(self, events: list[ResolvedBetEvent]) -> list[ResolvedBetEvent]:
        seen: set[tuple[object, ...]] = set()
        deduped: list[ResolvedBetEvent] = []
        for event in events:
            key = (
                event.group,
                event.username,
                event.sender_id,
                event.ts,
                event.period,
                event.bettor,
                event.play,
                float(event.amount),
                event.kind,
                event.source_kind,
                event.order_id,
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(event)
        return deduped

    def _resolve_single_group_bet_events(
        self,
        messages: list[ChatMessage],
        direct_period_context: DirectPeriodContext | None = None,
        group_types_by_id: dict[str, str] | None = None,
    ) -> list[ResolvedBetEvent]:
        if not messages:
            return []
        group_type = self._group_type_for_messages(messages, group_types_by_id)
        if group_type == "receipt":
            return self._resolve_receipt_group_bet_events(messages)
        if group_type == "direct":
            return self._resolve_direct_group_bet_events(messages, direct_period_context)
        group_name = messages[0].group
        if self._is_zodiac_group(group_name):
            return self._resolve_receipt_group_bet_events(messages)
        return self._resolve_direct_group_bet_events(messages, direct_period_context)

    def _group_type_for_messages(
        self,
        messages: list[ChatMessage],
        group_types_by_id: dict[str, str] | None,
    ) -> str:
        if not messages or not group_types_by_id:
            return ""
        first = messages[0]
        candidates = (
            str(getattr(first, "group_id", "") or "").strip(),
            str(getattr(first, "group", "") or "").strip(),
        )
        for key in candidates:
            if not key:
                continue
            group_type = self._normalize_group_type(group_types_by_id.get(key))
            if group_type:
                return group_type
        return ""

    def _normalize_group_type(self, value: object) -> str:
        text = self._normalize_text(value)
        if text in {"receipt", "回执", "回执群"}:
            return "receipt"
        if text in {"direct", "直接", "直接群"}:
            return "direct"
        return ""

    def _is_zodiac_group(self, group_name: str) -> bool:
        normalized = self._normalize_text(group_name)
        return any(name in normalized for name in ZODIAC_GROUP_NAMES)

    def _resolve_receipt_group_bet_events(self, messages: list[ChatMessage]) -> list[ResolvedBetEvent]:
        pending_by_bettor: dict[str, list[PendingUserMessage]] = defaultdict(list)
        pending_by_user: dict[str, list[PendingUserMessage]] = defaultdict(list)
        resolved: list[ResolvedBetEvent] = []

        for msg in messages:
            period = self._extract_period(msg.content)
            content, events = self._parse_bet_events_from_message(msg)
            if not events:
                continue
            is_robot_msg = self._is_group_member_robot(msg.group, msg.sender_id, msg.username, msg.group_id)
            if is_robot_msg and not self._parse_receipt_bet_events(content):
                continue
            for event in events:
                if event.kind in {"bet", "cancel"}:
                    username, sender_id = self._resolve_receipt_owner(
                        event,
                        msg,
                        period,
                        pending_by_bettor,
                        pending_by_user,
                    )
                else:
                    username, sender_id = msg.username, msg.sender_id
                resolved.append(
                    ResolvedBetEvent(
                        group=msg.group,
                        username=username,
                        sender_id=sender_id,
                        ts=msg.ts,
                        period=period,
                        bettor=event.bettor or username,
                        play=event.play,
                        amount=float(event.amount),
                        kind=event.kind,
                        source_kind="receipt",
                        order_id=event.order_id,
                    )
                )
            if is_robot_msg:
                continue
            pending = PendingUserMessage(
                username=msg.username,
                sender_id=msg.sender_id,
                bettor=msg.username,
                period=period,
                ts=msg.ts,
            )
            pending_by_user[self._normalize_text(msg.username)].append(pending)
            for event in events:
                bettor_key = self._normalize_text(event.bettor or msg.username)
                pending_by_bettor[bettor_key].append(pending)
        return resolved

    def _resolve_direct_group_bet_events(
        self,
        messages: list[ChatMessage],
        direct_period_context: DirectPeriodContext | None = None,
    ) -> list[ResolvedBetEvent]:
        periods = self._build_direct_group_period_ranges(messages, direct_period_context)
        if not periods and messages:
            periods = self._build_direct_group_period_ranges(messages)
        resolved: list[ResolvedBetEvent] = []
        seen_messages: set[tuple[object, ...]] = set()

        for msg in messages:
            msg_key = self._direct_message_dedupe_key(msg)
            if msg_key in seen_messages:
                continue
            seen_messages.add(msg_key)
            summary_snapshot = self._extract_robot_summary_snapshot(msg)
            if summary_snapshot is not None and self._is_robot_summary_stats_source(msg.content):
                for play, amount in summary_snapshot.totals.items():
                    resolved.append(
                        ResolvedBetEvent(
                            group=msg.group,
                            username=msg.username,
                            sender_id=msg.sender_id,
                            ts=msg.ts,
                            period=summary_snapshot.period,
                            bettor=msg.group,
                            play=play,
                            amount=float(amount),
                            kind="bet",
                            source_kind="summary",
                        )
                    )
                continue
            parsed_content, events = self._parse_bet_events_from_message(msg)
            if self._looks_like_period_summary_billboard(parsed_content):
                continue
            is_robot_msg = self._is_group_member_robot(msg.group, msg.sender_id, msg.username, msg.group_id)
            if is_robot_msg and not any(event.kind == "cancel" for event in events):
                continue
            period = self._resolve_direct_group_period(
                msg.ts,
                periods,
                fixed_window=direct_period_context is not None,
            )
            for event in events:
                resolved.append(
                    ResolvedBetEvent(
                        group=msg.group,
                        username=msg.username,
                        sender_id=msg.sender_id,
                        ts=msg.ts,
                        period=period,
                        bettor=event.bettor or msg.username,
                        play=event.play,
                        amount=float(event.amount),
                        kind=event.kind,
                        source_kind="direct",
                        order_id=event.order_id,
                    )
                )
        return resolved

    def _direct_message_dedupe_key(self, msg: ChatMessage) -> tuple[object, ...]:
        if msg.raw_client_time or msg.raw_rand:
            return (
                msg.group,
                msg.username,
                msg.sender_id,
                self._normalize_text(msg.content),
                int(msg.raw_client_time or 0),
                int(msg.raw_rand or 0),
            )
        return (
            msg.group,
            msg.username,
            msg.sender_id,
            self._normalize_text(msg.content),
            msg.ts,
        )

    def _parse_bet_events_from_message(self, msg: ChatMessage) -> tuple[str, list[BetEvent]]:
        content = self._decode_possible_frontend_ciphertext(self._clean_text(msg.content))
        if self._looks_like_period_summary_billboard(content):
            return content, []
        cancel_event = self._parse_cancel_event(content)
        if cancel_event is not None:
            return content, [cancel_event]
        receipt_events = self._parse_receipt_bet_events(content)
        if receipt_events:
            return content, receipt_events

        events: list[BetEvent] = []
        for play, amount in self._parse_bets(content):
            events.append(
                BetEvent(
                    bettor=msg.username,
                    play=play,
                    amount=float(amount),
                    kind="bet",
                    source=content,
                )
            )
        return content, events

    def _parse_receipt_bet_events(self, content: str) -> list[BetEvent]:
        if "下注期数" not in content or "下注内容" not in content:
            return []
        bettor_match = RECEIPT_BETTOR_PATTERN.search(content)
        body_match = RECEIPT_BODY_PATTERN.search(content)
        if not bettor_match or not body_match:
            return []
        bettor = bettor_match.group("bettor").strip()
        if not bettor:
            return []
        events: list[BetEvent] = []
        for raw_line in body_match.group("body").splitlines():
            parsed = self._parse_receipt_bet_line(raw_line)
            if parsed is None:
                continue
            play, amount = parsed
            if amount <= 0:
                continue
            events.append(BetEvent(bettor=bettor, play=play, amount=amount, kind="bet", source=content))
        return events

    def _parse_receipt_bet_line(self, line: str) -> tuple[str, float] | None:
        text = self._clean_text(line).strip()
        if not text:
            return None
        play_match = RECEIPT_ALLOWED_PLAY_BET_PATTERN.match(text)
        if play_match:
            play = play_match.group("play").strip()
            amount = self._parse_amount_text(play_match.group("amount"))
            return play, amount
        return None

    def _looks_like_period_summary_billboard(self, content: str) -> bool:
        if "在线人数" in content and "总分" in content:
            return False
        if not self._period_key_from_summary_text(content):
            return False
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        summary_line_count = 0
        for line in lines[1:]:
            bodies = self._summary_bet_bodies_from_line(line)
            if not bodies:
                continue
            if any(self._parse_bets(body) for body in bodies):
                summary_line_count += 1
        return summary_line_count >= 1

    def _extract_robot_summary_snapshot(self, msg: ChatMessage) -> RobotSummarySnapshot | None:
        content = self._decode_possible_frontend_ciphertext(self._clean_text(msg.content))
        if not self._looks_like_period_summary_billboard(content):
            return None
        period = self._period_key_from_summary_text(content)
        if not period:
            return None
        totals: dict[str, float] = defaultdict(float)
        totals_by_bettor: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for raw_line in content.splitlines():
            bettor = self._summary_line_bettor_name(raw_line)
            if self._is_private_chat_proxy_bettor(bettor):
                continue
            for body in self._summary_bet_bodies_from_line(raw_line):
                for play, amount in self._parse_bets(body):
                    if play in PLAY_TYPES:
                        totals[play] += float(amount)
                        if bettor:
                            totals_by_bettor[bettor][play] += float(amount)
        if not totals:
            return None
        return RobotSummarySnapshot(
            period=period,
            group=msg.group,
            ts=msg.ts,
            totals=dict(totals),
            totals_by_bettor={bettor: dict(play_totals) for bettor, play_totals in totals_by_bettor.items()},
        )

    def _period_key_from_summary_text(self, content: str) -> str:
        clean = self._clean_text(content)
        explicit = re.search(r"(?P<period>\d{4,})\s*期(?:下注核对)?\s*[:：]", clean)
        if explicit:
            return explicit.group("period")
        bracket = re.search(r"-+\[(?:[A-Z])?(?P<period>\d{4,})(?:-\d+)?\][^\n-]{0,8}-+", clean)
        if bracket:
            return bracket.group("period")
        return ""

    def _summary_bet_bodies_from_line(self, line: str) -> list[str]:
        bodies = [match.group("body") for match in re.finditer(r"【(?P<body>.*?)】", line)]
        bodies.extend(match.group("body") for match in SUMMARY_SQUARE_BODY_PATTERN.finditer(line))
        return [body for body in bodies if self._clean_text(body)]

    def _summary_line_bettor_name(self, line: str) -> str:
        clean_line = self._clean_text(line)
        if not clean_line:
            return ""
        body_match = re.search(r"[【\[]", clean_line)
        if body_match is None:
            return ""
        prefix = clean_line[: body_match.start()].strip()
        if not prefix:
            return ""
        parts = prefix.split()
        return self._clean_text(parts[0]) if parts else ""

    def _is_private_chat_proxy_bettor(self, bettor: str) -> bool:
        text = self._clean_text(bettor)
        if not text:
            return False
        normalized = self._normalize_text(text)
        return normalized.startswith("**") or "私聊下注" in text

    def _is_robot_summary_stats_source(self, content: str) -> bool:
        text = self._decode_possible_frontend_ciphertext(self._clean_text(content))
        if self._looks_like_personal_status_summary(text):
            return False
        if self._looks_like_group_period_summary(text):
            return True
        return False

    def _looks_like_group_period_summary(self, text: str) -> bool:
        if re.search(r"\d{4,}\s*期(?:下注核对)?\s*[:：]", text):
            return True
        if "本期下注" in text and re.search(r"-+\[第?\d{4,}期\]-+", text):
            return True
        if "期下注核对" in text:
            return True
        if re.search(r"-+\[(?:[A-Z])?\d{4,}(?:-\d+)?\][^\n-]{0,8}-+", text) and not self._looks_like_personal_status_summary(text):
            return True
        return False

    def _looks_like_personal_status_summary(self, text: str) -> bool:
        personal_markers = (
            "当前积分",
            "当前盈亏",
            "当前流水",
            "冻结积分",
            "剩余积分",
            "回粮冻结",
        )
        return "本期下注" in text and any(marker in text for marker in personal_markers)

    def _build_robot_summary_reconciliation(
        self,
        messages: list[ChatMessage],
        software_totals: dict[str, float],
        period_filter: str,
    ) -> dict[str, object]:
        records = self._build_robot_summary_reconciliations(messages, {"": software_totals}, period_filter)
        return records[0] if records else {}

    def _build_robot_summary_reconciliations(
        self,
        messages: list[ChatMessage],
        software_totals_by_group: dict[str, dict[str, float]],
        period_filter: str,
    ) -> list[dict[str, object]]:
        snapshots = [
            snapshot
            for msg in messages
            if (snapshot := self._extract_robot_summary_snapshot(msg)) is not None
            and self._is_robot_summary_stats_source(msg.content)
        ]
        if period_filter:
            snapshots = [snapshot for snapshot in snapshots if snapshot.period == period_filter]
        if not snapshots:
            return []
        latest_by_group_period: dict[tuple[str, str], RobotSummarySnapshot] = {}
        for snapshot in snapshots:
            key = (snapshot.group, snapshot.period)
            previous = latest_by_group_period.get(key)
            if previous is None or snapshot.ts > previous.ts:
                latest_by_group_period[key] = snapshot
        records: list[dict[str, object]] = []
        for snapshot in sorted(
            latest_by_group_period.values(),
            key=lambda item: (item.ts, item.group, item.period),
            reverse=True,
        ):
            group_software_totals = (
                software_totals_by_group.get(snapshot.group)
                or software_totals_by_group.get("")
                or {}
            )
            records.append(
                self._format_robot_summary_reconciliation(
                    self._filtered_robot_summary_snapshot(snapshot),
                    group_software_totals,
                )
            )
        return records

    def _filtered_robot_summary_snapshot(self, snapshot: RobotSummarySnapshot) -> RobotSummarySnapshot:
        blocked_names = self._blocked_names_for_group(snapshot.group)
        if not blocked_names or not snapshot.totals_by_bettor:
            return snapshot
        totals: dict[str, float] = defaultdict(float)
        filtered_totals_by_bettor: dict[str, dict[str, float]] = {}
        for bettor, play_totals in snapshot.totals_by_bettor.items():
            if self._normalize_text(bettor) in blocked_names:
                continue
            filtered_totals_by_bettor[bettor] = dict(play_totals)
            for play, amount in play_totals.items():
                if play in PLAY_TYPES:
                    totals[play] += float(amount)
        return RobotSummarySnapshot(
            period=snapshot.period,
            group=snapshot.group,
            ts=snapshot.ts,
            totals=dict(totals),
            totals_by_bettor=filtered_totals_by_bettor,
        )

    def _format_robot_summary_reconciliation(
        self,
        snapshot: RobotSummarySnapshot,
        software_totals: dict[str, float],
    ) -> dict[str, object]:
        by_play: dict[str, dict[str, float | bool]] = {}
        for play in PLAY_TYPES:
            software_total = float(software_totals.get(play, 0.0) or 0.0)
            robot_total = float(snapshot.totals.get(play, 0.0) or 0.0)
            diff = abs(software_total - robot_total)
            if robot_total <= 0:
                ratio = 0.0 if software_total <= 0 else 1.0
            else:
                ratio = diff / robot_total
            by_play[play] = {
                "software_total": software_total,
                "robot_total": robot_total,
                "diff": diff,
                "diff_ratio": ratio,
                "within_tolerance": ratio <= 0.2,
            }
        return {
            "group": snapshot.group,
            "period": snapshot.period,
            "robot_totals": dict(snapshot.totals),
            "software_totals": {
                play: float(software_totals.get(play, 0.0) or 0.0)
                for play in PLAY_TYPES
                if float(software_totals.get(play, 0.0) or 0.0) > 0
            },
            "by_play": by_play,
        }

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

    def _event_block_name_keys(self, event: ResolvedBetEvent) -> set[str]:
        names = {
            self._normalize_text(event.username),
            self._normalize_text(event.bettor),
        }
        return {name for name in names if name}

    def _blocked_event_identity_sets(
        self,
        events: list[ResolvedBetEvent],
        blocked_name_set: set[str],
    ) -> tuple[set[str], set[str]]:
        identity_keys: set[str] = set()
        sender_keys: set[str] = set()
        for event in events:
            event_name_keys = self._event_block_name_keys(event)
            if not event_name_keys & blocked_name_set:
                continue
            identity_keys.update(event_name_keys)
            sender_key = self._normalize_text(event.sender_id)
            if sender_key:
                sender_keys.add(sender_key)
        if not sender_keys:
            return identity_keys, sender_keys
        for event in events:
            sender_key = self._normalize_text(event.sender_id)
            if sender_key and sender_key in sender_keys:
                identity_keys.update(self._event_block_name_keys(event))
        return identity_keys, sender_keys

    def _parse_bets(self, content: str) -> list[tuple[str, float]]:
        compact_events = [
            (play, amount)
            for _bettor, play, amount in self._parse_compact_bets(content, self._extract_bettor_name(content))
            if amount > 0
        ]
        if compact_events:
            return compact_events
        events: list[tuple[str, float]] = []
        for match in SIMPLE_BET_PATTERN.finditer(content):
            if not self._play_token_has_safe_boundaries(content, match.start("play"), match.group("play")):
                continue
            amount = self._parse_amount_text(match.group("amount"))
            if amount <= 0:
                continue
            events.append((match.group("play"), amount))
        if events:
            return events
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
                amount_match = re.match(r"\s*(\d[\d,]*(?:\.\d+)?)", text[i + len(play) :])
                if amount_match:
                    amount_text = amount_match.group(1)
                    matches.append((i, play, self._parse_amount_text(amount_text)))
                    i = i + len(play) + amount_match.end()
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
            if text.startswith(token, start) and self._play_token_has_safe_boundaries(text, start, token):
                return token
        return None

    def _play_token_has_safe_boundaries(self, text: str, start: int, token: str) -> bool:
        before = text[start - 1] if start > 0 else ""
        after_index = start + len(token)
        after = text[after_index] if after_index < len(text) else ""
        if before in {"极", "尾", "A", "B", "C", "a", "b", "c", "大", "小", "单", "双"}:
            return False
        if after in {"大", "小", "单", "双"}:
            return False
        return True

    def _extract_direct_group_marker(self, msg: ChatMessage) -> tuple[str, str] | None:
        if not msg.sender_id:
            return None
        if not self._is_group_member_robot(msg.group, msg.sender_id, msg.username, msg.group_id):
            return None
        content = self._decode_possible_frontend_ciphertext(self._clean_text(msg.content))
        period = self._extract_period(content)
        if not period:
            return None
        if DIRECT_CLOSE_HINT_PATTERN.search(content) or "如下订单已取消" in content:
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
            marker_start = self._find_direct_period_start_marker(messages, direct_period_context)
            accept_start = max(direct_period_context.accept_start, marker_start) if marker_start else direct_period_context.accept_start
            if accept_start >= direct_period_context.accept_end:
                return []
            return [(accept_start, direct_period_context.accept_end, direct_period_context.period)]

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

    def _find_direct_period_start_marker(
        self,
        messages: list[ChatMessage],
        direct_period_context: DirectPeriodContext,
    ) -> datetime | None:
        period_key = self._normalize_period_text(direct_period_context.period)
        if not period_key:
            return None
        for msg in sorted(messages, key=lambda item: (item.ts, int(item.raw_client_time or 0), int(item.raw_rand or 0))):
            if msg.ts < direct_period_context.start or msg.ts >= direct_period_context.end:
                continue
            if not self._is_group_member_robot(msg.group, msg.sender_id, msg.username, msg.group_id):
                continue
            content = self._decode_possible_frontend_ciphertext(self._clean_text(msg.content))
            if period_key in self._period_keys_from_text(content):
                return msg.ts
        return None

    def _period_keys_from_text(self, value: object) -> set[str]:
        text = self._clean_text(value)
        keys: set[str] = set()
        for match in re.finditer(r"\d[\d-]{3,}\d", text):
            keys.add(self._normalize_period_text(match.group(0)))
        return {key for key in keys if key}

    def _normalize_period_text(self, value: object) -> str:
        return re.sub(r"\D+", "", self._clean_text(value))

    def _resolve_direct_group_period(
        self,
        ts: datetime,
        periods: list[tuple[datetime, datetime, str]],
        fixed_window: bool = False,
    ) -> str:
        for start, end, period in periods:
            if fixed_window:
                if ts < start:
                    continue
                if end is not None and ts >= end:
                    continue
                return period
            if ts < start:
                continue
            if end is not None and ts >= end:
                continue
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
        fallback_candidates = [
            pending
            for candidates_for_user in pending_by_user.values()
            for pending in candidates_for_user
            if (
                (not period or not pending.period or pending.period == period)
                and msg.ts >= pending.ts
                and msg.ts - pending.ts <= RECEIPT_MATCH_WINDOW
            )
        ]
        unique_users = {(pending.username, pending.sender_id) for pending in fallback_candidates}
        if len(unique_users) == 1:
            return next(iter(unique_users))
        bettor_name = self._clean_text(getattr(event, "bettor", ""))
        if bettor_name:
            return bettor_name, ""
        return msg.username, msg.sender_id

    def _extract_direct_group_marker(self, msg: ChatMessage) -> tuple[str, str] | None:
        if not msg.sender_id:
            return None
        if not self._is_group_member_robot(msg.group, msg.sender_id, msg.username, msg.group_id):
            return None
        content = self._decode_possible_frontend_ciphertext(self._clean_text(msg.content))
        period = self._extract_period(content)
        if not period:
            return None
        if DIRECT_CLOSE_HINT_PATTERN.search(content) or "如下订单已取消" in content:
            return ("end", period)
        if (
            "涓嬫敞鏈熸暟" in content
            or "鏈湡涓嬫敞" in content
            or "娑撳鏁為張鐔告殶" in content
            or "閺堬剚婀℃稉瀣暈" in content
            or "下注期数" in content
            or "本期下注" in content
        ):
            return ("start", period)
        return None

    def _parse_cancel_event(self, content: str) -> BetEvent | None:
        normalized = unicodedata.normalize("NFKC", content).strip()
        normalized_key = self._normalize_text(normalized)
        rejection_match = re.search(
            r"(?P<name>[^\s:：@\-]{1,30})\s*可用积分不足.*?(?:全部无效|请重新)",
            normalized,
        )
        if rejection_match:
            return BetEvent(rejection_match.group("name").strip(), "", 0.0, "cancel", source=content)
        if normalized_key in {self._normalize_text("取消"), self._normalize_text("鍙栨秷")}:
            return BetEvent("", "", 0.0, "cancel", source=content)

        compact = re.sub(r"\s+", " ", normalized).strip()
        match = re.match(r"^@?(?P<name>[^:：\s]{1,30})[:：]?\s*(?:取消|鍙栨秷)$", compact)
        if match:
            return BetEvent(match.group("name").strip(), "", 0.0, "cancel", source=content)

        lines = [self._normalize_text(line) for line in content.splitlines() if self._normalize_text(line)]
        if len(lines) == 2 and lines[1] in {"取消", self._normalize_text("鍙栨秷")}:
            bettor = lines[0].lstrip("@").rstrip(":：").strip()
            if bettor:
                return BetEvent(bettor, "", 0.0, "cancel", source=content)

        if lines and any(("已取消" in line) or ("宸插彇娑" in line) for line in lines[1:]):
            bettor = lines[0].lstrip("@").rstrip(":：").strip()
            if bettor:
                order_ids = re.findall(r"(?:订单号|璁㈠崟鍙)[:：]?\s*([^\s]+)", content)
                return BetEvent(
                    bettor,
                    "",
                    0.0,
                    "cancel",
                    source=content,
                    order_id=",".join(order_ids),
                )
        return None

    def _find_active_period(self, bet_stack: dict[tuple[str, str], list[BetEvent]], bettor: str) -> str:
        candidates = [(key[1], len(values)) for key, values in bet_stack.items() if key[0] == bettor and key[1]]
        if not candidates:
            return ""
        candidates.sort(key=lambda item: item[1], reverse=True)
        return candidates[0][0]

    def _find_active_period_by_latest(self, latest: object, bettor: str) -> str:
        candidates = sorted(
            [key[1] for key in latest if key[0] == bettor and key[1]],
            reverse=True,
        )
        return candidates[0] if candidates else ""

    def _pop_last_bet(self, stack: list[BetEvent], play: str) -> BetEvent | None:
        for index in range(len(stack) - 1, -1, -1):
            if play and stack[index].play != play:
                continue
            return stack.pop(index)
        return None

    def _pop_last_row(self, rows: list[dict[str, object]], play: str) -> dict[str, object] | None:
        for index in range(len(rows) - 1, -1, -1):
            if play and str(rows[index].get("play", "")) != play:
                continue
            return rows.pop(index)
        return None

    def _extract_period(self, content: str) -> str:
        match = re.search(r"(\d{4,})", self._clean_text(content))
        if not match:
            return ""
        return match.group(1)

    def _looks_like_robot_identity(self, username: object, sender_id: object, group: object) -> bool:
        clean_username = self._clean_text(username)
        clean_sender_id = self._clean_text(sender_id)
        clean_group = self._clean_text(group)
        if "机器" in clean_username:
            return True
        return self._is_group_member_robot(clean_group, clean_sender_id, clean_username)

    def _extract_bettor_name(self, content: str) -> str:
        return ""

    def _is_group_member_robot(
        self,
        group: str,
        sender_id: str,
        fallback_username: str,
        group_id: str = "",
    ) -> bool:
        if "机器" in self._clean_text(fallback_username):
            return True
        group_key = self._robot_group_key(group, group_id)
        return bool(group_key and sender_id and self._group_robot_ids.get(group_key) == sender_id)

    def _robot_group_key(self, group: str, group_id: str = "") -> str:
        raw_group_id = str(group_id or "").strip()
        if raw_group_id:
            return raw_group_id
        return str(group or "").strip()

    def _detect_group_robot_sender(self, messages: list[ChatMessage]) -> str:
        if not messages:
            return ""
        latest_ts = max((msg.ts for msg in messages), default=None)
        if latest_ts is None:
            return ""
        window_start = latest_ts - ROBOT_DETECTION_WINDOW
        recent = [msg for msg in messages if msg.ts >= window_start and str(msg.sender_id or "").strip()]
        if not recent:
            return ""
        if any("机器" in self._clean_text(msg.username) for msg in recent):
            return ""

        by_sender: dict[str, list[ChatMessage]] = defaultdict(list)
        for msg in recent:
            by_sender[str(msg.sender_id).strip()].append(msg)
        ranked = sorted(by_sender.items(), key=lambda item: len(item[1]), reverse=True)
        if not ranked:
            return ""
        sender_id, sender_messages = ranked[0]
        if not any(self._looks_like_robot_message(msg.content) for msg in sender_messages):
            return ""
        return sender_id

    def _looks_like_robot_message(self, content: object) -> bool:
        text = self._decode_possible_frontend_ciphertext(self._clean_text(content))
        if not text:
            return False
        if "下注期数" in text and "下注内容" in text:
            return True
        if "彩种" in text and "期号" in text and ("结果" in text or "历史开奖" in text):
            return True
        if "当前积分" in text and ("本期下注" in text or "本期未下注" in text):
            return True
        if any(token in text for token in ("开始下注", "下注开始", "截止线", "封盘线", "已截止")):
            return True
        return False

    def _decode_possible_frontend_ciphertext(self, content: str) -> str:
        text = self._clean_text(content)
        if not self._looks_like_base64_ciphertext(text):
            return text
        decoded = self._decrypt_frontend_aas_text(text)
        logger.debug(
            "[直读群] 密文检测: raw=%s, decoded=%s, success=%s",
            self._preview_text(text),
            self._preview_text(decoded or text),
            bool(decoded),
        )
        return self._clean_text(decoded or text)

    def _preview_text(self, text: str) -> str:
        clean = self._clean_text(text)
        if len(clean) <= LOG_PREVIEW_LIMIT:
            return clean
        return clean[:LOG_PREVIEW_LIMIT] + "..."

    def _looks_like_base64_ciphertext(self, text: str) -> bool:
        compact = str(text or "").strip()
        if not compact or "\n" in compact:
            return False
        if len(compact) < 16 or len(compact) % 4 != 0:
            return False
        return bool(re.fullmatch(r"[A-Za-z0-9+/=]+", compact))

    def _decrypt_frontend_aas_text(self, ciphertext_b64: str) -> str:
        if AES is None or unpad is None:
            return ""
        try:
            raw = base64.b64decode(ciphertext_b64, validate=True)
        except Exception:
            return ""
        key = FRONTEND_AAS_KEY.encode("utf-8")
        if len(key) < 16:
            key = key + (b"\x00" * (16 - len(key)))
        try:
            decrypted = AES.new(key[:16], AES.MODE_ECB).decrypt(raw)
            plain = unpad(decrypted, AES.block_size)
            return plain.decode("utf-8", errors="ignore")
        except Exception:
            return ""

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
        if value > 100_000_000_000_000:
            value //= 1_000_000
        elif value > 10_000_000_000:
            value //= 1000
        return datetime.fromtimestamp(value)

    def _apply_sqlite_query_options(
        self,
        query: str,
        options: ParseOptions,
        client_time_unit: int = 1,
    ) -> tuple[str, list[object]]:
        clauses: list[str] = []
        params: list[object] = []
        start_time = options.start_time
        end_time = options.end_time
        if start_time is None and end_time is None and options.incremental_since is None:
            now = datetime.now()
            start_time = now - DEFAULT_SQLITE_LOAD_WINDOW
            end_time = now
            logger.debug("应用默认时间窗口: %s ~ %s", start_time, end_time)
        if start_time is not None:
            clauses.append("client_time >= ?")
            params.append(self._to_sqlite_timestamp(start_time, client_time_unit))
        if end_time is not None:
            clauses.append("client_time <= ?")
            params.append(self._to_sqlite_timestamp(end_time, client_time_unit))
        if options.group_ids:
            placeholders = ",".join("?" for _ in options.group_ids)
            if "from msg" in query:
                clauses.append(f"conversation_id in ({placeholders})")
            else:
                clauses.append(f"sid in ({placeholders})")
            params.extend(options.group_ids)
        if options.blocked_user_ids:
            placeholders = ",".join("?" for _ in options.blocked_user_ids)
            if "from msg" in query:
                clauses.append(f"sender_id not in ({placeholders})")
            else:
                clauses.append(f"sender not in ({placeholders})")
            params.extend(options.blocked_user_ids)
        if options.incremental_since is not None or options.incremental_cursor_value:
            cursor_value = (
                int(options.incremental_cursor_value)
                if options.incremental_cursor_value
                else self._to_sqlite_timestamp(options.incremental_since, client_time_unit)
            )
            cursor_rand = int(options.incremental_cursor_rand or 0)
            clauses.append("(client_time > ? or (client_time = ? and rand > ?))")
            params.extend([cursor_value, cursor_value, cursor_rand])
        where_clause = f"where {' and '.join(clauses)}" if clauses else ""
        return query.format(where_clause=where_clause), params

    def _detect_sqlite_client_time_unit(self, con: sqlite3.Connection) -> int:
        try:
            row = con.execute("select max(client_time) from message").fetchone()
        except sqlite3.DatabaseError:
            return 1
        value = int((row[0] if row else 0) or 0)
        if value > 100_000_000_000_000:
            return 1_000_000
        if value > 10_000_000_000:
            return 1000
        return 1

    def _to_sqlite_timestamp(self, value: datetime | None, unit: int) -> int:
        if value is None:
            return 0
        return int(value.timestamp() * max(1, unit))

    def _extract_message_text(self, element_desc: object, content_blob: object) -> str:
        candidates: list[str] = []
        for value in (element_desc, content_blob):
            if isinstance(value, bytes):
                candidates.append(value.decode("utf-8", errors="ignore"))
            elif value:
                candidates.append(str(value))

        for candidate in candidates:
            text = self._clean_text(candidate)
            extracted = self._extract_json_text(text)
            if extracted:
                return extracted
            compact = text.strip()
            if self._looks_like_receipt_text(compact):
                return compact
            lines = [line.strip(" @") for line in text.splitlines()]
            useful = [line for line in lines if self._looks_like_message_line(line)]
            if useful:
                return "\n".join(useful).strip()
            decoded = self._decode_possible_frontend_ciphertext(compact)
            if decoded and decoded != compact:
                return decoded
            if (
                compact
                and not compact.startswith("{")
                and not compact.startswith("[")
                and not self._looks_like_base64_ciphertext(compact)
            ):
                return compact
        return ""

    def _looks_like_receipt_text(self, text: str) -> bool:
        return bool(text and "下注期数" in text and "下注内容" in text and "余额" in text)

    def _extract_json_text(self, text: str) -> str:
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            match = re.search(r'"content"\s*:\s*"((?:\\.|[^"])*)"', text)
            if not match:
                return ""
            try:
                return bytes(match.group(1), "utf-8").decode("unicode_escape").strip()
            except Exception:
                return match.group(1).strip()
        return self._extract_text_from_json_value(payload)

    def _extract_text_from_json_value(self, value: object) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            for key in (
                "text",
                "content",
                "msg",
                "message",
                "textElement",
                "text_elem",
                "strContent",
                "StrContent",
            ):
                item = value.get(key)
                if isinstance(item, dict):
                    nested = self._extract_text_from_json_value(item)
                    if nested:
                        return nested
                elif isinstance(item, str) and item.strip():
                    return item.strip()
            for item in value.values():
                nested = self._extract_text_from_json_value(item)
                if nested:
                    return nested
        if isinstance(value, list):
            for item in value:
                nested = self._extract_text_from_json_value(item)
                if nested:
                    return nested
        return ""

    def _looks_like_message_line(self, line: str) -> bool:
        line = self._clean_text(line)
        if not line:
            return False
        if self._extract_json_text(line):
            return True
        return bool(SIMPLE_BET_PATTERN.search(line) or self._parse_compact_bets(line, ""))

    def _stringify_sqlite_content(self, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="ignore")
        return str(value)
