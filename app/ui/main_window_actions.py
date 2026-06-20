from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from app.ui.raw_chat_dialog import RawChatDialog
from app.ui.summary_check_dialog import SummaryCheckDialog
from app.ui.unresolved_receipt_dialog import UnresolvedReceiptDialog
from app.utils.fetch_date import set_proxy_settings
from app.utils.proxy import proxy_status_text


logger = logging.getLogger(__name__)


class MainWindowActionsMixin:
    def _selected_group_names(self) -> list[str]:
        names: list[str] = []
        for index in range(self.group_list.count()):
            item = self.group_list.item(index)
            if item.checkState() == Qt.Checked:
                names.append(str(item.data(Qt.UserRole + 1) or item.text()))
        return names

    def _selected_group_ids(self) -> list[str]:
        ids: list[str] = []
        for index in range(self.group_list.count()):
            item = self.group_list.item(index)
            if item.checkState() == Qt.Checked:
                ids.append(str(item.data(Qt.UserRole) or ""))
        return ids

    def _selected_group_mode(self) -> str:
        if not hasattr(self, "group_list"):
            return "custom" if self._selected_group_ids() else "none"
        total = self.group_list.count()
        checked = len(self._selected_group_ids())
        if total > 0 and checked == total:
            return "all"
        if checked == 0:
            return "none"
        return "custom"

    def _has_any_group_items(self) -> bool:
        return self.group_list.count() > 0

    def _set_checked_state(self, widget, checked: bool) -> None:
        widget.blockSignals(True)
        for index in range(widget.count()):
            item = widget.item(index)
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            self._sync_check_item_text(item)
        widget.blockSignals(False)
        if widget is self.group_list:
            self._refresh_block_rule_group_selector()
            self._refresh_message_view()
            state_text = "全选" if checked else "清空"
            if hasattr(self, "_set_status"):
                self._set_status(f"群组筛选已{state_text}。", "info")
        self._save_settings()

    def _invert_checked_state(self, widget) -> None:
        widget.blockSignals(True)
        for index in range(widget.count()):
            item = widget.item(index)
            item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
            self._sync_check_item_text(item)
        widget.blockSignals(False)
        if widget is self.group_list:
            self._refresh_block_rule_group_selector()
            self._refresh_message_view()
            if hasattr(self, "_set_status"):
                self._set_status("群组筛选已反选。", "info")
        self._save_settings()

    def _handle_group_item_changed(self, item) -> None:
        self._sync_check_item_text(item)
        self._refresh_block_rule_group_selector()
        self._refresh_message_view()
        self._save_settings()

    def _sync_check_item_text(self, item) -> None:
        text = str(item.data(Qt.UserRole + 1) or item.text())
        prefix = "✓ " if item.checkState() == Qt.Checked else ""
        item.setText(f"{prefix}{text}")

    def _remember_username(self, username: str) -> None:
        names = [self.username_combo.itemText(i) for i in range(self.username_combo.count()) if self.username_combo.itemText(i)]
        if username in names:
            names.remove(username)
        names.insert(0, username)
        names = names[:12]
        self.username_combo.clear()
        self.username_combo.addItems(names)
        self.username_combo.setCurrentText(username)

    def _current_source_path(self) -> Path | None:
        current_raw = self.resolved_path_edit.text().strip()
        if current_raw:
            return Path(current_raw).expanduser()
        if self.resolved_db is not None:
            return self.resolved_db.msg_db
        raw = self.manual_db_edit.text().strip()
        return Path(raw).expanduser() if raw else None

    def _export_dir_path(self) -> Path:
        raw = str(self.settings.get("export_dir", "")).strip()
        path = Path(raw).expanduser() if raw else Path.cwd()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _save_settings(self) -> None:
        source_path = self._current_source_path()
        global_block_names = (
            self._global_block_names()
            if hasattr(self, "_global_block_names")
            else (self._blocked_names() if hasattr(self, "_blocked_names") else [])
        )
        overrides_raw = getattr(self, "_query_period_overrides_by_site", self.settings.get("query_period_overrides_by_site", {}))
        query_period_overrides_by_site = {
            str(key): str(value).strip()
            for key, value in dict(overrides_raw if isinstance(overrides_raw, dict) else {}).items()
            if str(value).strip()
        }
        legacy_period_override = str(getattr(self, "_query_period_override", "")).strip()
        legacy_manual_override = bool(getattr(self, "_manual_period_override", False) and legacy_period_override)
        advanced_time_frame = getattr(self, "advanced_time_frame", None)
        advanced_time_enabled = bool(
            advanced_time_frame is not None
            and hasattr(advanced_time_frame, "isVisible")
            and advanced_time_frame.isVisible()
        )
        advanced_time_start = self._settings_datetime_value("start_edit")
        advanced_time_end = self._settings_datetime_value("end_edit")
        payload = dict(getattr(self, "settings", {}))
        username = self.username_combo.currentText().strip()
        recent_usernames = [self.username_combo.itemText(i) for i in range(self.username_combo.count())]
        if username:
            recent_usernames = [item for item in recent_usernames if item and item != username]
            recent_usernames.insert(0, username)
        recent_usernames = recent_usernames[:12]
        payload.update(
            {
                "username": username,
                "recent_usernames": recent_usernames,
                "db_dir": str(source_path.parent) if source_path else "",
                "data_source": str(source_path) if source_path else "",
                "export_dir": str(payload.get("export_dir", "")).strip(),
                "global_block_names": global_block_names,
                "blocked_names": global_block_names,
                "blocked_names_by_group": self.group_block_rules,
                "group_types_by_id": dict(getattr(self, "group_types_by_id", {}) or {}),
                "group_type_switches_by_id": dict(getattr(self, "group_type_switches_by_id", {}) or {}),
                "group_robot_ids": dict(getattr(self, "group_robot_ids", {}) or {}),
                "selected_group_ids": self._selected_group_ids(),
                "selected_group_mode": self._selected_group_mode(),
                "selected_block_group_key": self._selected_block_group_key(),
                "fallback_db_path": self.manual_db_edit.text().strip(),
                "lock_threshold_sec": self._lock_threshold_sec,
                "query_period_overrides_by_site": query_period_overrides_by_site,
                "query_period_override": "" if query_period_overrides_by_site else legacy_period_override,
                "manual_period_override": False if query_period_overrides_by_site else legacy_manual_override,
                "advanced_time_filter_enabled": advanced_time_enabled,
                "advanced_time_start": advanced_time_start,
                "advanced_time_end": advanced_time_end,
                "is_first_launch": self._is_first_launch,
                "proxy_enabled": payload.get("proxy_enabled", False),
                "proxy_http": payload.get("proxy_http", ""),
                "proxy_https": payload.get("proxy_https", ""),
            }
        )
        self.settings = payload
        self.settings_service.save(payload)

    def _settings_datetime_value(self, attr_name: str) -> str:
        widget = getattr(self, attr_name, None)
        if widget is None or not hasattr(widget, "dateTime"):
            return ""
        value = widget.dateTime().toPython()
        return value.isoformat(timespec="seconds") if hasattr(value, "isoformat") else ""

    def _show_about(self) -> None:
        logger.debug("About dialog opened")
        QMessageBox.about(self, "关于", "StarTrace Chat Analyzer")

    def _open_proxy_settings(self) -> None:
        logger.debug("Proxy settings viewed")
        QMessageBox.information(self, "代理设置", proxy_status_text(self.settings))

    def _apply_proxy_settings(self, enabled: bool, http_proxy: str, https_proxy: str) -> None:
        self.settings["proxy_enabled"] = enabled
        self.settings["proxy_http"] = http_proxy
        self.settings["proxy_https"] = https_proxy
        set_proxy_settings(self.settings)
        self._save_settings()

    def _on_first_launch_complete(self) -> None:
        if not self._is_first_launch:
            return
        self._is_first_launch = False
        self.settings["is_first_launch"] = False
        self._save_settings()

    def _open_chart_window(self) -> None:
        if not self._assert_activated():
            return
        self._load_filtered_messages()

    def _raw_chat_history(self) -> list[object]:
        history = getattr(self, "raw_chat_messages", None)
        if not isinstance(history, list):
            history = []
            self.raw_chat_messages = history
        return history

    def _record_raw_chat_messages(self, messages: list[object]) -> None:
        history_getter = getattr(self, "_raw_chat_history", None)
        if callable(history_getter):
            history = history_getter()
        else:
            history = getattr(self, "raw_chat_messages", None)
            if not isinstance(history, list):
                history = []
                self.raw_chat_messages = history
        seen = {
            (
                getattr(msg, "ts", None),
                getattr(msg, "group", ""),
                getattr(msg, "username", ""),
                getattr(msg, "sender_id", ""),
                getattr(msg, "content", ""),
                getattr(msg, "raw_client_time", 0),
                getattr(msg, "raw_rand", 0),
            )
            for msg in history
        }
        for msg in messages:
            key = (
                getattr(msg, "ts", None),
                getattr(msg, "group", ""),
                getattr(msg, "username", ""),
                getattr(msg, "sender_id", ""),
                getattr(msg, "content", ""),
                getattr(msg, "raw_client_time", 0),
                getattr(msg, "raw_rand", 0),
            )
            if key in seen:
                continue
            seen.add(key)
            history.append(msg)

    def _messages_for_raw_chat_view(self) -> list[object]:
        history_getter = getattr(self, "_raw_chat_history", None)
        if callable(history_getter):
            history = history_getter()
            if history:
                return history
        history = getattr(self, "raw_chat_messages", None)
        if isinstance(history, list) and history:
            return history
        current_messages = getattr(self, "current_messages", [])
        return list(current_messages) if isinstance(current_messages, list) else []

    def _open_raw_chat_dialog(self) -> None:
        dialog = getattr(self, "raw_chat_dialog", None)
        view_getter = getattr(self, "_messages_for_raw_chat_view", None)
        if callable(view_getter):
            messages = view_getter()
        else:
            history = getattr(self, "raw_chat_messages", None)
            messages = list(history) if isinstance(history, list) and history else list(getattr(self, "current_messages", []))
        if dialog is None:
            parent = self if isinstance(self, QWidget) else None
            dialog = RawChatDialog(messages, parent)
            self.raw_chat_dialog = dialog
        else:
            dialog.set_messages(messages)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _summary_check_history(self) -> list[dict[str, object]]:
        history = getattr(self, "summary_check_history", None)
        if not isinstance(history, list):
            history = []
            self.summary_check_history = history
        return history

    def _record_summary_check(self, payload: dict[str, object]) -> None:
        period = str(payload.get("period", "") or "").strip()
        by_play = dict(payload.get("by_play", {}) or {})
        if not period or not by_play:
            return
        group = str(payload.get("group", "") or "").strip()
        history = MainWindowActionsMixin._summary_check_history(self)
        record = {
            "group": group,
            "period": period,
            "software_totals": dict(payload.get("software_totals", {}) or {}),
            "robot_totals": dict(payload.get("robot_totals", {}) or {}),
            "by_play": by_play,
        }
        deduped = [
            item
            for item in history
            if not (
                str(item.get("group", "") or "").strip() == group
                and str(item.get("period", "") or "").strip() == period
            )
        ]
        deduped.insert(0, record)
        kept: list[dict[str, object]] = []
        per_group_counts: dict[str, int] = {}
        for item in deduped:
            item_group = str(item.get("group", "") or "").strip()
            count = per_group_counts.get(item_group, 0)
            if count >= 20:
                continue
            kept.append(item)
            per_group_counts[item_group] = count + 1
        self.summary_check_history = kept

    def _summary_check_payload(self) -> dict[str, object]:
        stats = getattr(self, "current_stats", None)
        if stats is None:
            return {}
        records = getattr(stats, "summary_check_records", None)
        if isinstance(records, list) and records:
            return dict(records[0])
        return {
            "group": self._active_group_name_for_summary_check(),
            "period": getattr(stats, "summary_check_period", "") or "",
            "software_totals": getattr(stats, "totals", {}) or {},
            "robot_totals": getattr(stats, "summary_check_totals", {}) or {},
            "by_play": getattr(stats, "summary_check_by_play", {}) or {},
        }

    def _summary_check_payloads(self) -> list[dict[str, object]]:
        stats = getattr(self, "current_stats", None)
        records = getattr(stats, "summary_check_records", None) if stats is not None else None
        if isinstance(records, list) and records:
            for record in reversed(records):
                if isinstance(record, dict):
                    self._record_summary_check(record)
        else:
            payload = self._summary_check_payload()
            if payload:
                self._record_summary_check(payload)
        return list(self._summary_check_history())

    def _active_group_name_for_summary_check(self) -> str:
        selected_names_getter = getattr(self, "_selected_group_names", None)
        if callable(selected_names_getter):
            selected_names = selected_names_getter()
            if len(selected_names) == 1:
                return str(selected_names[0] or "")
        current_messages = getattr(self, "current_messages", [])
        groups = {
            str(getattr(message, "group", "")).strip()
            for message in current_messages
            if str(getattr(message, "group", "")).strip()
        }
        return next(iter(groups), "") if len(groups) == 1 else ""

    def _open_summary_check_dialog(self) -> None:
        dialog = getattr(self, "summary_check_dialog", None)
        payload_getter = getattr(self, "_summary_check_payloads", None)
        if callable(payload_getter):
            payload = payload_getter()
        else:
            stats = getattr(self, "current_stats", None)
            payload = []
            if stats is not None:
                payload = [
                    {
                        "period": getattr(stats, "summary_check_period", "") or "",
                        "software_totals": getattr(stats, "totals", {}) or {},
                        "robot_totals": getattr(stats, "summary_check_totals", {}) or {},
                        "by_play": getattr(stats, "summary_check_by_play", {}) or {},
                    }
                ]
        if dialog is None:
            parent = self if isinstance(self, QWidget) else None
            dialog = SummaryCheckDialog(payload, parent)
            self.summary_check_dialog = dialog
        else:
            dialog.set_summary_check(payload)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _unresolved_receipt_payload(self) -> list[dict[str, object]]:
        stats = getattr(self, "current_stats", None)
        if stats is None:
            return []
        return [dict(row) for row in getattr(stats, "unresolved_receipts", []) or []]

    def _open_unresolved_receipt_dialog(self) -> None:
        dialog = getattr(self, "unresolved_receipt_dialog", None)
        payload_getter = getattr(self, "_unresolved_receipt_payload", None)
        if callable(payload_getter):
            rows = payload_getter()
        else:
            stats = getattr(self, "current_stats", None)
            rows = [dict(row) for row in getattr(stats, "unresolved_receipts", []) or []] if stats is not None else []
        if dialog is None:
            parent = self if isinstance(self, QWidget) else None
            dialog = UnresolvedReceiptDialog(rows, parent)
            self.unresolved_receipt_dialog = dialog
        else:
            dialog.set_rows(rows)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _refresh_message_view(self) -> None:
        dialog = getattr(self, "raw_chat_dialog", None)
        if dialog is not None and dialog.isVisible():
            view_getter = getattr(self, "_messages_for_raw_chat_view", None)
            if callable(view_getter):
                messages = view_getter()
            else:
                history = getattr(self, "raw_chat_messages", None)
                messages = list(history) if isinstance(history, list) and history else list(getattr(self, "current_messages", []))
            dialog.set_messages(messages)

    def _prev_page(self) -> None:
        dialog = getattr(self, "raw_chat_dialog", None)
        if dialog is not None:
            dialog._prev_page()

    def _next_page(self) -> None:
        dialog = getattr(self, "raw_chat_dialog", None)
        if dialog is not None:
            dialog._next_page()

    def _find_user_id_by_name(self, username: str) -> str:
        for msg in self.current_messages:
            if getattr(msg, "username", "") == username and getattr(msg, "sender_id", ""):
                return getattr(msg, "sender_id", "")
        return ""

    def _export_messages(self, suffix: str) -> None:
        if not self.current_messages:
            QMessageBox.information(self, "没有数据", "请先加载消息。")
            return
        export_path = self._export_dir_path() / f"filtered_messages{suffix}"
        count = self.chat_service.export_filtered_messages(self.current_messages, export_path)
        self.status_label.setText(f"已导出 {count:,} 条消息到 {export_path}")
        logger.info("Exported messages count=%d path=%s", count, export_path)

    def _export_stats_excel(self) -> None:
        if not self.current_stats or not self.current_stats.totals:
            QMessageBox.information(self, "没有统计数据", "请先分析消息。")
            return
        export_path = self._export_dir_path() / "stats.xlsx"
        self.chat_service.export_stats_excel(self.current_stats, export_path)
        self.status_label.setText(f"已导出 Excel: {export_path}")
        logger.info("Exported stats Excel path=%s", export_path)

    def _export_stats_pdf(self) -> None:
        if not self.current_stats or not self.current_stats.totals:
            QMessageBox.information(self, "没有统计数据", "请先分析消息。")
            return
        export_path = self._export_dir_path() / "stats.pdf"
        self.chat_service.export_stats_pdf(self.current_stats, export_path)
        self.status_label.setText(f"已导出 PDF: {export_path}")
        logger.info("Exported stats PDF path=%s", export_path)

    def _pick_export_dir(self) -> None:
        dir_name = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if dir_name:
            self.settings["export_dir"] = dir_name
            self._save_settings()
            if hasattr(self, "_set_status"):
                self._set_status(f"导出目录已设置: {dir_name}", "info")

    def _activate_license(self) -> None:
        ok, message = self.license_service.activate(self.license_input.toPlainText().strip())
        if ok:
            logger.info("License activated")
            QMessageBox.information(self, "激活", message)
            self._activate_and_launch()
        else:
            logger.warning("License activation failed: %s", message)
            QMessageBox.warning(self, "激活", message)
        self._refresh_license_banner()
