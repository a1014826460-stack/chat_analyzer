from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime
from datetime import timedelta
from pathlib import Path

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtWidgets import QFileDialog, QListWidgetItem, QMessageBox

from app.models import ParseOptions, StatsResult
from app.services.account_resolver import ResolvedDatabase
from app.services.chat_service import PLAY_TYPES, RobotSummarySnapshot
from app.services.summary_check_report_service import SummaryCheckReportService
from app.utils.fetch_date import _SITE_INTERVAL_SEC


logger = logging.getLogger(__name__)


class MainWindowDataMixin:
    def _chart_group_filter_items(self) -> list[dict[str, object]]:
        if hasattr(self, "_group_filter_items"):
            return list(self._group_filter_items())
        items: list[dict[str, object]] = []
        group_list = getattr(self, "group_list", None)
        if group_list is None:
            return items
        for index in range(group_list.count()):
            item = group_list.item(index)
            group_id = str(item.data(Qt.UserRole) or item.data(32) or "").strip()
            group_name = str(item.data(Qt.UserRole + 1) or item.data(33) or item.text()).strip()
            if not group_name:
                continue
            items.append(
                {
                    "group_id": group_id or group_name,
                    "group_name": group_name,
                    "checked": item.checkState() == Qt.Checked,
                }
            )
        return items

    def _push_chart_group_filters(self) -> None:
        chart_window = getattr(self, "chart_window", None)
        if chart_window is None or not hasattr(chart_window, "sync_visible_groups"):
            return
        chart_window.sync_visible_groups(MainWindowDataMixin._chart_group_filter_items(self))

    def _load_initial_state(self) -> None:
        if getattr(self, "analysis_page", None) is None:
            return
        recent = self.settings.get("recent_usernames", [])
        if hasattr(self.username_combo, "clear"):
            self.username_combo.clear()
        if isinstance(recent, list):
            self.username_combo.addItems([str(item) for item in recent if str(item).strip()])
        username = str(self.settings.get("username", "")).strip()
        if username:
            self.username_combo.setCurrentText(username)
        if hasattr(self, "resolved_path_edit"):
            self.resolved_path_edit.setText(str(self.settings.get("data_source", "")).strip())
        self.manual_db_edit.setText(str(self.settings.get("fallback_db_path", "")).strip())
        self._query_period_overrides_by_site = {}
        self._query_period_override = ""
        self._manual_period_override = False
        if hasattr(self, "global_block_names_edit") and hasattr(self, "_global_block_names"):
            self.global_block_names_edit.setPlainText("\n".join(self._global_block_names()))
        if hasattr(self, "period_input"):
            if self._active_site:
                draw_infos = getattr(self, "_draw_infos", {})
                current_info = draw_infos.get(self._active_site) if isinstance(draw_infos, dict) else None
                default_period = self._default_query_period(current_info) if current_info is not None and hasattr(self, "_default_query_period") else ""
                self.period_input.setText(default_period)
            else:
                self.period_input.setText("")
        now = QDateTime.currentDateTime()
        saved_start = self._settings_datetime("advanced_time_start")
        saved_end = self._settings_datetime("advanced_time_end")
        advanced_enabled = bool(self.settings.get("advanced_time_filter_enabled", False))
        if hasattr(self, "advanced_time_frame"):
            self.advanced_time_frame.setVisible(advanced_enabled)
        if hasattr(self, "advanced_time_toggle"):
            self.advanced_time_toggle.setText("- 高级时间筛选" if advanced_enabled else "+ 高级时间筛选")
        if hasattr(self, "end_edit"):
            self.end_edit.setDateTime(saved_end or now)
        if hasattr(self, "start_edit"):
            self.start_edit.setDateTime(saved_start or now.addDays(-1))
        if hasattr(self, "_refresh_block_rule_summary"):
            self._refresh_block_rule_summary()
        self._refresh_block_rule_group_selector()
        self._refresh_license_banner()
        if getattr(self, "_require_activation", False) and not self.license_service.is_activated():
            self.tabs.setCurrentWidget(self.license_page)
            return
        if username:
            self._resolve_database(silent=True)
            return
        if self._active_site:
            self._sync_chart_status()

    def _apply_initial_splitter_sizes(self) -> None:
        if not hasattr(self, "main_splitter"):
            return
        settings = getattr(self, "settings", {}) or {}
        saved_sizes = settings.get("main_splitter_sizes", [])
        if (
            isinstance(saved_sizes, list)
            and len(saved_sizes) == 2
            and all(isinstance(value, int) and value > 0 for value in saved_sizes)
        ):
            self.main_splitter.setSizes([int(saved_sizes[0]), int(saved_sizes[1])])
            return
        total_width = 0
        if hasattr(self, "width"):
            try:
                total_width = int(self.width() or 0)
            except Exception:
                total_width = 0
        total_width = max(total_width, 1400)
        left_width = max(240, int(total_width * 0.24))
        left_width = min(left_width, total_width - 1)
        self.main_splitter.setSizes([left_width, total_width - left_width])

    def _settings_datetime(self, key: str) -> QDateTime | None:
        raw = str(self.settings.get(key, "")).strip()
        if not raw:
            return None
        value = QDateTime.fromString(raw, Qt.ISODate)
        return value if value.isValid() else None

    def _resolve_database(self, silent: bool = False) -> None:
        username = self.username_combo.currentText().strip()
        logger.debug("Resolve database requested username=%s silent=%s", username, silent)
        if not username:
            if not silent:
                QMessageBox.information(self, "缺少用户名", "请先输入用户名。")
                if hasattr(self, "_set_status"):
                    self._set_status("请先输入用户名。", "info")
            return
        resolved = self.account_resolver.resolve(username)
        if resolved is None:
            if hasattr(self, "_remember_username"):
                self._remember_username(username)
            if hasattr(self, "_save_settings"):
                self._save_settings()
            diagnostic = self.account_resolver.get_diagnostic()
            self.resolved_db = None
            if hasattr(self, "auto_bet_panel"):
                self.auto_bet_panel.setVisible(False)
            has_saved_source = bool(
                hasattr(self, "resolved_path_edit")
                and hasattr(self.resolved_path_edit, "text")
                and self.resolved_path_edit.text().strip()
            )
            if not has_saved_source and hasattr(self, "resolved_path_edit") and hasattr(self.resolved_path_edit, "clear"):
                self.resolved_path_edit.clear()
            if not has_saved_source and hasattr(self, "group_list") and hasattr(self.group_list, "clear"):
                self.group_list.clear()
            self._refresh_block_rule_group_selector()
            self.db_status_label.setText(diagnostic.format_message() if diagnostic else "未找到数据库。")
            self.status_label.setText("自动定位数据库失败，请手动选择数据源。")
            self.fallback_box.setVisible(True)
            logger.warning("Resolve database failed username=%s", username)
            return
        self.resolved_db = resolved
        self._connect_auto_bet_panel()
        if hasattr(self, "_bootstrap_server_mode"):
            self._bootstrap_server_mode()
        self.resolved_path_edit.setText(str(resolved.msg_db))
        self.db_status_label.setText(f"已定位 {resolved.account_name} -> {resolved.msg_db}")
        self.status_label.setText("数据库已定位，可以加载消息。")
        self.fallback_box.setVisible(False)
        self._remember_username(username)
        self._load_groups_from_current_source()
        self._save_settings()
        logger.debug("Resolve database succeeded username=%s path=%s", username, resolved.msg_db)

    def _load_groups_from_current_source(self) -> None:
        source_path = self._current_source_path()
        if source_path is None or not source_path.exists():
            logger.debug("Skip group loading; source missing: %s", source_path)
            return
        groups = self.chat_service.list_groups_from_db(source_path)
        settings = getattr(self, "settings", {})
        group_check_memory_by_id = {
            str(key).strip(): bool(value)
            for key, value in dict(settings.get("group_check_memory_by_id", {}) or {}).items()
            if str(key).strip()
        }
        selected_group_ids = {
            str(item).strip()
            for item in settings.get("selected_group_ids", [])
            if str(item).strip()
        }
        selected_group_mode = str(settings.get("selected_group_mode", "")).strip()
        restore_selection = bool(selected_group_ids) and selected_group_mode != "all"
        self.group_list.blockSignals(True)
        self.group_list.clear()
        for group in groups:
            item = QListWidgetItem(group.group_name)
            item.setData(Qt.UserRole, group.group_id)
            item.setData(Qt.UserRole + 1, group.group_name)
            item.setData(32, group.group_id)
            item.setData(33, group.group_name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            if group.group_id in group_check_memory_by_id:
                check_state = Qt.Checked if group_check_memory_by_id[group.group_id] else Qt.Unchecked
            elif selected_group_mode == "none":
                check_state = Qt.Unchecked
            elif selected_group_mode == "all" or not restore_selection or group.group_id in selected_group_ids:
                check_state = Qt.Checked
            else:
                check_state = Qt.Unchecked
            item.setCheckState(check_state)
            self.group_list.addItem(item)
        self.group_list.blockSignals(False)
        self._refresh_block_rule_group_selector()
        self._refresh_auto_bet_groups()
        MainWindowDataMixin._push_chart_group_filters(self)
        logger.debug("Loaded %d groups from %s", len(groups), source_path)

    def _pick_manual_data_source(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择数据源",
            self.manual_db_edit.text().strip(),
            "数据文件 (*.db *.sqlite *.txt);;所有文件 (*.*)",
        )
        if file_path:
            self.manual_db_edit.setText(file_path)
            logger.debug("Manual data source picked: %s", file_path)

    def _load_manual_data_source(self) -> None:
        source_path = Path(self.manual_db_edit.text().strip()).expanduser()
        logger.debug("Load manual data source requested path=%s", source_path)
        if not source_path.exists():
            QMessageBox.warning(self, "文件不存在", "选择的数据源不存在。")
            if hasattr(self, "_set_status"):
                self._set_status("手动数据源不存在。", "warning")
            return
        self.resolved_db = ResolvedDatabase(
            account_name=self.username_combo.currentText().strip() or "manual",
            accid="manual",
            im_appid="manual",
            config_dir=source_path.parent,
            im_db=source_path,
            msg_db=source_path,
        )
        self.resolved_path_edit.setText(str(source_path))
        self.db_status_label.setText(f"正在使用手动数据源: {source_path}")
        self.status_label.setText("已选择手动数据源。")
        self._load_groups_from_current_source()
        self._save_settings()

    def _compute_load_signature(self, incremental: bool) -> tuple:
        source = self._current_source_path()
        options = self._gather_parse_options()
        return (
            str(source) if source else "",
            options.username,
            tuple(options.groups),
            tuple(options.blocked_names),
            options.period_filter,
            options.site,
            options.period_window_start.isoformat(sep=" ") if options.period_window_start else "",
            options.period_window_end.isoformat(sep=" ") if options.period_window_end else "",
            options.period_interval_sec,
            incremental,
        )

    def _build_load_options(self, incremental: bool) -> tuple[Path, ParseOptions, tuple, bool]:
        source = self._current_source_path()
        if source is None:
            raise FileNotFoundError("No data source selected")
        options = self._gather_parse_options()
        advanced_time_check = getattr(self, "advanced_time_check", None)
        advanced_time_frame = getattr(self, "advanced_time_frame", None)
        advanced_time_enabled = (
            advanced_time_check is not None
            and hasattr(advanced_time_check, "isChecked")
            and advanced_time_check.isChecked()
        ) or (
            advanced_time_frame is not None
            and hasattr(advanced_time_frame, "isVisible")
            and advanced_time_frame.isVisible()
        )
        if advanced_time_enabled:
            if hasattr(self, "start_edit"):
                options.start_time = self.start_edit.dateTime().toPython()
            if hasattr(self, "end_edit"):
                options.end_time = self.end_edit.dateTime().toPython()
        if incremental:
            cursor = self._last_message_cursor.get(self._active_site or "")
            if cursor:
                options.incremental_cursor_value = int(cursor[0])
                options.incremental_cursor_rand = int(cursor[1])
        return source, options, self._compute_load_signature(incremental), incremental

    def _run_load_pipeline(
        self,
        source_path: Path,
        options: ParseOptions,
        current_sig: tuple,
        load_seq: int,
        active_site: str,
        old_cursor_snapshot: tuple[int, int] | None,
    ) -> dict[str, object]:
        self.chat_service.set_group_block_rules(options.blocked_names_by_group)
        self.chat_service.set_group_robot_ids(dict(getattr(self, "group_robot_ids", {}) or {}))
        messages = self.chat_service.load_messages_with_cache(source_path, options)
        group_robot_ids = self.chat_service.remember_group_robots(messages)
        visual_rows, stats = self.chat_service.analyze_bets(
            messages,
            options.blocked_names,
            options.blocked_user_ids,
            options.period_filter,
            options.site,
            options.period_window_start,
            options.period_window_end,
            options.period_interval_sec,
            options.lock_threshold_sec,
            options.group_types_by_id,
        )
        self._log_load_diagnostics(source_path, options, messages, visual_rows, stats)
        new_cursor = self.chat_service.get_cached_cursor(messages)
        return {
            "seq": load_seq,
            "options": options,
            "active_site": active_site,
            "current_messages": messages,
            "current_visual_rows": visual_rows,
            "current_stats": stats,
            "group_robot_ids": group_robot_ids,
            "old_cursor": old_cursor_snapshot,
            "new_cursor": new_cursor,
            "short_circuit": False,
            "current_sig": current_sig,
            "replace_chart": not options.incremental_cursor_value,
        }

    def _log_load_diagnostics(
        self,
        source_path: Path,
        options: ParseOptions,
        messages: list[object],
        visual_rows: list[dict[str, object]],
        stats: object,
    ) -> None:
        stats_matched = int(getattr(stats, "matched_messages", 0) or 0)
        totals_by_group = getattr(stats, "totals_by_group", {}) or {}
        selected_group_ids = ",".join(str(item) for item in options.group_ids)
        total_group_amounts = {
            str(group): round(sum(float(value or 0) for value in dict(totals).values()), 2)
            for group, totals in dict(totals_by_group).items()
        }
        logger.debug(
            "Load diagnostics source=%s site=%s username=%s groups=%d group_ids=%d "
            "selected_group_ids=%s period=%s start=%s end=%s cursor=%s/%s "
            "messages=%d matched=%d rows=%d totals_by_group=%d group_amounts=%s",
            source_path,
            options.site or "",
            options.username or "",
            len(options.groups),
            len(options.group_ids),
            selected_group_ids,
            options.period_filter or "",
            options.start_time.isoformat(sep=" ") if options.start_time else "",
            options.end_time.isoformat(sep=" ") if options.end_time else "",
            int(options.incremental_cursor_value or 0),
            int(options.incremental_cursor_rand or 0),
            len(messages),
            stats_matched,
            len(visual_rows),
            len(totals_by_group),
            total_group_amounts,
        )

    def _apply_load_result(self, result: dict[str, object]) -> None:
        next_messages = list(result.get("current_messages", []))
        next_visual_rows = list(result.get("current_visual_rows", []))
        next_stats = result.get("current_stats")
        next_signature = (
            tuple(
                (
                    getattr(message, "ts", None),
                    getattr(message, "group", ""),
                    getattr(message, "username", ""),
                    getattr(message, "sender_id", ""),
                    getattr(message, "content", ""),
                    getattr(message, "raw_client_time", 0),
                    getattr(message, "raw_rand", 0),
                )
                for message in next_messages
            ),
            tuple(
                sorted(
                    tuple(sorted(dict(row).items()))
                    for row in next_visual_rows
                    if isinstance(row, dict)
                )
            ),
            tuple(sorted(dict(getattr(next_stats, "totals", {}) or {}).items())) if next_stats is not None else (),
        )
        should_refresh_ui = next_signature != getattr(self, "_last_result_signature", None)
        self._last_result_signature = next_signature

        self.current_messages = next_messages
        if hasattr(self, "_record_raw_chat_messages"):
            self._record_raw_chat_messages(self.current_messages)
        self.current_visual_rows = next_visual_rows
        self.current_stats = next_stats
        group_robot_ids = result.get("group_robot_ids")
        if isinstance(group_robot_ids, dict):
            self.group_robot_ids = {str(key): str(value) for key, value in group_robot_ids.items()}
        self._last_loaded_signature = result.get("current_sig")
        new_cursor = result.get("new_cursor")
        if self._active_site and new_cursor:
            self._last_message_cursor[self._active_site] = new_cursor
        self.status_label.setText(f"已加载 {len(self.current_messages):,} 条消息。")
        if should_refresh_ui:
            self._refresh_message_view()
            self._update_chart_data(replace=bool(result.get("replace_chart", False)))
            self._sync_stats_from_accumulated_visual_rows()
        self._sync_chart_status()
        logger.debug("Load messages applied count=%d", len(self.current_messages))

    def _sync_stats_from_accumulated_visual_rows(self) -> None:
        stats = getattr(self, "current_stats", None)
        if stats is None:
            return
        rows = MainWindowDataMixin._accumulated_visual_rows(self)
        if not rows:
            return

        totals: dict[str, float] = defaultdict(float)
        totals_by_group: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        software_rows_by_group_period: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
        non_summary_seen: set[tuple[str, str]] = set()
        summary_fallback_rows: list[dict[str, object]] = []

        for row in rows:
            group = str(row.get("group", "") or "")
            period = str(row.get("period", "") or "").strip()
            play = str(row.get("play", "") or "")
            if not play:
                continue
            source_kind = str(row.get("source_kind", "") or "")
            if source_kind == "summary":
                summary_fallback_rows.append(dict(row))
                continue
            amount = float(row.get("amount", 0.0) or 0.0)
            totals[play] += amount
            if group:
                totals_by_group[group][play] += amount
                if period:
                    software_rows_by_group_period[(group, period)].append(
                        {"play": play, "amount": amount, "time": row.get("time")}
                    )
                non_summary_seen.add((group, play))

        for row in summary_fallback_rows:
            group = str(row.get("group", "") or "")
            play = str(row.get("play", "") or "")
            if not play:
                continue
            if group and (group, play) in non_summary_seen:
                continue
            amount = float(row.get("amount", 0.0) or 0.0)
            totals[play] += amount
            if group:
                totals_by_group[group][play] += amount

        summary_messages = list(getattr(self, "current_messages", []) or [])
        raw_history = list(getattr(self, "raw_chat_messages", []) or [])
        if raw_history:
            seen_keys = {
                (
                    getattr(message, "ts", None),
                    getattr(message, "group", ""),
                    getattr(message, "username", ""),
                    getattr(message, "sender_id", ""),
                    getattr(message, "content", ""),
                    getattr(message, "raw_client_time", 0),
                    getattr(message, "raw_rand", 0),
                )
                for message in summary_messages
            }
            for message in raw_history:
                key = (
                    getattr(message, "ts", None),
                    getattr(message, "group", ""),
                    getattr(message, "username", ""),
                    getattr(message, "sender_id", ""),
                    getattr(message, "content", ""),
                    getattr(message, "raw_client_time", 0),
                    getattr(message, "raw_rand", 0),
                )
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                summary_messages.append(message)

        records = []
        reconciliation_builder = getattr(self.chat_service, "_build_robot_summary_reconciliations", None)
        if callable(reconciliation_builder):
            records = reconciliation_builder(
                summary_messages,
                {key: list(value) for key, value in software_rows_by_group_period.items()},
                "",
            )
        if not records:
            records = MainWindowDataMixin._rebuild_summary_check_records(
                self,
                getattr(stats, "summary_check_records", []) or [],
                {key: list(value) for key, value in software_rows_by_group_period.items()},
            )
        summary_check = records[0] if records else {}
        diagnostics: list[dict[str, object]] = []
        diagnostic_builder = getattr(self.chat_service, "build_summary_check_diagnostics", None)
        if callable(diagnostic_builder):
            diagnostics = diagnostic_builder(
                summary_messages,
                {key: list(value) for key, value in software_rows_by_group_period.items()},
                str(summary_check.get("period", "") or ""),
                records,
                group_types_by_id=dict(getattr(self, "group_types_by_id", {}) or {}),
            )
        self.current_visual_rows = rows
        self.current_stats = StatsResult(
            totals=dict(totals),
            matched_messages=int(getattr(stats, "matched_messages", 0) or 0),
            exported_records=int(getattr(stats, "exported_records", 0) or 0),
            totals_by_group={group: dict(group_totals) for group, group_totals in totals_by_group.items()},
            summary_check_period=str(summary_check.get("period", "") or ""),
            summary_check_totals=dict(summary_check.get("robot_totals", {}) or {}),
            summary_check_by_play=dict(summary_check.get("by_play", {}) or {}),
            summary_check_records=records,
            summary_check_diagnostics=[dict(item) for item in diagnostics if isinstance(item, dict)],
            unresolved_receipts=[dict(row) for row in getattr(stats, "unresolved_receipts", []) or []],
        )
        MainWindowDataMixin._persist_summary_check_records(self, records, diagnostics)

    def _persist_summary_check_records(
        self,
        records: list[dict[str, object]],
        diagnostics: list[dict[str, object]],
    ) -> None:
        if not records:
            return
        report_service = getattr(self, "summary_check_report_service", None)
        if report_service is None:
            settings = getattr(self, "settings", {}) or {}
            export_dir = str(dict(settings).get("export_dir", "") or "").strip()
            report_service = SummaryCheckReportService(Path(export_dir).expanduser() if export_dir else Path.cwd())
            self.summary_check_report_service = report_service
        try:
            report_service.save_records([dict(record) for record in records], [dict(item) for item in diagnostics])
        except Exception:
            logger.warning("Failed to persist summary check records", exc_info=True)

    def _accumulated_visual_rows(self) -> list[dict[str, object]]:
        chart_window = getattr(self, "chart_window", None)
        period_rows = getattr(chart_window, "_period_rows", None)
        if isinstance(period_rows, list) and period_rows:
            return [dict(row) for row in period_rows if isinstance(row, dict)]
        return [dict(row) for row in getattr(self, "current_visual_rows", []) or [] if isinstance(row, dict)]

    def _rebuild_summary_check_records(
        self,
        records: list[dict[str, object]],
        software_rows_by_group_period: dict[tuple[str, str], list[dict[str, object]]],
    ) -> list[dict[str, object]]:
        chat_service = getattr(self, "chat_service", None)
        if chat_service is None or not records:
            return []
        rebuilt: list[dict[str, object]] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            group = str(record.get("group", "") or "")
            period = str(record.get("period", "") or "").strip()
            if not period:
                continue
            software_rows = software_rows_by_group_period.get((group, period)) or software_rows_by_group_period.get(("", period))
            summary_time = record.get("summary_time")
            if not isinstance(summary_time, datetime):
                summary_time = datetime.now()
            software_totals = chat_service._software_totals_until_snapshot(software_rows or [], summary_time)
            if not software_totals:
                continue
            snapshot = RobotSummarySnapshot(
                period=period,
                group=group,
                ts=summary_time,
                totals={
                    play: float(amount or 0.0)
                    for play, amount in dict(record.get("robot_totals", {}) or {}).items()
                    if play in PLAY_TYPES
                },
                totals_by_bettor={},
            )
            rebuilt.append(chat_service._format_robot_summary_reconciliation(snapshot, software_totals))
        return rebuilt

    def _load_filtered_messages(self, notify_missing_source: bool = True) -> None:
        if getattr(self, "_message_load_in_progress", False):
            logger.debug("Skip message load; previous load is still running")
            return
        try:
            source_path, options, current_sig, _incremental = self._build_load_options(True)
        except FileNotFoundError:
            if notify_missing_source:
                QMessageBox.information(self, "没有数据源", "请先自动定位或手动选择数据源。")
            if hasattr(self, "_set_status"):
                self._set_status("没有数据源，请先选择数据源。", "info")
            return
        self._message_load_in_progress = True
        self._message_load_sequence += 1
        load_seq = self._message_load_sequence
        self.status_label.setText("正在加载消息...")
        logger.debug("Submit message load seq=%s source=%s site=%s", load_seq, source_path, self._active_site)
        future = self._data_worker.submit(
            self._run_load_pipeline,
            source_path,
            options,
            current_sig,
            load_seq,
            self._active_site or "",
            self._last_message_cursor.get(self._active_site or ""),
        )

        def _forward_result(done_future) -> None:
            try:
                result = done_future.result()
            except Exception as exc:
                logger.exception("Failed to load messages from %s", source_path)
                result = {"seq": load_seq, "error": exc}
            self._load_result_ready.emit(result)

        future.add_done_callback(_forward_result)

    def _handle_load_result_ready(self, result: object) -> None:
        self._message_load_in_progress = False
        if not isinstance(result, dict):
            return
        if int(result.get("seq", 0) or 0) != self._message_load_sequence:
            logger.debug("Ignore stale load result seq=%s current=%s", result.get("seq"), self._message_load_sequence)
            return
        error = result.get("error")
        if error is not None:
            self.status_label.setText("加载消息失败。")
            QMessageBox.warning(self, "加载失败", str(error))
            return
        self._apply_load_result(result)

    def _on_message_refresh_tick(self) -> None:
        if getattr(self, "_message_load_in_progress", False):
            logger.debug("Skip auto message refresh; previous load is still running")
            return
        if MainWindowDataMixin._active_site_is_within_lock_threshold(self):
            logger.debug(
                "Skip auto message refresh; site=%s countdown=%s threshold=%s",
                getattr(self, "_active_site", "") or "",
                MainWindowDataMixin._active_site_countdown(self),
                int(getattr(self, "_lock_threshold_sec", 0) or 0),
            )
            if hasattr(self, "_sync_chart_status"):
                self._sync_chart_status()
            return
        self._load_filtered_messages(notify_missing_source=False)

    def _active_site_countdown(self) -> int | None:
        active_site = getattr(self, "_active_site", "") or ""
        if not active_site:
            return None
        draw_infos = getattr(self, "_draw_infos", {}) or {}
        info = draw_infos.get(active_site) if isinstance(draw_infos, dict) else None
        if info is None:
            return None
        try:
            return int(getattr(info, "next_countdown", 0) or 0)
        except (TypeError, ValueError):
            return None

    def _active_site_is_within_lock_threshold(self) -> bool:
        threshold = int(getattr(self, "_lock_threshold_sec", 0) or 0)
        if threshold <= 0:
            return False
        countdown = MainWindowDataMixin._active_site_countdown(self)
        return countdown is not None and 0 <= countdown <= threshold

    def _update_chart_data(self, replace: bool = False) -> None:
        if hasattr(self, "chart_window"):
            MainWindowDataMixin._push_chart_group_filters(self)
            if replace and hasattr(self.chart_window, "replace_rows"):
                self.chart_window.replace_rows(self.current_visual_rows)
            else:
                self.chart_window.set_rows(self.current_visual_rows)
            self.chart_window.update_activity(self.current_visual_rows)

    def _gather_parse_options(self) -> ParseOptions:
        selected_groups: list[str] = []
        selected_group_ids: list[str] = []
        for index in range(self.group_list.count()):
            item = self.group_list.item(index)
            if item.checkState() != Qt.Checked:
                continue
            selected_groups.append(str(item.data(33) or item.text()))
            selected_group_ids.append(str(item.data(32) or ""))

        site = self._active_site or ""
        draw_infos = getattr(self, "_draw_infos", {})
        current_info = draw_infos.get(site) if site and isinstance(draw_infos, dict) else None
        period_filter = self.period_input.text().strip() if hasattr(self, "period_input") else ""
        if current_info is not None:
            period_filter = period_filter or str(getattr(current_info, "next_period", "") or getattr(current_info, "current_period", "")).strip()
        period_interval_sec = int(getattr(current_info, "interval_sec", 0) or _SITE_INTERVAL_SEC.get(site, 180))
        period_window_start = getattr(current_info, "start_time", None) if current_info is not None else None
        period_window_end = getattr(current_info, "next_time", None) if current_info is not None else None
        if period_window_start is None and period_window_end is not None and period_interval_sec > 0:
            period_window_start = period_window_end - timedelta(seconds=period_interval_sec)
        global_block_names = (
            self._global_block_names()
            if hasattr(self, "_global_block_names")
            else (self._blocked_names() if hasattr(self, "_blocked_names") else [])
        )
        return ParseOptions(
            username="",
            groups=selected_groups,
            blocked_names=global_block_names,
            blocked_names_by_group=self.group_block_rules,
            group_types_by_id=dict(getattr(self, "group_types_by_id", {}) or {}),
            group_ids=selected_group_ids,
            blocked_user_ids=[],
            period_filter=period_filter,
            site=site,
            period_window_start=period_window_start,
            period_window_end=period_window_end,
            period_interval_sec=period_interval_sec,
            lock_threshold_sec=int(getattr(self, "_lock_threshold_sec", 0) or 0),
        )

    # ------------------------------------------------------------------
    # Auto Bet Integration
    # ------------------------------------------------------------------

    def _stable_payload_signature(self, payload: object) -> str:
        try:
            return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        except TypeError:
            return repr(payload)

    def _arm_auto_bet_refresh_burst(self, now: datetime | None = None) -> None:
        current = now or datetime.now()
        self._auto_bet_refresh_burst_until = current + timedelta(seconds=20)

    def _auto_bet_panel_refresh_interval_seconds(self, now: datetime | None = None) -> int:
        current = now or datetime.now()
        burst_until = getattr(self, "_auto_bet_refresh_burst_until", None)
        if isinstance(burst_until, datetime) and current <= burst_until:
            return 2
        return 10

    def _auto_bet_refresh_due(self, key: str, now: datetime | None = None, *, force: bool = False) -> bool:
        if force:
            setattr(self, key, now or datetime.now())
            return True
        current = now or datetime.now()
        last = getattr(self, key, None)
        interval = MainWindowDataMixin._auto_bet_panel_refresh_interval_seconds(self, current)
        if isinstance(last, datetime) and (current - last).total_seconds() < interval:
            return False
        setattr(self, key, current)
        return True

    def _refresh_auto_bet_frequency_analysis(
        self,
        site: str,
        target_period: str = "",
        now: datetime | None = None,
        *,
        force: bool = False,
    ) -> None:
        """Publish an explicit history-cache analysis update to the auto-bet panel."""
        panel = getattr(self, "auto_bet_panel", None)
        if getattr(self, "server_mode_settings", None) and self.server_mode_settings.enabled:
            if getattr(self, "_server_frequency_poll_in_progress", False):
                return
            if not MainWindowDataMixin._auto_bet_refresh_due(
                self, "_server_frequency_last_polled_at", now, force=force
            ):
                return
            client = getattr(self, "server_api_client", None)
            worker = getattr(self, "_worker", None)
            config = panel.get_config() if panel is not None and hasattr(panel, "get_config") else None
            if client is None or worker is None or config is None or not getattr(client, "is_authenticated", False):
                return
            self._server_frequency_poll_in_progress = True

            def load_frequency() -> dict[str, object]:
                try:
                    return client.frequency_analysis(
                        site,
                        history_count=config.ai_history_count,
                        confidence_threshold=config.ai_confidence_threshold,
                        target_period=target_period or str(
                            getattr(getattr(self, "_draw_infos", {}).get(site), "next_period", "") or ""
                        ),
                    )
                except Exception as exc:
                    return {"error": exc}

            try:
                future = worker.submit(load_frequency)
            except Exception:
                self._server_frequency_poll_in_progress = False
                logger.debug("Unable to submit server frequency analysis poll", exc_info=True)
                return

            def forward_result(done_future) -> None:
                try:
                    payload = done_future.result()
                except Exception as exc:
                    payload = {"error": exc}
                signal = getattr(self, "_server_frequency_ready", None)
                if signal is not None and hasattr(signal, "emit"):
                    signal.emit(payload)
                else:
                    self._handle_server_frequency_ready(payload)

            future.add_done_callback(forward_result)
            return
        service = getattr(self, "auto_bet_service", None)
        if (
            service is None
            or getattr(service, "_result_provider", None) is None
            or not hasattr(service, "refresh_frequency_analysis")
            or panel is None
            or not hasattr(panel, "update_frequency_analysis")
        ):
            return
        if not MainWindowDataMixin._auto_bet_refresh_due(
            self, "_local_frequency_last_polled_at", now, force=force
        ):
            return
        analysis = service.refresh_frequency_analysis(site, target_period=target_period)
        signature = MainWindowDataMixin._stable_payload_signature(self, analysis)
        if signature == getattr(self, "_local_frequency_snapshot_signature", ""):
            return
        self._local_frequency_snapshot_signature = signature
        panel.update_frequency_analysis(analysis)

    def _update_local_runtime_and_ai_statistics(self) -> None:
        service = getattr(self, "auto_bet_service", None)
        panel = getattr(self, "auto_bet_panel", None)
        if service is None or panel is None:
            return
        if hasattr(panel, "update_runtime_state"):
            runtime_state = service.runtime_state
            runtime_signature = MainWindowDataMixin._stable_payload_signature(self, runtime_state)
            if runtime_signature != getattr(self, "_local_runtime_snapshot_signature", ""):
                self._local_runtime_snapshot_signature = runtime_signature
                panel.update_runtime_state(runtime_state)
        if hasattr(panel, "update_ai_statistics"):
            store = getattr(service, "_ai_prediction_store", None)
            if store is not None:
                cfg = service.config
                ai_summary = store.accuracy_summary(cfg.site, cfg.ai_accuracy_window)
                ai_signature = MainWindowDataMixin._stable_payload_signature(self, ai_summary)
                if ai_signature != getattr(self, "_local_ai_snapshot_signature", ""):
                    self._local_ai_snapshot_signature = ai_signature
                    panel.update_ai_statistics(ai_summary)

    def _on_auto_bet_tick(self, now: datetime | None = None) -> None:
        """Refresh the mandatory server-owned automatic betting runtime."""
        client = getattr(self, "server_api_client", None)
        if client is not None and not getattr(client, "is_authenticated", False) and hasattr(self, "_bootstrap_server_mode"):
            self._bootstrap_server_mode()
        self._refresh_server_pending_bet()
        self._refresh_server_betting_events()
        self._refresh_server_runtime_logs(now=now)
        if hasattr(self, "_refresh_server_statistics"):
            try:
                self._refresh_server_statistics(now=now)
            except TypeError:
                self._refresh_server_statistics()
        if hasattr(self, "_refresh_auto_bet_frequency_analysis"):
            try:
                self._refresh_auto_bet_frequency_analysis(getattr(self, "_active_site", ""), now=now)
            except TypeError:
                self._refresh_auto_bet_frequency_analysis(getattr(self, "_active_site", ""))

    def _handle_auto_bet_log_ready(self, record: object) -> None:
        panel = getattr(self, "auto_bet_panel", None)
        if panel is not None and hasattr(panel, "append_log"):
            panel.append_log(record)

    def _refresh_server_runtime_logs(self, now: datetime | None = None, *, load_more: bool = False, force: bool = False) -> None:
        """Load one authenticated, bounded page for the auto-bet runtime log."""
        panel = getattr(self, "auto_bet_panel", None)
        client = getattr(self, "server_api_client", None)
        worker = getattr(self, "_worker", None)
        if panel is None or client is None or worker is None or not panel.isVisible() or not getattr(client, "is_authenticated", False):
            return
        if getattr(self, "_server_runtime_logs_poll_in_progress", False):
            return
        if not load_more:
            interval = panel.runtime_log_refresh_interval_seconds()
            if not interval:
                return
            current = now or datetime.now()
            last = getattr(self, "_server_runtime_logs_last_polled_at", None)
            if not force and isinstance(last, datetime) and (current - last).total_seconds() < interval:
                return
            self._server_runtime_logs_last_polled_at = current
        before_id = panel.runtime_log_before_id() if load_more else None
        filters = panel.runtime_log_filters()
        self._server_runtime_logs_poll_in_progress = True

        def load_logs() -> dict[str, object]:
            try:
                return client.runtime_logs(before_id=before_id, **filters)
            except Exception as exc:
                return {"error": exc, "load_more": load_more}

        try:
            future = worker.submit(load_logs)
        except Exception:
            self._server_runtime_logs_poll_in_progress = False
            logger.debug("Unable to submit server runtime-log poll", exc_info=True)
            return

        def forward_result(done_future) -> None:
            try:
                payload = done_future.result()
            except Exception as exc:
                payload = {"error": exc, "load_more": load_more}
            if isinstance(payload, dict):
                payload["load_more"] = load_more
            signal = getattr(self, "_server_runtime_logs_ready", None)
            if signal is not None and hasattr(signal, "emit"):
                signal.emit(payload)
            else:
                self._handle_server_runtime_logs_ready(payload)

        future.add_done_callback(forward_result)

    def _handle_server_runtime_logs_ready(self, payload: object) -> None:
        self._server_runtime_logs_poll_in_progress = False
        panel = getattr(self, "auto_bet_panel", None)
        if panel is None or not isinstance(payload, dict):
            return
        if payload.get("error") is not None:
            panel._runtime_log_status_label.setText(f"日志刷新失败：{payload['error']}")
            return
        panel.apply_runtime_log_page(payload, replace=not bool(payload.get("load_more")))

    def _on_runtime_log_filters_changed(self) -> None:
        self._refresh_server_runtime_logs(force=True)

    def _on_runtime_log_load_more_clicked(self) -> None:
        self._refresh_server_runtime_logs(load_more=True)

    def _handle_ai_pending_ready(self, pending: object) -> None:
        panel = getattr(self, "auto_bet_panel", None)
        if panel is not None and hasattr(panel, "show_pending_ai_recommendation"):
            panel.show_pending_ai_recommendation(pending)

    def _reset_server_run_statistics_panels(self) -> None:
        panel = getattr(self, "auto_bet_panel", None)
        if panel is None:
            return
        from app.models.auto_bet import AutoBetRuntimeState

        self._server_frequency_snapshot_signature = ""
        self._server_runtime_snapshot_signature = ""
        self._server_ai_snapshot_signature = ""
        if hasattr(panel, "update_runtime_state"):
            panel.update_runtime_state(AutoBetRuntimeState())
        if hasattr(panel, "update_ai_statistics"):
            panel.update_ai_statistics({})
        if hasattr(panel, "update_frequency_analysis"):
            panel.update_frequency_analysis(None)

    def _reset_local_run_statistics_snapshots(self) -> None:
        self._local_frequency_snapshot_signature = ""
        self._local_runtime_snapshot_signature = ""
        self._local_ai_snapshot_signature = ""
        self._local_frequency_last_polled_at = None
        self._local_statistics_last_polled_at = None

    def _event_created_before_server_run(self, item: dict) -> bool:
        started_at = getattr(self, "_server_run_started_at", None)
        if started_at is None:
            return False
        raw = str(item.get("created_at", "") or "").strip()
        if not raw:
            return False
        try:
            created_at = datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return False
        return created_at < started_at

    def _start_server_auto_bet(self) -> None:
        """Server mode leaves crawling, AI, and WSS sending on the backend."""
        panel = getattr(self, "auto_bet_panel", None)
        if panel is None:
            return
        try:
            config = panel.get_config()
            validation_errors = config.start_validation_errors(require_ai_credentials=False)
            if validation_errors:
                QMessageBox.warning(self, "无法启动自动下注", "\n".join(validation_errors))
                panel.set_running(False)
                return
            # Server API stores StrategyEvent.created_at as naive UTC. Keep this
            # cursor in the same timezone so since/event filtering does not hide
            # valid events on UTC+8 client machines.
            self._server_run_started_at = datetime.utcnow()
            MainWindowDataMixin._arm_auto_bet_refresh_burst(self, self._server_run_started_at)
            MainWindowDataMixin._reset_server_run_statistics_panels(self)
            try:
                try:
                    self._server_event_cursor = int(self.server_api_client.latest_betting_event_id(site=config.site))
                except TypeError:
                    self._server_event_cursor = int(self.server_api_client.latest_betting_event_id())
            except Exception as exc:
                logger.debug("Unable to initialize server betting-event cursor: %s", exc)
            self._schedule_server_strategy_save({
                "enabled": True,
                "site": config.site,
                "target_groups": config.target_groups,
                "history_count": config.ai_history_count,
                "confidence_threshold": config.ai_confidence_threshold,
                "require_confirmation": config.ai_require_confirmation,
                "bet_amount": config.bet_amount,
            })
            panel.set_running(True)
            if hasattr(panel, "append_log"):
                from app.models.auto_bet import InjectRecord

                panel.append_log(InjectRecord(
                    ts=datetime.now(),
                    group_name="",
                    group_id="",
                    play_type="",
                    amount=0,
                    success=True,
                    content="服务端策略已提交，等待本期频率与 AI 决策",
                    site=config.site,
                    period="",
                ))
            self._refresh_server_pending_bet()
            if hasattr(self, "_refresh_server_statistics"):
                self._refresh_server_statistics(force=True)
            if hasattr(self, "_refresh_auto_bet_frequency_analysis"):
                self._refresh_auto_bet_frequency_analysis(config.site, force=True)
            timer = getattr(self, "_auto_bet_timer", None)
            if timer is not None:
                timer.start()
        except Exception as exc:
            logger.warning("Unable to start server auto-bet: %s", exc)
            panel.set_running(False)

    def _refresh_server_pending_bet(self) -> None:
        panel = getattr(self, "auto_bet_panel", None)
        if panel is None or getattr(self, "_server_pending_poll_in_progress", False):
            return
        client = getattr(self, "server_api_client", None)
        if client is None or not getattr(client, "is_authenticated", False):
            return
        worker = getattr(self, "_worker", None)
        if worker is None:
            return
        self._server_pending_poll_in_progress = True

        def load_pending() -> dict[str, object]:
            try:
                return {"items": self.server_api_client.pending_bets()}
            except Exception as exc:
                return {"error": exc}

        try:
            future = worker.submit(load_pending)
        except Exception:
            self._server_pending_poll_in_progress = False
            logger.debug("Unable to submit server pending-bet poll", exc_info=True)
            return

        def forward_result(done_future) -> None:
            try:
                payload = done_future.result()
            except Exception as exc:
                payload = {"error": exc}
            signal = getattr(self, "_server_pending_ready", None)
            if signal is not None and hasattr(signal, "emit"):
                signal.emit(payload)
            else:
                self._handle_server_pending_ready(payload)

        future.add_done_callback(forward_result)

    def _refresh_server_betting_events(self) -> None:
        """Fetch completed server-side evaluations and append them once to the UI log."""
        if getattr(self, "_server_event_poll_in_progress", False):
            return
        client = getattr(self, "server_api_client", None)
        worker = getattr(self, "_worker", None)
        if client is None or worker is None or not getattr(client, "is_authenticated", False):
            return
        self._server_event_poll_in_progress = True
        cursor = max(0, int(getattr(self, "_server_event_cursor", 0) or 0))
        since = getattr(self, "_server_run_started_at", None)

        def load_events() -> dict[str, object]:
            try:
                return {
                    "items": client.betting_events(
                        after_id=cursor,
                        site=getattr(self, "_active_site", "") or None,
                        since=since,
                    )
                }
            except Exception as exc:
                return {"error": exc}

        try:
            future = worker.submit(load_events)
        except Exception:
            self._server_event_poll_in_progress = False
            logger.debug("Unable to submit server betting-event poll", exc_info=True)
            return

        def forward_result(done_future) -> None:
            try:
                payload = done_future.result()
            except Exception as exc:
                payload = {"error": exc}
            signal = getattr(self, "_server_betting_events_ready", None)
            if signal is not None and hasattr(signal, "emit"):
                signal.emit(payload)
            else:
                self._handle_server_betting_events_ready(payload)

        future.add_done_callback(forward_result)

    def _handle_server_frequency_ready(self, payload: object) -> None:
        self._server_frequency_poll_in_progress = False
        if not isinstance(payload, dict) or payload.get("error") is not None:
            if isinstance(payload, dict) and payload.get("error") is not None:
                logger.debug("Unable to refresh server frequency analysis: %s", payload.get("error"))
            return
        panel = getattr(self, "auto_bet_panel", None)
        if panel is not None and hasattr(panel, "update_frequency_analysis"):
            signature = MainWindowDataMixin._stable_payload_signature(self, payload)
            if signature == getattr(self, "_server_frequency_snapshot_signature", ""):
                return
            self._server_frequency_snapshot_signature = signature
            panel.update_frequency_analysis(payload)

    def _refresh_server_statistics(self, now: datetime | None = None, *, force: bool = False) -> None:
        """Fetch server-side runtime/AI statistics and apply them to the auto-bet panel."""
        if getattr(self, "_server_statistics_poll_in_progress", False):
            return
        if not MainWindowDataMixin._auto_bet_refresh_due(self, "_server_statistics_last_polled_at", now, force=force):
            return
        client = getattr(self, "server_api_client", None)
        worker = getattr(self, "_worker", None)
        panel = getattr(self, "auto_bet_panel", None)
        if client is None or worker is None or panel is None or not getattr(client, "is_authenticated", False):
            return
        config = panel.get_config() if hasattr(panel, "get_config") else None
        site = str(getattr(config, "site", getattr(self, "_active_site", "pc28")) or "pc28")
        ai_window = int(getattr(config, "ai_accuracy_window", 20) or 20)
        self._server_statistics_poll_in_progress = True

        def load_statistics() -> dict[str, object]:
            try:
                return client.betting_statistics(site, ai_window=ai_window, since=getattr(self, "_server_run_started_at", None))
            except Exception as exc:
                return {"error": exc}

        try:
            future = worker.submit(load_statistics)
        except Exception:
            self._server_statistics_poll_in_progress = False
            logger.debug("Unable to submit server statistics poll", exc_info=True)
            return

        def forward_result(done_future) -> None:
            try:
                payload = done_future.result()
            except Exception as exc:
                payload = {"error": exc}
            signal = getattr(self, "_server_statistics_ready", None)
            if signal is not None and hasattr(signal, "emit"):
                signal.emit(payload)
            else:
                self._handle_server_statistics_ready(payload)

        future.add_done_callback(forward_result)

    def _handle_server_statistics_ready(self, payload: object) -> None:
        self._server_statistics_poll_in_progress = False
        if not isinstance(payload, dict) or payload.get("error") is not None:
            if isinstance(payload, dict) and payload.get("error") is not None:
                logger.debug("Unable to refresh server statistics: %s", payload.get("error"))
            return
        panel = getattr(self, "auto_bet_panel", None)
        if panel is None:
            return
        runtime_payload = payload.get("runtime_state")
        if isinstance(runtime_payload, dict) and hasattr(panel, "update_runtime_state"):
            from app.models.auto_bet import AutoBetRuntimeState

            runtime_signature = MainWindowDataMixin._stable_payload_signature(self, runtime_payload)
            if runtime_signature == getattr(self, "_server_runtime_snapshot_signature", ""):
                runtime_payload = None
            else:
                self._server_runtime_snapshot_signature = runtime_signature
        if isinstance(runtime_payload, dict) and hasattr(panel, "update_runtime_state"):
            allowed = AutoBetRuntimeState.__dataclass_fields__.keys()
            state_args = {key: runtime_payload.get(key) for key in allowed if key in runtime_payload}
            panel.update_runtime_state(AutoBetRuntimeState(**state_args))
        ai_summary = payload.get("ai_statistics")
        if isinstance(ai_summary, dict) and hasattr(panel, "update_ai_statistics"):
            ai_signature = MainWindowDataMixin._stable_payload_signature(self, ai_summary)
            if ai_signature == getattr(self, "_server_ai_snapshot_signature", ""):
                return
            self._server_ai_snapshot_signature = ai_signature
            panel.update_ai_statistics(ai_summary)

    def _server_event_is_stale_for_current_site(self, site: str, period: str) -> bool:
        """Hide backfilled strategy events that are clearly older than the active draw context."""
        if not site or not period:
            return False
        draw_infos = getattr(self, "_draw_infos", {})
        info = draw_infos.get(site) if isinstance(draw_infos, dict) else None
        if str(getattr(info, "source", "") or "").strip().lower() == "inferred":
            return False
        current_period = str(getattr(info, "next_period", "") or "").strip()
        if not current_period or not current_period.isdigit() or not period.isdigit():
            return False
        try:
            return int(period) < int(current_period)
        except ValueError:
            return False

    def _handle_server_betting_events_ready(self, payload: object) -> None:
        self._server_event_poll_in_progress = False
        if not isinstance(payload, dict) or payload.get("error") is not None:
            return
        panel = getattr(self, "auto_bet_panel", None)
        if panel is None or not hasattr(panel, "append_log"):
            return
        from app.models.auto_bet import InjectRecord

        cursor = max(0, int(getattr(self, "_server_event_cursor", 0) or 0))
        activity_sites: set[str] = set()
        key_activity_types = {
            "frequency_skip",
            "ai_error",
            "ai_skip",
            "ai_execute",
            "confirmed",
            "skipped",
            "sent",
            "failed",
            "expired",
        }
        for item in payload.get("items", []):
            if not isinstance(item, dict):
                continue
            event_id = int(item.get("id", 0) or 0)
            if event_id <= cursor:
                continue
            if isinstance(item, dict) and MainWindowDataMixin._event_created_before_server_run(self, item):
                cursor = event_id
                continue
            event_type = str(item.get("event_type", "") or "")
            site = str(item.get("site", "") or "")
            period = str(item.get("period", "") or "")
            message = str(item.get("message", "") or "服务器策略事件")
            decision_event_types = {"frequency_skip", "ai_error", "ai_skip", "ai_execute"}
            if MainWindowDataMixin._server_event_is_stale_for_current_site(self, site, period):
                cursor = event_id
                continue
            event_key = (site, period, event_type, message)
            seen_keys = getattr(self, "_server_event_seen_keys", None)
            if seen_keys is None:
                seen_keys = set()
                self._server_event_seen_keys = seen_keys
            if event_type in decision_event_types and event_key in seen_keys:
                cursor = event_id
                continue
            if event_type in decision_event_types:
                seen_keys.add(event_key)
                if len(seen_keys) > 1000:
                    self._server_event_seen_keys = set(list(seen_keys)[-500:])
            # Server-mode event rows are already persisted as runtime logs. Keep
            # this legacy append path only for non-server callers to avoid two
            # render paths showing the same operational event.
            if not bool(getattr(getattr(self, "server_mode_settings", None), "enabled", False)):
                panel.append_log(InjectRecord(
                    ts=datetime.now(),
                    group_name="",
                    group_id="",
                    play_type="",
                    amount=0,
                    success=event_type not in {"ai_error"},
                    content=message,
                    error="",
                    site=site,
                    period=period,
                ))
            if event_type in key_activity_types:
                activity_sites.add(site)
            cursor = event_id
        self._server_event_cursor = cursor
        if activity_sites:
            MainWindowDataMixin._arm_auto_bet_refresh_burst(self)
            if hasattr(self, "_refresh_server_runtime_logs"):
                self._refresh_server_runtime_logs(force=True)
            if hasattr(self, "_refresh_server_statistics"):
                self._refresh_server_statistics(force=True)
            if hasattr(self, "_refresh_auto_bet_frequency_analysis"):
                for site in sorted(activity_sites):
                    self._refresh_auto_bet_frequency_analysis(site, force=True)

    def _handle_server_pending_ready(self, payload: object) -> None:
        self._server_pending_poll_in_progress = False
        panel = getattr(self, "auto_bet_panel", None)
        if panel is None or not isinstance(payload, dict):
            return
        error = payload.get("error")
        if error is not None:
            logger.debug("Unable to refresh server pending bets: %s", error)
            return
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            panel.show_pending_server_bet(None)
            return
        item = items[0]
        from app.models.auto_bet import PendingAiBet

        panel.show_pending_server_bet(PendingAiBet(
            site=str(item.get("site", "")), period=str(item.get("period", "")),
            play_type=str(item.get("play_type", "")), amount=float(item.get("amount", 0)),
            reason="等待服务器确认下注", created_at=datetime.now(),
        ), order_id=int(item["id"]))

    def _schedule_server_strategy_save(self, payload: dict[str, object]) -> None:
        """Coalesce UI configuration bursts into background API writes."""
        enriched = dict(payload)
        target_groups = [str(group_id) for group_id in enriched.get("target_groups", [])]
        panel = getattr(self, "auto_bet_panel", None)
        names = getattr(panel, "_group_names", {}) if panel is not None else {}
        if isinstance(names, dict):
            enriched["target_group_names"] = {
                group_id: str(names.get(group_id, group_id)).strip() or group_id
                for group_id in target_groups
            }
        self._server_strategy_pending_payload = enriched
        if getattr(self, "_server_strategy_save_in_progress", False):
            return
        timer = getattr(self, "_server_strategy_timer", None)
        if timer is not None:
            timer.cancel()
        delay = max(0.0, float(getattr(self, "server_strategy_debounce_seconds", 0.4)))
        timer = threading.Timer(delay, lambda: MainWindowDataMixin._submit_pending_server_strategy_save(self))
        timer.daemon = True
        self._server_strategy_timer = timer
        timer.start()

    def _submit_pending_server_strategy_save(self) -> None:
        self._server_strategy_timer = None
        if getattr(self, "_server_strategy_save_in_progress", False):
            return
        if not getattr(self, "_server_strategy_pending_payload", None):
            return
        worker = getattr(self, "_worker", None)
        if worker is None:
            return
        self._server_strategy_save_in_progress = True

        def save_latest() -> dict[str, object]:
            request_payload = dict(getattr(self, "_server_strategy_pending_payload", {}) or {})
            self._server_strategy_pending_payload = None
            try:
                self.server_api_client.save_strategy(request_payload)
                return {"ok": True, "payload": request_payload}
            except Exception as exc:
                return {"error": exc, "payload": request_payload}

        try:
            future = worker.submit(save_latest)
        except Exception:
            self._server_strategy_save_in_progress = False
            logger.debug("Unable to submit server strategy save", exc_info=True)
            return

        def forward_result(done_future) -> None:
            try:
                result = done_future.result()
            except Exception as exc:
                result = {"error": exc}
            signal = getattr(self, "_server_strategy_save_ready", None)
            if signal is not None and hasattr(signal, "emit"):
                signal.emit(result)
            else:
                self._handle_server_strategy_save_ready(result)

        future.add_done_callback(forward_result)

    def _handle_server_strategy_save_ready(self, result: object) -> None:
        self._server_strategy_save_in_progress = False
        error = result.get("error") if isinstance(result, dict) else None
        if error is not None:
            logger.warning("Unable to save server auto-bet strategy: %s", error)
        payload = result.get("payload") if isinstance(result, dict) else None
        completed_stop = isinstance(payload, dict) and payload.get("enabled") is False
        if completed_stop and getattr(self, "_server_strategy_stop_pending", False):
            self._server_strategy_stop_pending = False
            if error is not None:
                panel = getattr(self, "auto_bet_panel", None)
                if panel is not None:
                    panel.set_running(True)
                timer = getattr(self, "_auto_bet_timer", None)
                if timer is not None:
                    timer.start()
        if getattr(self, "_server_strategy_pending_payload", None):
            MainWindowDataMixin._schedule_server_strategy_save(self, self._server_strategy_pending_payload)

    def _confirm_server_pending_bet(self) -> None:
        MainWindowDataMixin._submit_server_order_action(self, "confirm_bet")

    def _skip_server_pending_bet(self) -> None:
        MainWindowDataMixin._submit_server_order_action(self, "skip_bet")

    def _submit_server_order_action(self, action: str) -> None:
        panel = getattr(self, "auto_bet_panel", None)
        bet_id = getattr(panel, "server_pending_bet_id", None) if panel is not None else None
        if not bet_id or getattr(self, "_server_order_action_in_progress", False):
            return
        worker = getattr(self, "_worker", None)
        if worker is None:
            return
        self._server_order_action_in_progress = True

        def run_action() -> dict[str, object]:
            try:
                getattr(self.server_api_client, action)(bet_id)
                return {"ok": True, "action": action}
            except Exception as exc:
                return {"error": exc, "action": action}

        try:
            future = worker.submit(run_action)
        except Exception:
            self._server_order_action_in_progress = False
            logger.debug("Unable to submit server order action", exc_info=True)
            return

        def forward_result(done_future) -> None:
            try:
                result = done_future.result()
            except Exception as exc:
                result = {"error": exc, "action": action}
            signal = getattr(self, "_server_order_action_ready", None)
            if signal is not None and hasattr(signal, "emit"):
                signal.emit(result)
            else:
                MainWindowDataMixin._handle_server_order_action_ready(self, result)

        future.add_done_callback(forward_result)

    def _handle_server_order_action_ready(self, result: object) -> None:
        self._server_order_action_in_progress = False
        if isinstance(result, dict) and result.get("error") is not None:
            logger.warning("Unable to perform server order action: %s", result["error"])
            return
        MainWindowDataMixin._refresh_server_pending_bet(self)

    def _on_confirm_ai_bet(self) -> None:
        if getattr(self, "server_mode_settings", None) and self.server_mode_settings.enabled:
            self._confirm_server_pending_bet()
            return
        service = getattr(self, "auto_bet_service", None)
        panel = getattr(self, "auto_bet_panel", None)
        if service is None or panel is None:
            return
        pending_key = getattr(panel, "pending_ai_key", None)
        if not pending_key:
            return
        site, period = pending_key
        info = getattr(self, "_draw_infos", {}).get(site)
        countdown = int(getattr(info, "next_countdown", 0) or 0)
        cfg = service.config
        within_window = service._within_bet_window(
            countdown,
            cfg.lock_threshold_sec,
            period_start_time=getattr(info, "start_time", None),
            period_end_time=getattr(info, "next_time", None),
        )
        service.confirm_ai_bet(site, period, within_bet_window=within_window)
        panel.update_runtime_state(service.runtime_state)

    def _on_skip_ai_bet(self) -> None:
        if getattr(self, "server_mode_settings", None) and self.server_mode_settings.enabled:
            self._skip_server_pending_bet()
            return
        service = getattr(self, "auto_bet_service", None)
        panel = getattr(self, "auto_bet_panel", None)
        if service is None or panel is None:
            return
        pending_key = getattr(panel, "pending_ai_key", None)
        if pending_key:
            service.skip_ai_bet(*pending_key)

    def _on_show_ai_history(self) -> None:
        panel = getattr(self, "auto_bet_panel", None)
        if panel is None or not hasattr(panel, "show_ai_history"):
            return
        if getattr(self, "server_mode_settings", None) and self.server_mode_settings.enabled:
            client = getattr(self, "server_api_client", None)
            worker = getattr(self, "_worker", None)
            config = panel.get_config() if hasattr(panel, "get_config") else None
            if client is None or worker is None or config is None or not getattr(client, "is_authenticated", False):
                return

            def load_history() -> list[dict]:
                return client.ai_prediction_history(config.site, limit=100)

            try:
                future = worker.submit(load_history)
            except Exception:
                logger.debug("Unable to submit server AI history request", exc_info=True)
                return

            def forward_result(done_future) -> None:
                try:
                    records = done_future.result()
                except Exception as exc:
                    records = {"error": exc}
                signal = getattr(self, "_server_ai_history_ready", None)
                if signal is not None and hasattr(signal, "emit"):
                    signal.emit(records)
                else:
                    MainWindowDataMixin._handle_server_ai_history_ready(self, records)

            future.add_done_callback(forward_result)
            return
        service = getattr(self, "auto_bet_service", None)
        store = getattr(service, "_ai_prediction_store", None) if service is not None else None
        if store is None:
            return
        cfg = service.config
        panel.show_ai_history(store.recent_records(cfg.site, 100))

    def _handle_server_ai_history_ready(self, records: object) -> None:
        if isinstance(records, dict) and records.get("error") is not None:
            logger.debug("Unable to load server AI history: %s", records["error"])
            return
        panel = getattr(self, "auto_bet_panel", None)
        if panel is not None and hasattr(panel, "show_ai_history") and isinstance(records, list):
            panel.show_ai_history(records)

    def _on_auto_bet_config_changed(self, config: object) -> None:
        """Save auto bet config to settings."""
        service = getattr(self, "auto_bet_service", None)
        if service is None:
            return
        from app.models.auto_bet import StrategyConfig
        if isinstance(config, StrategyConfig):
            service.apply_config(config)
            self.settings["auto_bet"] = config.to_dict()
            self.settings_service.save(self.settings)
            if getattr(self, "server_mode_settings", None) and self.server_mode_settings.enabled:
                self._schedule_server_strategy_save({
                        "enabled": config.enabled,
                        "site": config.site,
                        "target_groups": config.target_groups,
                        "history_count": config.ai_history_count,
                        "confidence_threshold": config.ai_confidence_threshold,
                        "require_confirmation": config.ai_require_confirmation,
                        "bet_amount": config.bet_amount,
                    })

    def _on_auto_bet_start(self) -> None:
        """Submit automatic betting to the mandatory server runtime."""
        self._start_server_auto_bet()

    def _on_auto_bet_stop(self) -> None:
        """Stop client polling for the server-owned automatic betting runtime."""
        panel = getattr(self, "auto_bet_panel", None)
        if panel is not None:
            config = panel.get_config()
            self._server_strategy_stop_pending = True
            self._schedule_server_strategy_save({
                "enabled": False,
                "site": config.site,
                "target_groups": config.target_groups,
                "history_count": config.ai_history_count,
                "confidence_threshold": config.ai_confidence_threshold,
                "require_confirmation": config.ai_require_confirmation,
                "bet_amount": config.bet_amount,
            })
            panel.set_running(False)
        timer = getattr(self, "_auto_bet_timer", None)
        if timer is not None:
            timer.stop()

    def _on_auto_bet_risk_halted(self, reason: str) -> None:
        """Stop scheduler and sender after a configured risk boundary is reached."""
        service = getattr(self, "auto_bet_service", None)
        if service is None or not service.is_running:
            return
        service.stop()
        injector = getattr(service, "_injector", None)
        if injector is not None:
            try:
                injector.shutdown()
            except Exception as exc:
                logger.debug("Risk-limit injector shutdown error: %s", exc)
            service.set_injector(None)
        timer = getattr(self, "_auto_bet_timer", None)
        if timer is not None:
            timer.stop()
        panel = getattr(self, "auto_bet_panel", None)
        if panel is not None:
            if hasattr(panel, "set_running"):
                panel.set_running(False)
            if hasattr(panel, "append_log"):
                from app.models.auto_bet import InjectRecord
                from datetime import datetime

                panel.append_log(InjectRecord(
                    ts=datetime.now(), group_name="", play_type="", amount=0,
                    content=reason, success=True,
                ))

    def _connect_auto_bet_panel(self) -> None:
        """Wire auto bet panel signals and load saved config.
        Called after panel is created in layout and DB is resolved."""
        panel = getattr(self, "auto_bet_panel", None)
        if panel is None:
            return
        if getattr(self, "_auto_bet_panel_connected", False):
            return
        self._auto_bet_panel_connected = True
        panel.set_server_mode(bool(
            getattr(self, "server_mode_settings", None) and self.server_mode_settings.enabled
        ))

        # Wire signals
        panel.config_changed.connect(self._on_auto_bet_config_changed)
        panel.start_clicked.connect(self._on_auto_bet_start)
        panel.stop_clicked.connect(self._on_auto_bet_stop)
        panel.ai_confirm_clicked.connect(self._on_confirm_ai_bet)
        panel.ai_skip_clicked.connect(self._on_skip_ai_bet)
        panel.ai_history_clicked.connect(self._on_show_ai_history)
        panel.runtime_log_filters_changed.connect(self._on_runtime_log_filters_changed)
        panel.runtime_log_load_more_clicked.connect(self._on_runtime_log_load_more_clicked)
        self.auto_bet_service.set_log_callback(self._auto_bet_log_ready.emit)
        self.auto_bet_service.set_ai_pending_callback(self._ai_pending_ready.emit)

        # Populate groups
        self._refresh_auto_bet_groups()

        # Load saved config after removing credentials from pre-server releases.
        MainWindowDataMixin._remove_local_ai_credentials_from_settings(self)
        saved = self.settings.get("auto_bet", {})
        if saved:
            from app.models.auto_bet import StrategyConfig
            cfg = StrategyConfig.from_dict(saved)
            panel.load_config(cfg)
            self.auto_bet_service.apply_config(cfg)

        active_site = str(getattr(self, "_active_site", "") or "").strip()
        if active_site and hasattr(panel, "set_active_site"):
            panel.set_active_site(active_site)

        # Show panel now that DB is resolved
        panel.setVisible(True)

    def _remove_local_ai_credentials_from_settings(self) -> bool:
        settings = getattr(self, "settings", None)
        if not isinstance(settings, dict):
            return False
        saved = settings.get("auto_bet")
        if not isinstance(saved, dict):
            return False
        obsolete = {"ai_provider", "ai_base_url", "ai_model", "ai_api_key"}
        cleaned = {key: value for key, value in saved.items() if key not in obsolete}
        if len(cleaned) == len(saved):
            return False
        settings["auto_bet"] = cleaned
        self.settings_service.save(settings)
        return True

    def _refresh_auto_bet_groups(self) -> None:
        """Refresh the auto-bet panel's target group list from the current group_list."""
        panel = getattr(self, "auto_bet_panel", None)
        if panel is None:
            return
        groups = []
        if hasattr(self, "group_list"):
            for i in range(self.group_list.count()):
                item = self.group_list.item(i)
                gid = str(item.data(Qt.UserRole) or item.data(32) or "")
                gname = item.text()
                if gname:
                    groups.append((gid or gname, gname))
        panel.set_available_groups(groups)
        config = panel.get_config()
        available_ids = {group_id for group_id, _group_name in groups}
        filtered_ids = [group_id for group_id in config.target_groups if group_id in available_ids]
        service = getattr(self, "auto_bet_service", None)
        service_config = getattr(service, "config", None)
        if filtered_ids != config.target_groups or getattr(service_config, "target_groups", None) != filtered_ids:
            config.target_groups = filtered_ids
            panel.load_config(config)
            self._on_auto_bet_config_changed(config)
        if service is not None and hasattr(service, "set_group_names"):
            service.set_group_names({group_id: group_name for group_id, group_name in groups})
        if (
            groups
            and getattr(getattr(self, "server_mode_settings", None), "enabled", False)
            and hasattr(self, "_schedule_server_strategy_save")
        ):
            self._schedule_server_strategy_save({
                "enabled": config.enabled,
                "site": config.site,
                "target_groups": config.target_groups,
                "history_count": config.ai_history_count,
                "confidence_threshold": config.ai_confidence_threshold,
                "require_confirmation": config.ai_require_confirmation,
                "bet_amount": config.bet_amount,
            })
