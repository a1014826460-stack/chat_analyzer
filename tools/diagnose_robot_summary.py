from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.models import ParseOptions
from app.services.chat_service import ChatLogService
from app.services.settings_service import SettingsService


def _parse_iso_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    return datetime.fromisoformat(text)


def _load_settings() -> dict:
    return SettingsService().load()


def _default_data_source(settings: dict) -> Path:
    raw = str(settings.get("data_source", "") or "").strip()
    if raw:
        return Path(raw).expanduser()
    fallback = str(settings.get("fallback_db_path", "") or "").strip()
    if fallback:
        return Path(fallback).expanduser()
    raise FileNotFoundError("No data source configured in settings.json")


def _build_options(settings: dict, args: argparse.Namespace) -> ParseOptions:
    selected_group_ids = list(args.group_ids or settings.get("selected_group_ids", []) or [])
    blocked_names_by_group = dict(settings.get("blocked_names_by_group", {}) or {})
    global_block_names = list(settings.get("global_block_names", settings.get("blocked_names", [])) or [])
    group_types_by_id = dict(settings.get("group_types_by_id", {}) or {})
    start_time = _parse_iso_datetime(args.start) if args.start else None
    end_time = _parse_iso_datetime(args.end) if args.end else None
    options = ParseOptions(
        username="",
        blocked_names=global_block_names,
        blocked_names_by_group=blocked_names_by_group,
        group_types_by_id=group_types_by_id,
        group_ids=[str(item).strip() for item in selected_group_ids if str(item).strip()],
        blocked_user_ids=[],
        start_time=start_time,
        end_time=end_time,
        period_filter=str(args.period or "").strip(),
        site=str(args.site or "pc28").strip(),
        period_window_start=start_time,
        period_window_end=end_time,
        period_interval_sec=int(args.period_interval_sec),
        lock_threshold_sec=int(args.lock_threshold_sec),
    )
    return options


def _json_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _serialize_diagnostics(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    serialized: list[dict[str, object]] = []
    for row in rows:
        payload: dict[str, object] = {}
        for key, value in dict(row).items():
            payload[key] = _json_value(value)
        serialized.append(payload)
    return serialized


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose robot summary reconciliation for the current chat database.")
    parser.add_argument("--data-source", help="Path to msg_0.db or text source. Defaults to settings.json data_source.")
    parser.add_argument("--period", default="", help="Optional period filter.")
    parser.add_argument("--site", default="pc28", help="Site code used for direct-period resolution.")
    parser.add_argument("--start", default="", help="Optional ISO start time, e.g. 2026-06-20T12:00:00.")
    parser.add_argument("--end", default="", help="Optional ISO end time, e.g. 2026-06-20T12:10:00.")
    parser.add_argument("--period-interval-sec", type=int, default=60, help="Direct-period interval in seconds.")
    parser.add_argument("--lock-threshold-sec", type=int, default=20, help="Lock threshold in seconds.")
    parser.add_argument("--group-ids", nargs="*", default=None, help="Optional explicit group IDs.")
    parser.add_argument("--summary-only", action="store_true", help="Print a compact summary instead of full diagnostics.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    args = parser.parse_args()

    settings = _load_settings()
    source_path = Path(args.data_source).expanduser() if args.data_source else _default_data_source(settings)
    options = _build_options(settings, args)

    service = ChatLogService()
    service.set_group_block_rules(options.blocked_names_by_group)
    service.set_group_robot_ids(dict(settings.get("group_robot_ids", {}) or {}))
    messages = service.load_messages_with_cache(source_path, options)
    group_robot_ids = service.remember_group_robots(messages)
    diagnostics = service.build_offline_robot_summary_diagnostics(
        messages,
        blocked_names=options.blocked_names,
        blocked_ids=options.blocked_user_ids,
        period_filter=options.period_filter,
        site=options.site,
        period_window_start=options.period_window_start,
        period_window_end=options.period_window_end,
        period_interval_sec=options.period_interval_sec,
        lock_threshold_sec=options.lock_threshold_sec,
        group_types_by_id=options.group_types_by_id,
    )

    payload = {
        "source_path": str(source_path),
        "site": options.site,
        "period_filter": options.period_filter,
        "group_ids": list(options.group_ids),
        "message_count": len(messages),
        "remembered_group_robot_ids": group_robot_ids,
        "diagnostics": _serialize_diagnostics(diagnostics),
    }
    if args.summary_only:
        summary_rows = []
        for item in payload["diagnostics"]:
            summary_rows.append(
                {
                    "group": item.get("group", ""),
                    "period": item.get("period", ""),
                    "robot_summary_detected": item.get("robot_summary_detected", False),
                    "software_rows_found": item.get("software_rows_found", False),
                    "summary_check_record_generated": item.get("summary_check_record_generated", False),
                    "failure_reason": item.get("failure_reason", ""),
                }
            )
        payload = {
            "source_path": payload["source_path"],
            "site": payload["site"],
            "period_filter": payload["period_filter"],
            "group_ids": payload["group_ids"],
            "message_count": payload["message_count"],
            "remembered_group_robot_ids": payload["remembered_group_robot_ids"],
            "diagnostic_count": len(summary_rows),
            "groups_with_diagnostics": sorted({str(item.get("group", "") or "") for item in summary_rows if str(item.get("group", "") or "")}),
            "diagnostics": summary_rows,
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
