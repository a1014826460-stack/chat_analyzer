from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from app.models import DrawInfo
from app.ui.main_window_theme import THEME
from app.utils.fetch_date import extract_draw_info, fetch_all_draw_infos, site_label, site_list


logger = logging.getLogger(__name__)


class MainWindowRealtimeMixin:
    def _refresh_site_cards(self) -> None:
        try:
            self._draw_infos = fetch_all_draw_infos()
            logger.debug("Loaded draw info for %d sites", len(self._draw_infos))
        except Exception:
            logger.exception("Failed to load draw info for site cards")
            self._draw_infos = {site: DrawInfo(current_period="") for site in site_list()}

        while self.site_cards_layout.count():
            item = self.site_cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._site_card_widgets = {}
        for index, site in enumerate(site_list()):
            frame, widgets = self._build_site_card(site, self._draw_infos.get(site, DrawInfo(current_period="")))
            self.site_cards_layout.addWidget(frame, index // 2, index % 2)
            self._site_card_widgets[site] = widgets

        if hasattr(self, "site_status_label"):
            self.site_status_label.setText("线路数据已加载")

    def _build_site_card(self, site: str, info: DrawInfo) -> tuple[QFrame, dict[str, QLabel]]:
        frame = QFrame()
        frame.setObjectName("siteFrame")
        layout = QVBoxLayout(frame)
        name_lbl = QLabel(site_label(site))
        period_lbl = QLabel(f"当前期: {info.current_period or '-'}")
        next_lbl = QLabel(f"下一期: {info.next_period or '-'}")
        countdown_lbl = QLabel(f"倒计时: {self._format_countdown(info.next_countdown)}")
        open_btn = QPushButton("切换")
        open_btn.clicked.connect(lambda checked=False, value=site: self._select_site(value))
        layout.addWidget(name_lbl)
        layout.addWidget(period_lbl)
        layout.addWidget(next_lbl)
        layout.addWidget(countdown_lbl)
        layout.addWidget(open_btn)
        return frame, {
            "name": name_lbl,
            "period": period_lbl,
            "next": next_lbl,
            "countdown": countdown_lbl,
        }

    def _select_site(self, site: str) -> None:
        logger.info("Switch site: %s", site)
        self._active_site = site
        self._manual_period_override = False
        self._query_period_override = ""
        self._stats_locked = False
        self._awaiting_next_period = False
        self._last_message_cursor.pop(site, None)
        self.lock_status_label.setText("")
        self.auto_refresh_label.setText("自动刷新")
        self.auto_refresh_label.setStyleSheet("")
        self._refresh_active_site_info()
        if hasattr(self, "_set_status"):
            self._set_status(f"已切换线路: {site_label(site)}", "info")
        self._load_filtered_messages()

    def _refresh_active_site_info(self) -> None:
        if not self._active_site:
            return
        info = self._draw_infos.get(self._active_site, DrawInfo(current_period=""))
        self.active_site_label.setText(site_label(self._active_site))
        self.active_period_label.setText(info.current_period or "-")
        self.next_period_label.setText(info.next_period or "-")
        self.countdown_label.setText(self._format_countdown(info.next_countdown))
        self._sync_period_input_from_site(info)
        self._sync_chart_status()

    def _on_refresh_tick(self) -> None:
        if not self._active_site:
            return
        try:
            self._draw_infos[self._active_site] = extract_draw_info(self._active_site)
        except Exception:
            logger.exception("Failed to refresh draw info for %s", self._active_site)
        self._refresh_active_site_info()

    def _on_countdown_tick(self) -> None:
        if not self._active_site:
            return
        info = self._draw_infos.get(self._active_site)
        if info is None:
            return
        if info.next_time is not None:
            info.next_countdown = max(0, int((info.next_time - datetime.now()).total_seconds()))
        elif info.next_countdown > 0:
            info.next_countdown -= 1
        self._refresh_active_site_info()

    def _preserve_latest_draw_info(self, latest: DrawInfo, fetched: DrawInfo) -> DrawInfo:
        return fetched if fetched.current_period else latest

    def _default_query_period(self, info: DrawInfo) -> str:
        return info.next_period or info.current_period

    def _sync_period_input_from_site(self, info: DrawInfo) -> None:
        if self._manual_period_override:
            return
        self.period_input.blockSignals(True)
        self.period_input.setText(self._default_query_period(info))
        self.period_input.blockSignals(False)

    def _on_period_input_changed(self) -> None:
        self._query_period_override = self.period_input.text().strip()
        self._manual_period_override = bool(self._query_period_override)
        logger.debug("Query period changed: manual=%s period=%s", self._manual_period_override, self._query_period_override)

    def _on_lock_threshold_changed(self, value: int) -> None:
        self._lock_threshold_sec = int(value)
        logger.info("Lock threshold changed: %s seconds", self._lock_threshold_sec)
        self._save_settings()
        self._sync_chart_status()

    def _format_countdown(self, value: int) -> str:
        value = max(0, int(value))
        minutes, seconds = divmod(value, 60)
        return f"{minutes:02d}:{seconds:02d}"

    def _sync_chart_status(self) -> None:
        if not hasattr(self, "chart_window"):
            return
        countdown = 0
        if self._active_site:
            countdown = self._draw_infos.get(self._active_site, DrawInfo(current_period="")).next_countdown
        if self._stats_locked:
            status_text = "当前期数统计已锁定"
            self.chart_window.set_status("locked", status_text)
            self.chart_window.set_status_seconds(countdown)
            self.lock_status_label.setText(status_text)
            self.auto_refresh_label.setText("已锁定")
            self.auto_refresh_label.setStyleSheet(f"color:{THEME['c5']}; font-weight:800;")
        elif not self.current_visual_rows:
            status_text = "当前期未找到下注记录"
            self.chart_window.set_status("empty", status_text)
            self.chart_window.set_status_seconds(countdown)
            self.lock_status_label.setText(status_text)
            self.auto_refresh_label.setText("无数据")
            self.auto_refresh_label.setStyleSheet(f"color:{THEME['muted']}; font-weight:800;")
        else:
            status_text = f"实时刷新运行中 · 距锁定 {countdown:,} 秒"
            self.chart_window.set_status("running", status_text)
            self.chart_window.set_status_seconds(countdown)
            self.lock_status_label.setText(status_text)
            self.auto_refresh_label.setText("运行中")
            self.auto_refresh_label.setStyleSheet(f"color:{THEME['c2']}; font-weight:800;")
