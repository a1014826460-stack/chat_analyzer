from __future__ import annotations

import logging
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
        logger.info("Resolve database requested username=%s silent=%s", username, silent)
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
        self.resolved_path_edit.setText(str(resolved.msg_db))
        self.db_status_label.setText(f"已定位 {resolved.account_name} -> {resolved.msg_db}")
        self.status_label.setText("数据库已定位，可以加载消息。")
        self.fallback_box.setVisible(False)
        self._remember_username(username)
        self._load_groups_from_current_source()
        self._save_settings()
        logger.info("Resolve database succeeded username=%s path=%s", username, resolved.msg_db)

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
        logger.info("Loaded %d groups from %s", len(groups), source_path)

    def _pick_manual_data_source(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择数据源",
            self.manual_db_edit.text().strip(),
            "数据文件 (*.db *.sqlite *.txt);;所有文件 (*.*)",
        )
        if file_path:
            self.manual_db_edit.setText(file_path)
            logger.info("Manual data source picked: %s", file_path)

    def _load_manual_data_source(self) -> None:
        source_path = Path(self.manual_db_edit.text().strip()).expanduser()
        logger.info("Load manual data source requested path=%s", source_path)
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
        logger.info(
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
        logger.info("Load messages applied count=%d", len(self.current_messages))

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
        logger.info("Submit message load seq=%s source=%s site=%s", load_seq, source_path, self._active_site)
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
            logger.info(
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

    def _on_auto_bet_tick(self) -> None:
        """Called by auto_bet timer to evaluate betting strategy."""
        service = getattr(self, "auto_bet_service", None)
        if service is None or not service.is_running:
            return
        active_site = getattr(self, "_active_site", "")
        draw_infos = getattr(self, "_draw_infos", {})
        info = draw_infos.get(active_site) if isinstance(draw_infos, dict) else None
        if info is None:
            return
        current_period = info.current_period or ""
        countdown = info.next_countdown or 0
        service.tick(
            active_site,
            countdown,
            current_period,
            period_start_time=getattr(info, "start_time", None),
            period_end_time=getattr(info, "next_time", None),
        )
        if service.runtime_state.halted:
            self._on_auto_bet_risk_halted(service.runtime_state.halt_reason)
        panel = getattr(self, "auto_bet_panel", None)
        if panel is not None and hasattr(panel, "update_runtime_state"):
            panel.update_runtime_state(service.runtime_state)
        if panel is not None and hasattr(panel, "update_ai_statistics"):
            store = getattr(service, "_ai_prediction_store", None)
            if store is not None:
                cfg = service.config
                panel.update_ai_statistics(
                    store.accuracy_summary(cfg.site, cfg.ai_accuracy_window)
                )

    def _handle_auto_bet_log_ready(self, record: object) -> None:
        panel = getattr(self, "auto_bet_panel", None)
        if panel is not None and hasattr(panel, "append_log"):
            panel.append_log(record)

    def _handle_ai_pending_ready(self, pending: object) -> None:
        panel = getattr(self, "auto_bet_panel", None)
        if panel is not None and hasattr(panel, "show_pending_ai_recommendation"):
            panel.show_pending_ai_recommendation(pending)

    def _on_confirm_ai_bet(self) -> None:
        service = getattr(self, "auto_bet_service", None)
        panel = getattr(self, "auto_bet_panel", None)
        if service is None or panel is None:
            return
        pending_key = getattr(panel, "pending_ai_key", None)
        if not pending_key:
            return
        site, period = pending_key
        if getattr(panel, "prefer_ai_for_pending_conflict", False):
            config = service.config
            if not config.ai_prefer_recommendation_on_conflict:
                config.ai_prefer_recommendation_on_conflict = True
                self._on_auto_bet_config_changed(config)
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
        service = getattr(self, "auto_bet_service", None)
        panel = getattr(self, "auto_bet_panel", None)
        if service is None or panel is None:
            return
        pending_key = getattr(panel, "pending_ai_key", None)
        if pending_key:
            service.skip_ai_bet(*pending_key)

    def _on_show_ai_history(self) -> None:
        service = getattr(self, "auto_bet_service", None)
        panel = getattr(self, "auto_bet_panel", None)
        store = getattr(service, "_ai_prediction_store", None) if service is not None else None
        if panel is None or store is None or not hasattr(panel, "show_ai_history"):
            return
        cfg = service.config
        panel.show_ai_history(store.recent_records(cfg.site, 100))

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

    def _on_auto_bet_start(self) -> None:
        """Start the auto bet engine."""
        service = getattr(self, "auto_bet_service", None)
        if service is None:
            return
        missing_ai_fields = service.config.missing_ai_fields()
        if missing_ai_fields:
            panel = getattr(self, "auto_bet_panel", None)
            if panel is not None:
                panel.set_running(False)
            QMessageBox.information(self, "需要 AI 配置", f"请先填写：{'、'.join(missing_ai_fields)}。")
            return
        resolved_db = getattr(self, "resolved_db", None)
        if resolved_db is None:
            panel = getattr(self, "auto_bet_panel", None)
            if panel is not None:
                panel.set_running(False)
            return

        # Prefer the browser/WebSDK WSS protocol: it uses a separate WebSocket
        # instance and does not call the native IM SDK login, so it avoids kicking the
        # running WuQuan client offline. Fall back to UIA/background window
        # senders if WSS credentials are missing or WSS startup fails.
        from app.services.account_resolver import DEFAULT_SHARED_PREFS
        from app.services.background_window_sender import BackgroundWindowMessageSender
        from app.services.uia_wuquan_sender import UiaWuQuanMessageSender
        from app.services.ws_message_sender import WsMessageSender
        from app.services.wuquan_account_mapping import load_shared_preferences, resolve_login_account

        panel = getattr(self, "auto_bet_panel", None)
        injector = None

        try:
            prefs_payload = load_shared_preferences(DEFAULT_SHARED_PREFS)
            account = resolve_login_account(resolved_db.accid, prefs_payload)
        except Exception as exc:
            logger.warning("Web WSS credential lookup failed: %s", exc)
            account = None

        if account is not None and account.user_sig:
            try:
                injector = WsMessageSender(
                    resolved_db.im_appid or account.im_appid,
                    account.accid,
                    account.user_sig,
                    nick=account.nick_name,
                    avatar=account.avatar,
                )
                if not injector.startup():
                    logger.warning("WsMessageSender startup failed; fallback to UIA/background sender")
                    injector = None
            except (RuntimeError, OSError) as exc:
                logger.error("WsMessageSender init/startup failed: %s", exc)
                injector = None
        else:
            logger.warning("Web WSS credentials not found for accid=%s; fallback to UIA/background sender", resolved_db.accid)

        if injector is None:
            try:
                injector = UiaWuQuanMessageSender(msg_db_path=resolved_db.msg_db)
            except (RuntimeError, OSError) as exc:
                logger.error("UiaWuQuanMessageSender init failed: %s", exc)
                if panel is not None:
                    panel.set_running(False)
                return

            if not injector.startup():
                logger.warning("UiaWuQuanMessageSender startup failed; fallback to BackgroundWindowMessageSender")
                try:
                    injector = BackgroundWindowMessageSender(msg_db_path=resolved_db.msg_db)
                except (RuntimeError, OSError) as exc:
                    logger.error("BackgroundWindowMessageSender init failed: %s", exc)
                    if panel is not None:
                        panel.set_running(False)
                    return
                if not injector.startup():
                    logger.error("BackgroundWindowMessageSender startup failed")
                    if panel is not None:
                        panel.set_running(False)
                    return

        service.set_injector(injector)
        svc_cfg = service.config
        if svc_cfg.strategy_type in {"flat", "martingale", "trend_following", "ai"}:
            from app.services.ai_bet_client import AiBetClient

            if hasattr(service, "set_ai_client"):
                service.set_ai_client(AiBetClient())
        elif hasattr(service, "set_ai_client"):
            service.set_ai_client(None)

        from app.services.draw_result_store import DrawResultStore
        from app.services.ai_prediction_store import AiPredictionStore
        from app.services.history_fetchers import HistoryFetcher
        from app.utils.pathing import user_data_dir

        store = DrawResultStore(
            db_path=Path(user_data_dir()) / "draw_results.db",
            fetcher=HistoryFetcher(),
        )
        history_count = svc_cfg.ai_history_count
        store.ensure_data(svc_cfg.site, min_count=history_count)
        service.set_result_provider(store)
        if hasattr(service, "set_ai_prediction_store"):
            prediction_store = AiPredictionStore(Path(user_data_dir()) / "ai_predictions.db")
            service.set_ai_prediction_store(prediction_store)

        service.start()
        panel = getattr(self, "auto_bet_panel", None)
        if panel is not None and hasattr(panel, "update_runtime_state"):
            panel.update_runtime_state(service.runtime_state)
        if panel is not None and hasattr(panel, "update_ai_statistics"):
            prediction_store = getattr(service, "_ai_prediction_store", None)
            if prediction_store is not None:
                panel.update_ai_statistics(
                    prediction_store.accuracy_summary(svc_cfg.site, svc_cfg.ai_accuracy_window)
                )
        timer = getattr(self, "_auto_bet_timer", None)
        if timer is not None:
            timer.start()

    def _on_auto_bet_stop(self) -> None:
        """Stop the auto bet engine."""
        service = getattr(self, "auto_bet_service", None)
        if service is not None:
            service.stop()
            # Shutdown injector
            injector = getattr(service, "_injector", None)
            if injector is not None:
                try:
                    injector.shutdown()
                except Exception as exc:
                    logger.debug("Injector shutdown error: %s", exc)
                service.set_injector(None)
            panel = getattr(self, "auto_bet_panel", None)
            if panel is not None and hasattr(panel, "update_runtime_state"):
                panel.update_runtime_state(service.runtime_state)

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

        # Wire signals
        panel.config_changed.connect(self._on_auto_bet_config_changed)
        panel.start_clicked.connect(self._on_auto_bet_start)
        panel.stop_clicked.connect(self._on_auto_bet_stop)
        panel.ai_confirm_clicked.connect(self._on_confirm_ai_bet)
        panel.ai_skip_clicked.connect(self._on_skip_ai_bet)
        panel.ai_history_clicked.connect(self._on_show_ai_history)
        self.auto_bet_service.set_log_callback(self._auto_bet_log_ready.emit)
        self.auto_bet_service.set_ai_pending_callback(self._ai_pending_ready.emit)

        # Populate groups
        self._refresh_auto_bet_groups()

        # Load saved config
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
        service = getattr(self, "auto_bet_service", None)
        if service is not None and hasattr(service, "set_group_names"):
            service.set_group_names({group_id: group_name for group_id, group_name in groups})
