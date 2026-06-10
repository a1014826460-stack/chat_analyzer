from __future__ import annotations

import logging
from math import ceil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QFileDialog, QMessageBox

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
        self.settings_service.save(
            {
                "username": self.username_combo.currentText().strip(),
                "recent_usernames": [self.username_combo.itemText(i) for i in range(self.username_combo.count())],
                "db_dir": str(source_path.parent) if source_path else "",
                "data_source": str(source_path) if source_path else "",
                "export_dir": str(self.settings.get("export_dir", "")).strip(),
                "blocked_names": self._blocked_names(),
                "blocked_names_by_group": self.group_block_rules,
                "selected_group_ids": self._selected_group_ids(),
                "selected_block_group_key": self._selected_block_group_key(),
                "fallback_db_path": self.manual_db_edit.text().strip(),
                "lock_threshold_sec": self._lock_threshold_sec,
                "query_period_override": self._query_period_override,
                "manual_period_override": self._manual_period_override,
                "is_first_launch": self._is_first_launch,
                "proxy_enabled": self.settings.get("proxy_enabled", False),
                "proxy_http": self.settings.get("proxy_http", ""),
                "proxy_https": self.settings.get("proxy_https", ""),
            }
        )

    def _show_about(self) -> None:
        QMessageBox.about(self, "About", "StarTrace Chat Analyzer")

    def _open_proxy_settings(self) -> None:
        QMessageBox.information(self, "Proxy", proxy_status_text(self.settings))

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

    def _refresh_message_view(self) -> None:
        filtered = self._filtered_messages_for_view()
        total_pages = max(1, ceil(len(filtered) / self.messages_per_page))
        self.message_page = min(self.message_page, total_pages - 1)
        start = self.message_page * self.messages_per_page
        page_rows = filtered[start : start + self.messages_per_page]
        self.result_view.clear()
        cursor = self.result_view.textCursor()
        for msg in page_rows:
            cursor.insertHtml(self._message_html(msg))
            cursor.insertHtml("<br/><br/>")
        self.result_view.moveCursor(QTextCursor.Start)
        self.page_label.setText(f"Page {self.message_page + 1} / {total_pages}")

    def _filtered_messages_for_view(self) -> list:
        selected_groups = self.chart_window.selected_groups()
        base_messages = self.current_messages or []
        if not selected_groups:
            return base_messages
        return [msg for msg in base_messages if getattr(msg, "group", "") in selected_groups]

    def _prev_page(self) -> None:
        if self.message_page > 0:
            self.message_page -= 1
            self._refresh_message_view()

    def _next_page(self) -> None:
        filtered = self._filtered_messages_for_view()
        total_pages = max(1, ceil(len(filtered) / self.messages_per_page))
        if self.message_page + 1 < total_pages:
            self.message_page += 1
            self._refresh_message_view()

    def _message_html(self, msg) -> str:
        user_id = getattr(msg, "sender_id", "") or self._find_user_id_by_name(getattr(msg, "username", ""))
        user_label = f"{getattr(msg, 'username', '')} {user_id}".strip()
        return (
            f"{self._pill(msg.ts.strftime('%Y-%m-%d %H:%M'), '#d5fbff')}"
            f" | {self._pill(getattr(msg, 'group', ''), '#d8efff')}"
            f" | {self._pill(user_label, '#e3f1ff')}"
            f"<br/>{self._pill(getattr(msg, 'content', ''), '#f4f8ff')}"
        )

    def _pill(self, value: str, bg: str) -> str:
        safe = (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br/>")
        )
        return f"<span style='display:inline-block; margin:0 8px 8px 0; padding:6px 10px; background:{bg}; border-radius:12px;'>{safe}</span>"

    def _find_user_id_by_name(self, username: str) -> str:
        for msg in self.current_messages:
            if getattr(msg, "username", "") == username and getattr(msg, "sender_id", ""):
                return getattr(msg, "sender_id", "")
        return ""

    def _export_messages(self, suffix: str) -> None:
        if not self.current_messages:
            QMessageBox.information(self, "No data", "Load messages first.")
            return
        export_path = self._export_dir_path() / f"filtered_messages{suffix}"
        count = self.chat_service.export_filtered_messages(self.current_messages, export_path)
        self.status_label.setText(f"Exported {count:,} messages to {export_path}")

    def _export_stats_excel(self) -> None:
        if not self.current_stats or not self.current_stats.totals:
            QMessageBox.information(self, "No stats", "Analyze messages first.")
            return
        export_path = self._export_dir_path() / "stats.xlsx"
        self.chat_service.export_stats_excel(self.current_stats, export_path)
        self.status_label.setText(f"Exported Excel: {export_path}")

    def _export_stats_pdf(self) -> None:
        if not self.current_stats or not self.current_stats.totals:
            QMessageBox.information(self, "No stats", "Analyze messages first.")
            return
        export_path = self._export_dir_path() / "stats.pdf"
        self.chat_service.export_stats_pdf(self.current_stats, export_path)
        self.status_label.setText(f"Exported PDF: {export_path}")

    def _pick_export_dir(self) -> None:
        dir_name = QFileDialog.getExistingDirectory(self, "Choose export directory")
        if dir_name:
            self.settings["export_dir"] = dir_name
            self._save_settings()

    def _activate_license(self) -> None:
        ok, message = self.license_service.activate(self.license_input.toPlainText().strip())
        if ok:
            QMessageBox.information(self, "Activation", message)
            self._activate_and_launch()
        else:
            QMessageBox.warning(self, "Activation", message)
        self._refresh_license_banner()
