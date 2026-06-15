from __future__ import annotations

import logging
from datetime import datetime, timedelta

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout

from app.models import DrawInfo, StatsResult
from app.ui.main_window_theme import THEME
from app.utils.fetch_date import _SITE_INTERVAL_SEC, extract_draw_info, fetch_all_draw_infos, site_label, site_list


logger = logging.getLogger(__name__)

CALIBRATION_DELAY_SEC = 10
CALIBRATION_RETRY_DELAY_SEC = 5
CALIBRATION_MAX_RETRIES = 3


class MainWindowRealtimeMixin:
    def _refresh_site_cards(self) -> None:
        self._draw_infos = {
            site: self._draw_infos.get(site, DrawInfo(current_period="")) for site in site_list()
        }
        self._render_site_cards()
        if hasattr(self, "site_status_label"):
            self.site_status_label.setText("正在后台加载线路数据...")
        future = self._worker.submit(fetch_all_draw_infos)
        future.add_done_callback(self._handle_site_cards_loaded)

    def _render_site_cards(self) -> None:
        sites = site_list()
        if self._site_card_widgets and set(self._site_card_widgets) == set(sites) and self.site_cards_layout.count():
            for site in sites:
                self._update_site_card_widgets(site, self._draw_infos.get(site, DrawInfo(current_period="")))
            if hasattr(self, "site_status_label"):
                self.site_status_label.setText("线路数据已加载")
            return

        while self.site_cards_layout.count():
            item = self.site_cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

        self._site_card_widgets = {}
        for index, site in enumerate(sites):
            frame, widgets = self._build_site_card(site, self._draw_infos.get(site, DrawInfo(current_period="")))
            self.site_cards_layout.addWidget(frame, index // 2, index % 2)
            self._site_card_widgets[site] = widgets

        if hasattr(self, "site_status_label"):
            self.site_status_label.setText("线路数据已加载")

    def _update_site_card_widgets(self, site: str, info: DrawInfo) -> None:
        widgets = self._site_card_widgets.get(site, {})
        if not widgets:
            return
        widgets["name"].setText(site_label(site))
        widgets["period"].setText(f"当前: {info.current_period or '-'}")
        widgets["next"].setText(f"下期: {info.next_period or '-'}")
        widgets["countdown"].setText(f"倒计时: {self._format_countdown(info.next_countdown)}")

    def _handle_site_cards_loaded(self, future) -> None:
        try:
            draw_infos = future.result()
            logger.debug("Loaded draw info for %d sites", len(draw_infos))
        except Exception:
            logger.exception("Failed to load draw info for site cards")
            draw_infos = {site: DrawInfo(current_period="") for site in site_list()}
        if hasattr(self, "_draw_infos_ready"):
            self._draw_infos_ready.emit(draw_infos)
            return

        self._apply_draw_infos(draw_infos)

    def _apply_draw_infos(self, draw_infos: dict[str, DrawInfo]) -> None:
        self._draw_infos = draw_infos
        self._render_site_cards()
        if self._active_site:
            self._refresh_active_site_info()

    def _build_site_card(self, site: str, info: DrawInfo) -> tuple[QFrame, dict[str, QLabel]]:
        frame = QFrame()
        frame.setObjectName("siteFrame")
        frame.setMinimumHeight(120)
        frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)
        name_lbl = QLabel(site_label(site))
        name_lbl.setObjectName("emphasisLabel")
        period_lbl = QLabel(f"当前: {info.current_period or '-'}")
        next_lbl = QLabel(f"下期: {info.next_period or '-'}")
        countdown_lbl = QLabel(f"倒计时: {self._format_countdown(info.next_countdown)}")
        open_btn = QPushButton("切换")
        open_btn.setMaximumWidth(58)
        open_btn.clicked.connect(lambda checked=False, value=site: self._select_site(value))
        top_row = QHBoxLayout()
        top_row.addWidget(name_lbl)
        top_row.addStretch(1)
        top_row.addWidget(open_btn)
        layout.addLayout(top_row)
        layout.addWidget(period_lbl)
        layout.addWidget(next_lbl)
        layout.addWidget(countdown_lbl)
        return frame, {
            "name": name_lbl,
            "period": period_lbl,
            "next": next_lbl,
            "countdown": countdown_lbl,
        }

    def _select_site(self, site: str) -> None:
        logger.info("Switch site: %s", site)
        previous_site = self._active_site
        migrated_legacy_override = False
        if (
            getattr(self, "_manual_period_override", False)
            and getattr(self, "_query_period_override", "")
        ):
            if not hasattr(self, "_query_period_overrides_by_site") or not isinstance(self._query_period_overrides_by_site, dict):
                self._query_period_overrides_by_site = {}
            legacy_override = str(self._query_period_override).strip()
            if previous_site:
                migrated_legacy_override = previous_site not in self._query_period_overrides_by_site
                self._query_period_overrides_by_site.setdefault(previous_site, legacy_override)
            elif site:
                migrated_legacy_override = site not in self._query_period_overrides_by_site
                self._query_period_overrides_by_site.setdefault(site, legacy_override)
        self._active_site = site
        self._query_period_override = self._current_period_override()
        self._manual_period_override = self._has_manual_period_override()
        self._stats_locked = False
        self._awaiting_next_period = False
        self._last_message_cursor.pop(site, None)
        self.lock_status_label.setText("")
        self.auto_refresh_label.setText("自动刷新")
        self.auto_refresh_label.setStyleSheet("")
        self._refresh_active_site_info()
        if hasattr(self, "_set_status"):
            self._set_status(f"已切换线路: {site_label(site)}", "info")
        if migrated_legacy_override and hasattr(self, "_save_settings"):
            self._save_settings()
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
        self._refresh_active_site_info()

    def _on_countdown_tick(self) -> None:
        if not self._draw_infos:
            return
        now = datetime.now()
        for site in site_list():
            info = self._draw_infos.get(site)
            if info is None:
                continue
            self._advance_site_countdown(site, info, now)
        self._submit_due_draw_calibrations(now)
        if hasattr(self, "_render_site_cards"):
            self._render_site_cards()
        if self._active_site:
            self._refresh_active_site_info()

    def _advance_site_countdown(self, site: str, info: DrawInfo, now: datetime) -> None:
        if info.next_time is not None:
            info.next_countdown = max(0, int((info.next_time - now).total_seconds()))
        elif info.next_countdown > 0:
            info.next_countdown -= 1
        if info.next_countdown > 0:
            return
        local_info = self._advance_site_locally(site, info, now)
        self._apply_single_draw_info((site, local_info, None))
        self._schedule_draw_calibration(site, now + timedelta(seconds=CALIBRATION_DELAY_SEC))

    def _calibration_due_map(self) -> dict[str, datetime]:
        due_at = getattr(self, "_draw_calibration_due_at", None)
        if not isinstance(due_at, dict):
            self._draw_calibration_due_at = {}
            due_at = self._draw_calibration_due_at
        return due_at

    def _advance_site_locally(self, site: str, info: DrawInfo, now: datetime) -> DrawInfo:
        interval = info.interval_sec or _SITE_INTERVAL_SEC.get(site, 180)
        start_time = info.next_time or now
        current_period = info.next_period or self._increment_period_text(info.current_period, 1)
        next_time = start_time + timedelta(seconds=interval)
        return DrawInfo(
            current_period=current_period,
            current_time=start_time,
            next_countdown=max(0, int((next_time - now).total_seconds())),
            next_period=self._increment_period_text(current_period, 1),
            next_time=next_time,
            auto_period=current_period,
            start_time=start_time,
            interval_sec=interval,
            source="inferred",
            last_api_success_at=info.last_api_success_at,
        )

    def _schedule_draw_calibration(self, site: str, due_at: datetime) -> None:
        self._calibration_due_map()[site] = due_at

    def _submit_due_draw_calibrations(self, now: datetime) -> None:
        due_map = self._calibration_due_map()
        for site, due_at in list(due_map.items()):
            if due_at > now:
                continue
            due_map.pop(site, None)
            self._submit_site_draw_refresh(site, self._draw_infos.get(site, DrawInfo(current_period="")))

    def _submit_site_draw_refresh(self, site: str, info: DrawInfo) -> None:
        refreshing_sites = self._refreshing_site_set()
        if site in refreshing_sites:
            return
        refreshing_sites.add(site)
        worker = getattr(self, "_worker", None)
        if worker is None:
            refreshing_sites.discard(site)
            self._schedule_draw_calibration(site, datetime.now() + timedelta(seconds=CALIBRATION_RETRY_DELAY_SEC))
            return
        try:
            future = worker.submit(extract_draw_info, site)
        except Exception:
            logger.warning("[%s] failed to submit draw calibration, retry scheduled", site_label(site), exc_info=True)
            refreshing_sites.discard(site)
            self._schedule_draw_calibration(site, datetime.now() + timedelta(seconds=CALIBRATION_RETRY_DELAY_SEC))
            return
        future.add_done_callback(lambda finished, value=site: self._handle_single_draw_info_loaded(value, None, finished))


    def _handle_single_draw_info_loaded(self, site: str, fallback: DrawInfo | None, future) -> None:
        error = None
        try:
            info = future.result()
        except Exception as exc:
            error = exc
            info = None

        self._refreshing_site_set().discard(site)
        if info is None or getattr(info, "source", "api") != "api" or self._is_stale_draw_info(site, info):
            if self._schedule_calibration_retry(site):
                logger.warning("[%s] draw calibration failed or returned stale data, retry scheduled: %s", site_label(site), error or info)
            else:
                logger.warning("[%s] draw calibration failed after retries, keeping inferred period: %s", site_label(site), error or info)
            return

        self._clear_draw_retry_count(site)
        payload = (site, info, error)
        if hasattr(self, "_single_draw_info_ready"):
            self._single_draw_info_ready.emit(payload)
            return
        self._apply_single_draw_info(payload)

    def _apply_single_draw_info(self, payload) -> None:
        site, info, _error = payload
        self._refreshing_site_set().discard(site)
        previous = self._draw_infos.get(site)
        previous_period = str(getattr(previous, "current_period", "") or "").strip()
        incoming_period = str(getattr(info, "current_period", "") or "").strip()
        period_override = MainWindowRealtimeMixin._current_period_override(self)
        previous_query_period = (
            period_override or MainWindowRealtimeMixin._default_query_period(self, previous)
            if previous is not None
            else ""
        )
        incoming_query_period = period_override or MainWindowRealtimeMixin._default_query_period(self, info)
        active_period_changed = bool(
            self._active_site == site
            and incoming_period
            and previous_period
            and incoming_period != previous_period
        )
        active_query_period_changed = bool(
            self._active_site == site
            and incoming_query_period
            and previous_query_period
            and incoming_query_period != previous_query_period
        )
        self._draw_infos[site] = info
        self._update_site_card_widgets(site, info)
        if self._active_site == site:
            if active_period_changed or active_query_period_changed:
                MainWindowRealtimeMixin._handle_active_site_period_changed(self, site)
            self._refresh_active_site_info()

    def _handle_active_site_period_changed(self, site: str) -> None:
        last_cursor = getattr(self, "_last_message_cursor", None)
        if isinstance(last_cursor, dict):
            last_cursor.pop(site, None)
        self._stats_locked = False
        self._awaiting_next_period = False
        if hasattr(self, "current_messages"):
            self.current_messages = []
        if hasattr(self, "current_visual_rows"):
            self.current_visual_rows = []
        if hasattr(self, "current_stats"):
            self.current_stats = StatsResult(totals={}, totals_by_group={})
        if hasattr(self, "chart_window") and hasattr(self.chart_window, "replace_rows"):
            self.chart_window.replace_rows([])
        info = self._draw_infos.get(site, DrawInfo(current_period=""))
        if hasattr(self, "period_input"):
            self._sync_period_input_from_site(info)
        if not MainWindowRealtimeMixin._has_manual_period_override(self) and hasattr(self, "_load_filtered_messages"):
            self._load_filtered_messages()

    def _refreshing_site_set(self) -> set[str]:
        refreshing = getattr(self, "_refreshing_sites", None)
        if isinstance(refreshing, set):
            return refreshing
        self._refreshing_sites = set()
        return self._refreshing_sites

    def _draw_retry_count(self, site: str) -> int:
        counts = getattr(self, "_draw_retry_counts", None)
        if not isinstance(counts, dict):
            self._draw_retry_counts = {}
            counts = self._draw_retry_counts
        return int(counts.get(site, 0) or 0)

    def _set_draw_retry_count(self, site: str, count: int) -> None:
        counts = getattr(self, "_draw_retry_counts", None)
        if not isinstance(counts, dict):
            self._draw_retry_counts = {}
            counts = self._draw_retry_counts
        counts[site] = int(count)

    def _clear_draw_retry_count(self, site: str) -> None:
        counts = getattr(self, "_draw_retry_counts", None)
        if isinstance(counts, dict):
            counts.pop(site, None)

    def _compare_period_text(self, left: str, right: str) -> int:
        left_text = str(left or "").strip()
        right_text = str(right or "").strip()
        if left_text.isdigit() and right_text.isdigit():
            left_int = int(left_text)
            right_int = int(right_text)
            return (left_int > right_int) - (left_int < right_int)
        return (left_text > right_text) - (left_text < right_text)

    def _is_stale_draw_info(self, site: str, info: DrawInfo) -> bool:
        current = self._draw_infos.get(site)
        if current is None or not current.current_period or not info.current_period:
            return False
        return self._compare_period_text(info.current_period, current.current_period) < 0

    def _schedule_calibration_retry(self, site: str) -> bool:
        retry_count = self._draw_retry_count(site) + 1
        if retry_count > CALIBRATION_MAX_RETRIES:
            self._clear_draw_retry_count(site)
            return False
        self._set_draw_retry_count(site, retry_count)
        self._schedule_draw_calibration(site, datetime.now() + timedelta(seconds=CALIBRATION_RETRY_DELAY_SEC))
        return True

    def _extrapolate_next_draw_info(self, site: str, info: DrawInfo) -> DrawInfo:
        interval = _SITE_INTERVAL_SEC.get(site, 180)
        current_period = info.next_period or self._increment_period_text(info.current_period, 1)
        return DrawInfo(
            current_period=current_period,
            next_period=self._increment_period_text(current_period, 1),
            next_countdown=interval,
            auto_period=current_period,
        )

    def _increment_period_text(self, period: str, delta: int) -> str:
        raw = str(period or "").strip()
        if not raw:
            return ""
        if not raw.isdigit():
            return raw
        return str(int(raw) + delta).zfill(len(raw))

    def _preserve_latest_draw_info(self, latest: DrawInfo, fetched: DrawInfo) -> DrawInfo:
        return fetched if fetched.current_period else latest

    def _default_query_period(self, info: DrawInfo) -> str:
        return info.next_period or info.current_period

    def _current_period_override(self) -> str:
        return str(getattr(self, "_query_period_overrides_by_site", {}).get(self._active_site or "", "")).strip()

    def _has_manual_period_override(self) -> bool:
        if not hasattr(self, "_current_period_override"):
            return False
        return bool(self._current_period_override())

    def _sync_period_input_from_site(self, info: DrawInfo) -> None:
        if hasattr(self.period_input, "hasFocus") and self.period_input.hasFocus():
            return
        text = self._current_period_override() or self._default_query_period(info)
        self.period_input.blockSignals(True)
        self.period_input.setText(text)
        self.period_input.blockSignals(False)

    def _on_period_input_changed(self) -> None:
        if not self._active_site:
            return
        if not hasattr(self, "_query_period_overrides_by_site") or not isinstance(self._query_period_overrides_by_site, dict):
            self._query_period_overrides_by_site = {}
        value = self.period_input.text().strip()
        default_value = ""
        if self._active_site:
            default_value = self._default_query_period(self._draw_infos.get(self._active_site, DrawInfo(current_period="")))
        if value and value != default_value:
            self._query_period_overrides_by_site[self._active_site] = value
        else:
            self._query_period_overrides_by_site.pop(self._active_site, None)
        self._query_period_override = self._query_period_overrides_by_site.get(self._active_site, "")
        self._manual_period_override = bool(self._query_period_override)
        logger.debug("Query period changed: site=%s period=%s", self._active_site, value)
        self._save_settings()

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
