from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from app.services.storage_service import ensure_parent


PLAY_ORDER = ("大单", "小单", "大双", "小双", "大", "小", "单", "双")


class SummaryCheckReportService:
    def __init__(self, export_dir: Path | str | None = None) -> None:
        base = Path(export_dir).expanduser() if export_dir else Path.cwd()
        self.base_dir = base / "summary_check"

    def save_records(
        self,
        records: list[dict[str, object]],
        diagnostics: list[dict[str, object]] | None = None,
        now: datetime | None = None,
    ) -> dict[str, list[Path]]:
        saved: dict[str, list[Path]] = {"records": [], "exceptions": []}
        diagnostics_by_key = self._diagnostics_by_key(diagnostics or [])
        for record in records:
            if not isinstance(record, dict):
                continue
            group = str(record.get("group", "") or "").strip()
            period = str(record.get("period", "") or "").strip()
            if not group or not period:
                continue
            record_path = self._record_path(record, now)
            ensure_parent(record_path)
            diagnostic = diagnostics_by_key.get((group, period), {})
            payload = self._record_payload(record, diagnostic)
            record_unchanged = self._unchanged_record(record_path, payload)
            if not record_unchanged:
                record_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                saved["records"].append(record_path)

            exception_text = self._format_exception_report(record, diagnostic)
            if exception_text and self._exception_needs_write(record, exception_text, now):
                exception_path = self._exception_path(record, now)
                ensure_parent(exception_path)
                exception_path.write_text(exception_text, encoding="utf-8")
                saved["exceptions"].append(exception_path)
        return saved

    def _unchanged_record(self, record_path: Path, payload: dict[str, object]) -> bool:
        if not record_path.exists():
            return False
        try:
            previous = json.loads(record_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        return self._payload_signature(previous) == self._payload_signature(payload)

    def _payload_signature(self, payload: dict[str, object]) -> dict[str, object]:
        return {
            "group": payload.get("group", ""),
            "period": payload.get("period", ""),
            "summary_time": payload.get("summary_time", ""),
            "software_totals": payload.get("software_totals", {}),
            "robot_totals": payload.get("robot_totals", {}),
            "by_play": payload.get("by_play", {}),
        }

    def _record_path(self, record: dict[str, object], now: datetime | None) -> Path:
        return self._dated_dir(record, now) / f"{self._file_stem(record)}_record.json"

    def _exception_path(self, record: dict[str, object], now: datetime | None) -> Path:
        return self._dated_dir(record, now) / f"{self._file_stem(record)}_exception.md"

    def _exception_needs_write(self, record: dict[str, object], exception_text: str, now: datetime | None) -> bool:
        exception_path = self._exception_path(record, now)
        if not exception_path.exists():
            return True
        try:
            return exception_path.read_text(encoding="utf-8") != exception_text
        except Exception:
            return True

    def _dated_dir(self, record: dict[str, object], now: datetime | None) -> Path:
        value = record.get("summary_time") or now or datetime.now()
        if isinstance(value, datetime):
            date_text = value.strftime("%Y-%m-%d")
        else:
            date_text = datetime.now().strftime("%Y-%m-%d")
        return self.base_dir / date_text

    def _file_stem(self, record: dict[str, object]) -> str:
        period = str(record.get("period", "") or "").strip() or "unknown-period"
        group = str(record.get("group", "") or "").strip() or "unknown-group"
        return self._safe_filename(f"{period}_{group}")

    def _safe_filename(self, value: str) -> str:
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "").strip())
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
        return cleaned[:120] or "summary-check"

    def _record_payload(self, record: dict[str, object], diagnostic: dict[str, object]) -> dict[str, object]:
        return {
            "saved_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
            "group": str(record.get("group", "") or ""),
            "period": str(record.get("period", "") or ""),
            "summary_time": self._json_value(record.get("summary_time")),
            "software_totals": dict(record.get("software_totals", {}) or {}),
            "robot_totals": dict(record.get("robot_totals", {}) or {}),
            "by_play": dict(record.get("by_play", {}) or {}),
            "diagnostic": self._json_value(diagnostic),
        }

    def _json_value(self, value: object) -> object:
        if isinstance(value, datetime):
            return value.isoformat(sep=" ", timespec="seconds")
        if isinstance(value, dict):
            return {str(key): self._json_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._json_value(item) for item in value]
        return value

    def _format_exception_report(self, record: dict[str, object], diagnostic: dict[str, object]) -> str:
        abnormal_rows = self._abnormal_rows(record)
        if not abnormal_rows:
            return ""
        group = str(record.get("group", "") or "")
        period = str(record.get("period", "") or "")
        lines = [
            "# 机器人汇总校验异常报告",
            "",
            f"群组: {group}",
            f"期号: {period}",
            "",
            "## 异常玩法",
        ]
        for play, row in abnormal_rows:
            software_total = float(row.get("software_total", 0.0) or 0.0)
            robot_total = float(row.get("robot_total", 0.0) or 0.0)
            diff = float(row.get("diff", abs(software_total - robot_total)) or 0.0)
            lines.append(
                f"{play} | 软件 {software_total:,.0f} | 机器人 {robot_total:,.0f} | 偏差 {diff:,.0f} | 异常"
            )
        lines.extend(["", "## 可能原因"])
        lines.extend(f"- {reason}" for reason in self._exception_reasons(abnormal_rows, diagnostic))
        lines.extend(["", "## 证据"])
        lines.append(f"- robot_summary_detected: {bool(diagnostic.get('robot_summary_detected', False))}")
        lines.append(f"- misclassified_as_user_bet: {bool(diagnostic.get('misclassified_as_user_bet', False))}")
        lines.append(f"- software_rows_found: {bool(diagnostic.get('software_rows_found', False))}")
        lines.append(f"- software_row_count: {int(diagnostic.get('software_row_count', 0) or 0)}")
        return "\n".join(lines) + "\n"

    def _abnormal_rows(self, record: dict[str, object]) -> list[tuple[str, dict[str, object]]]:
        by_play = dict(record.get("by_play", {}) or {})
        rows: list[tuple[str, dict[str, object]]] = []
        for play in PLAY_ORDER:
            row = dict(by_play.get(play, {}) or {})
            if row and not bool(row.get("within_tolerance", False)):
                rows.append((play, row))
        return rows

    def _exception_reasons(
        self,
        abnormal_rows: list[tuple[str, dict[str, object]]],
        diagnostic: dict[str, object],
    ) -> list[str]:
        reasons: list[str] = []
        if diagnostic and not bool(diagnostic.get("software_rows_found", False)):
            reasons.append("没有拿到同群同期的软件侧 rows，无法完成有效对账。")
        if any(float(row.get("robot_total", 0.0) or 0.0) > float(row.get("software_total", 0.0) or 0.0) for _, row in abnormal_rows):
            reasons.append("机器人侧金额高于软件侧，可能有机器人汇总中的下注未进入软件侧 rows。")
        if any(float(row.get("software_total", 0.0) or 0.0) > float(row.get("robot_total", 0.0) or 0.0) for _, row in abnormal_rows):
            reasons.append("软件侧金额高于机器人侧，可能有软件识别到的下注未进入机器人核对账单。")
        if bool(diagnostic.get("misclassified_as_user_bet", False)):
            reasons.append("机器人汇总疑似被错误归入用户下注链路，需要检查消息分类。")
        if not reasons:
            reasons.append("当前只能确认玩法金额不一致，请结合原始机器人汇总和软件侧 rows 继续复核。")
        return reasons

    def _diagnostics_by_key(self, diagnostics: list[dict[str, object]]) -> dict[tuple[str, str], dict[str, object]]:
        result: dict[tuple[str, str], dict[str, object]] = {}
        for item in diagnostics:
            if not isinstance(item, dict):
                continue
            group = str(item.get("group", "") or "")
            period = str(item.get("period", "") or "")
            if group or period:
                result[(group, period)] = item
        return result
