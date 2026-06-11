from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtWidgets import QFileDialog, QListWidgetItem, QMessageBox

from app.models import ParseOptions
from app.services.account_resolver import ResolvedDatabase
from app.utils.fetch_date import _SITE_INTERVAL_SEC


logger = logging.getLogger(__name__)


class MainWindowDataMixin:
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
        if hasattr(self, "period_input"):
            self.period_input.setText(self._query_period_override if self._manual_period_override else "")
        now = QDateTime.currentDateTime()
        if hasattr(self, "end_edit"):
            self.end_edit.setDateTime(now)
        if hasattr(self, "start_edit"):
            self.start_edit.setDateTime(now.addDays(-1))
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
        if hasattr(self, "main_splitter"):
            self.main_splitter.setSizes([420, 980])

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
            diagnostic = self.account_resolver.get_diagnostic()
            self.resolved_db = None
            if hasattr(self, "resolved_path_edit") and hasattr(self.resolved_path_edit, "clear"):
                self.resolved_path_edit.clear()
            if hasattr(self, "group_list") and hasattr(self.group_list, "clear"):
                self.group_list.clear()
            self._refresh_block_rule_group_selector()
            self.db_status_label.setText(diagnostic.format_message() if diagnostic else "未找到数据库。")
            self.status_label.setText("自动定位数据库失败，请手动选择数据源。")
            self.fallback_box.setVisible(True)
            logger.warning("Resolve database failed username=%s", username)
            return
        self.resolved_db = resolved
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
        self.group_list.blockSignals(True)
        self.group_list.clear()
        for group in groups:
            item = QListWidgetItem(group.group_name)
            item.setData(32, group.group_id)
            item.setData(33, group.group_name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.group_list.addItem(item)
        self.group_list.blockSignals(False)
        self._refresh_block_rule_group_selector()
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
        messages = self.chat_service.load_messages_with_cache(source_path, options)
        visual_rows, stats = self.chat_service.analyze_bets(
            messages,
            options.blocked_names,
            options.blocked_user_ids,
            options.period_filter,
            options.site,
            options.period_window_start,
            options.period_window_end,
            options.period_interval_sec,
        )
        new_cursor = self.chat_service.get_cached_cursor(messages)
        return {
            "seq": load_seq,
            "options": options,
            "active_site": active_site,
            "current_messages": messages,
            "current_visual_rows": visual_rows,
            "current_stats": stats,
            "old_cursor": old_cursor_snapshot,
            "new_cursor": new_cursor,
            "short_circuit": False,
            "current_sig": current_sig,
        }

    def _apply_load_result(self, result: dict[str, object]) -> None:
        self.current_messages = list(result.get("current_messages", []))
        self.current_visual_rows = list(result.get("current_visual_rows", []))
        self.current_stats = result.get("current_stats")
        self._last_loaded_signature = result.get("current_sig")
        new_cursor = result.get("new_cursor")
        if self._active_site and new_cursor:
            self._last_message_cursor[self._active_site] = new_cursor
        self.status_label.setText(f"已加载 {len(self.current_messages):,} 条消息。")
        self._refresh_message_view()
        self._update_chart_data()
        self._sync_chart_status()
        logger.info("Load messages applied count=%d", len(self.current_messages))

    def _load_filtered_messages(self) -> None:
        try:
            source_path, options, current_sig, _incremental = self._build_load_options(True)
        except FileNotFoundError:
            QMessageBox.information(self, "没有数据源", "请先自动定位或手动选择数据源。")
            if hasattr(self, "_set_status"):
                self._set_status("没有数据源，请先选择数据源。", "info")
            return
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

    def _update_chart_data(self) -> None:
        if hasattr(self, "chart_window"):
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

        period_filter = self.period_input.text().strip() if hasattr(self, "period_input") else ""
        site = self._active_site or ""
        period_interval_sec = _SITE_INTERVAL_SEC.get(site, 180)
        return ParseOptions(
            username=self.username_combo.currentText().strip(),
            groups=selected_groups,
            blocked_names=self._blocked_names(),
            blocked_names_by_group=self.group_block_rules,
            group_ids=selected_group_ids,
            blocked_user_ids=[],
            period_filter=period_filter,
            site=site,
            period_interval_sec=period_interval_sec,
        )
