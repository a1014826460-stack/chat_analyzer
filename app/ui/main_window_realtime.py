from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from app.models import DrawInfo, StatsResult
from app.ui.main_window_theme import THEME
from app.utils.fetch_date import _SITE_INTERVAL_SEC, extract_draw_info, fetch_all_draw_infos, site_label, site_list


logger = logging.getLogger(__name__)


class MainWindowRealtimeMixin:
    def _refresh_site_cards(self) -> None:
        try:
            self._draw_infos = fetch_all_draw_infos()
        except Exception:
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

    def _build_site_card(self, site: str, info: DrawInfo) -> tuple[QFrame, dict[str, QLabel]]:
        frame = QFrame()
        frame.setObjectName("siteFrame")
        layout = QVBoxLayout(frame)
        name_lbl = QLabel(site_label(site))
        period_lbl = QLabel(info.current_period or "-")
        next_lbl = QLabel(info.next_period or "-")
        countdown_lbl = QLabel(self._format_countdown(info.next_countdown))
        open_btn = QPushButton("Use")
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
        self._active_site = site
        self._manual_period_override = False
        self._query_period_override = ""
        self._stats_locked = False
        self._awaiting_next_period = False
        self._last_message_cursor.pop(site, None)
        self.lock_status_label.setText("")
        self.auto_refresh_label.setText("Auto refresh")
        self.auto_refresh_label.setStyleSheet("")
        self._refresh_active_site_info()
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

    def _on_lock_threshold_changed(self, value: int) -> None:
        self._lock_threshold_sec = int(value)
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
            self.chart_window.set_status("locked", "Statistics locked for current period")
            self.chart_window.set_status_seconds(countdown)
            self.lock_status_label.setText("Statistics locked for current period")
            self.auto_refresh_label.setText("Locked")
            self.auto_refresh_label.setStyleSheet(f"color:{THEME['c5']}; font-weight:800;")
        elif not self.current_visual_rows:
            self.chart_window.set_status("empty", "No bets found for current period")
            self.chart_window.set_status_seconds(countdown)
            self.lock_status_label.setText("No bets found for current period")
            self.auto_refresh_label.setText("No data")
            self.auto_refresh_label.setStyleSheet(f"color:{THEME['muted']}; font-weight:800;")
        else:
            self.chart_window.set_status("running", f"Live refresh running · {countdown:,}s to deadline")
            self.chart_window.set_status_seconds(countdown)
            self.lock_status_label.setText(f"Live refresh running · {countdown:,}s to deadline")
            self.auto_refresh_label.setText("Live")
            self.auto_refresh_label.setStyleSheet(f"color:{THEME['c2']}; font-weight:800;")
