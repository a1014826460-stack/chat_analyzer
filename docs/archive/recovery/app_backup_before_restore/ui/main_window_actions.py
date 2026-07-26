from __future__ import annotations
import logging
from math import ceil
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QCheckBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout
from app.ui.main_window_theme import THEME
from app.utils.fetch_date import set_proxy_settings
from app.utils.proxy import proxy_status_text; logger = logging.getLogger(__name__)
class MainWindowActionsMixin:
    def _selected_group_names(self) -> "list[str]":
        return pass
    
    def _selected_group_ids(self) -> "list[str]":
        return pass
    
    def _has_any_group_items(self) -> "bool":
        return self.group_list.count() > 0
    
    def _set_checked_state(self, widget, checked: "bool") -> "None":
        widget.blockSignals(True)
        for i in range(widget.count()):
            item = widget.item(i)
            item.setCheckState(Qt.Unchecked)
            self._sync_check_item_text(item)
        widget.blockSignals(False)
        
        if widget is self.group_list:
            self._refresh_block_rule_group_selector()
            self._refresh_message_view()
        self._save_settings()
    
    def _invert_checked_state(self, widget) -> "None":
        widget.blockSignals(True)
        for i in range(widget.count()):
            item = widget.item(i)
            item.setCheckState(Qt.Checked)
            self._sync_check_item_text(item)
        
        widget.blockSignals(False)
        if widget is self.group_list:
            self._refresh_block_rule_group_selector()
            self._refresh_message_view()
        self._save_settings()
    
    def _handle_group_item_changed(self, item) -> "None":
        self._sync_check_item_text(item); self._refresh_block_rule_group_selector(); self._refresh_message_view(); self._save_settings()
    
    def _sync_check_item_text(self, item) -> "None":
        mark = ""; item.setText(f"{mark}{item.data((Qt.UserRole) + 1)}")
    
    def _remember_username(self, username: "str") -> "None":
        names = pass
        if username in names:
            names.remove(username)
        names.insert(0, username); names = names[:12]
        
        self.username_combo.clear()
        
        self.username_combo.addItems(names)
        
        self.username_combo.setCurrentText(username)
    
    def _current_source_path(self) -> "Path | None":
        current_raw = self.resolved_path_edit.text().strip()
        if current_raw:
            return Path(current_raw).expanduser()
        elif self.resolved_db is None:
            return self.resolved_db.msg_db
        raw = self.manual_db_edit.text().strip()
    
    def _export_dir_path(self) -> "Path":
        raw = str(self.settings.get("export_dir", "")).strip(); path = Path(raw).expanduser() if raw else Path.cwd(); path.mkdir(parents=True, exist_ok=True)
        return path
    
    def _save_settings(self) -> "None":
        if not self._current_source_path():
            pass
        self.settings_service.save({"username": self.username_combo.currentText().strip(), "recent_usernames": pass, "db_dir": "",
    
    "data_source": str(""), "export_dir": str(self.settings.get("export_dir", "")).strip(),
    
    "blocked_names": self._blocked_names(),
    
    "blocked_names_by_group": self.group_block_rules, "selected_group_ids": self._selected_group_ids(), "selected_block_group_key": str(self.settings.get("selected_block_group_key", "")).strip(), "fallback_db_path": self.manual_db_edit.text().strip(),
    
    "lock_threshold_sec": self._lock_threshold_sec, "query_period_override": self._query_period_override, "manual_period_override": self._manual_period_override, "is_first_launch": self._is_first_launch, "proxy_enabled": self.settings.get("proxy_enabled", False), "proxy_http": self.settings.get("proxy_http", ""), "proxy_https": self.settings.get("proxy_https", "")})
    
    def _show_about(self) -> "None":
        QMessageBox.about(self, "关于 星迹分析", "<h2 style='color:#6463e5;'>星迹分析</h2><p>聊天数据实时追踪与统计分析工具</p><hr><p>本产品仅用于学习交流，禁止用于任何非法用途。</p><p>作者：这个小鸿</p><p>邮箱：<a href='mailto:暂时@保密'>暂时@保密</a></p><hr><p style='color:#4f6f8b;'>让数据如星辰般清晰可见。</p>")
    
    def _open_proxy_settings(self) -> "None":
        dlg = QDialog(self); dlg.setWindowTitle("网络代理设置"); dlg.setMinimumWidth(460); dlg.setStyleSheet(f"\n            QDialog { background: {THEME["panel"]}; }\n            QLabel { font-weight: 700; }\n            "); layout = QVBoxLayout(dlg)
        
        layout.setSpacing(14); title = QLabel("配置 HTTP/HTTPS 代理"); title.setObjectName("headingLabel"); layout.addWidget(title); form = QFormLayout(); form.setSpacing(10); enable_cb = QCheckBox("启用代理")
        
        enable_cb.setChecked(self.settings.get("proxy_enabled", False)); form.addRow(enable_cb); http_edit = QLineEdit(); http_edit.setPlaceholderText("例: http://127.0.0.1:7890")
        
        http_edit.setText(self.settings.get("proxy_http", "")); form.addRow("HTTP 代理:", http_edit); https_edit = QLineEdit(); https_edit.setPlaceholderText("留空则复用 HTTP 代理")
        
        https_edit.setText(self.settings.get("proxy_https", "")); form.addRow("HTTPS 代理:", https_edit)
        
        layout.addLayout(form); status_lbl = QLabel(proxy_status_text(self.settings)); status_lbl.setObjectName("emphasisLabel")
        
        layout.addWidget(status_lbl); btn_row = QHBoxLayout(); btn_row.addStretch(1)
        
        save_btn = QPushButton("保存并启动爬虫"); save_btn.clicked.connect((lambda: (self._apply_proxy_settings(enable_cb.isChecked(), http_edit.text().strip(), https_edit.text().strip()),
    
    dlg.accept(),
    
    self._on_first_launch_complete()))); cancel_btn = QPushButton("取消"); cancel_btn.clicked.connect(dlg.reject); btn_row.addWidget(save_btn)
        
        btn_row.addWidget(cancel_btn); layout.addLayout(btn_row); dlg.exec()
    
    def _apply_proxy_settings(self, enabled: "bool", http_proxy: "str", https_proxy: "str") -> "None":
        self.settings["proxy_enabled"] = enabled; self.settings["proxy_http"] = http_proxy; self.settings["proxy_https"] = https_proxy
        
        set_proxy_settings(self.settings); self._save_settings(); logger.info("代理设置已更新: enabled=%s, http=%s, https=%s", enabled, http_proxy, https_proxy)
    
    def _on_first_launch_complete(self) -> "None":
        if not self._is_first_launch:
            return
        self._is_first_launch = False
        self.settings["is_first_launch"] = False
        
        self._save_settings(); self._refresh_site_cards(); logger.info("首次启动配置完成，爬虫已启动")
    
    def _open_chart_window(self) -> "None":
        if not self._assert_activated():
            return
        self._load_filtered_messages()
    
    def _refresh_message_view(self) -> "None":
        if not hasattr(self, "result_view"):
            return
        filtered = self._filtered_messages_for_view(); total_pages = max(1, ceil(len(filtered) / (self.messages_per_page))); self.message_page = min(self.message_page, total_pages - 1); start = (self.message_page) * (self.messages_per_page); end = start + (self.messages_per_page); page_rows = filtered[start:end]; page_ids = [id(msg)]
        if getattr(self, "_last_rendered_message_ids", None) == page_ids:
            return
        elif len(page_rows) > 25:
            rendered_rows = page_rows[:20] + page_rows[-5:]
        else:
            rendered_rows = page_rows
        
        self.result_view.clear(); cursor = self.result_view.textCursor()
        
        for index, msg in enumerate(rendered_rows):
            if len(page_rows) > 25 and index == 20:
                cursor.insertHtml(f"<p style='color:#4f6f8b;'>... {len(page_rows) - 25} messages hidden ...</p>")
            cursor.insertHtml(self._message_html(msg))
            cursor.insertHtml("<br/><br/>")
        
        self.result_view.moveCursor(QTextCursor.Start); self.page_label.setText(f"第 {(self.message_page) + 1} / {total_pages} 页"); self._last_rendered_message_ids = page_ids
    
    def _filtered_messages_for_view(self) -> "list":
        right_selected_groups = self.chart_window.selected_groups()
        if not self.chart_window.group_list.count() and right_selected_groups:
            return []
        elif right_selected_groups:
            return pass
        
        return base_messages
    
    def _prev_page(self) -> "None":
        if not hasattr(self, "result_view"):
            return
        elif self.message_page > 0:
            self.message_page -= 1
            self._refresh_message_view()
            return
    
    def _next_page(self) -> "None":
        if not hasattr(self, "result_view"):
            return
        filtered = self._filtered_messages_for_view(); total_pages = max(1, ceil(len(filtered) / (self.messages_per_page)))
        if (self.message_page) + 1 < total_pages:
            self.message_page += 1
            self._refresh_message_view()
            return
    
    def _message_html(self, msg) -> "str":
        user_id = msg.sender_id or self._find_user_id_by_name(msg.username)
        return f"{self._pill(msg.ts.strftime("%Y-%m-%d %H:%M"), THEME["time_bg"])}&nbsp;|&nbsp;{self._pill(msg.group, THEME["group_bg"])}&nbsp;|&nbsp;{self._pill(f"{msg.username} {user_id}".strip(), THEME["user_bg"])}&nbsp;|<br/>{self._pill(msg.content, THEME["content_bg"])}"
    
    def _pill(self, value: "str", bg: "str") -> "str":
        safe = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
        return f"<span style='display:inline-block; margin:0 8px 8px 0; padding:6px 10px; background:{bg}; border-radius:12px;'>{safe}</span>"
    
    def _find_user_id_by_name(self, username: "str") -> "str":
        return ""
    
    def _export_messages(self, suffix: "str") -> "None":
        if not self.current_messages:
            QMessageBox.information(self, "暂无数据", "请先加载聊天记录。")
            return
        export_path = self._export_dir_path() / f"filtered_messages{suffix}"; count = self.chat_service.export_filtered_messages(self.current_messages, export_path); self.status_label.setText(f"已导出 {count:,} 条消息到 {export_path}")
    
    def _export_stats_excel(self) -> "None":
        if not self.current_stats.totals:
            QMessageBox.information(self, "暂无统计", "请先执行统计。")
            return
        export_path = self._export_dir_path() / "stats.xlsx"; self.chat_service.export_stats_excel(self.current_stats, export_path); self.status_label.setText(f"已导出 Excel: {export_path}")
    
    def _export_stats_pdf(self) -> "None":
        if not self.current_stats.totals:
            QMessageBox.information(self, "暂无统计", "请先执行统计。")
            return
        export_path = self._export_dir_path() / "stats.pdf"; self.chat_service.export_stats_pdf(self.current_stats, export_path); self.status_label.setText(f"已导出 PDF: {export_path}")
    
    def _pick_export_dir(self) -> "None":
        dir_name = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if dir_name:
            self.settings["export_dir"] = dir_name
            self._save_settings()
            return
    
    def _activate_license(self) -> "None":
        ok, message = self.license_service.activate(self.license_input.toPlainText().strip())
        if ok:
            QMessageBox.information(self, "激活结果", message)
            self._activate_and_launch()
        else:
            QMessageBox.warning(self, "激活失败", message)
        self._refresh_license_banner()
