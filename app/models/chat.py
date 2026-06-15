from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ChatGroup:
    group_id: str
    group_name: str


@dataclass
class ChatMessage:
    ts: datetime
    group: str
    username: str
    content: str
    sender_id: str = ""
    raw_client_time: int = 0
    raw_rand: int = 0


@dataclass
class ParseOptions:
    username: str = ""
    groups: list[str] = field(default_factory=list)
    blocked_names: list[str] = field(default_factory=list)
    blocked_names_by_group: dict[str, dict[str, object]] = field(default_factory=dict)
    group_ids: list[str] = field(default_factory=list)
    blocked_user_ids: list[str] = field(default_factory=list)
    start_time: datetime | None = None
    end_time: datetime | None = None
    period_filter: str = ""
    site: str = ""
    period_window_start: datetime | None = None
    period_window_end: datetime | None = None
    period_interval_sec: int = 0
    incremental_since: datetime | None = None
    incremental_cursor_value: int = 0
    incremental_cursor_rand: int = 0

    @property
    def global_block_names(self) -> list[str]:
        return self.blocked_names

    @property
    def blacklist_users(self) -> list[str]:
        return self.global_block_names

    @property
    def masked_bettors(self) -> list[str]:
        return self.global_block_names


@dataclass
class StatsResult:
    totals: dict[str, float]
    matched_messages: int = 0
    exported_records: int = 0
    totals_by_group: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass
class DrawInfo:
    current_period: str
    current_time: datetime | None = None
    next_countdown: int = 0
    next_period: str = ""
    next_time: datetime | None = None
    auto_period: str = ""
    start_time: datetime | None = None
    interval_sec: int = 0
    source: str = "api"
    last_api_success_at: datetime | None = None


@dataclass
class LicenseInfo:
    key: str = ""
    key_hash: str = ""
    expires_at: datetime | None = None
    machine_code: str = ""
    activated_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.expires_at is not None and datetime.now() <= self.expires_at
