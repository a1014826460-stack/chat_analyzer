from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QTimer, Signal, Qt
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QShowEvent
from PySide6.QtWidgets import QApplication, QMainWindow, QMenuBar, QMessageBox, QStackedWidget, QTextEdit, QVBoxLayout, QWidget, QLabel, QPushButton

from app.build_config import IS_ADMIN_VERSION
from app.models import StatsResult
from app.services.account_resolver import AccountResolver
from app.services.chat_service import ChatLogService
from app.services.license_service import LicenseService
from app.services.settings_service import SettingsService
from app.ui.license_generator_dialog import LicenseGeneratorDialog
from app.ui.main_window_actions import MainWindowActionsMixin
from app.ui.main_window_blocking import MainWindowBlockingMixin
from app.ui.main_window_data import MainWindowDataMixin
from app.ui.main_window_layout import MainWindowLayoutMixin
from app.ui.main_window_realtime import MainWindowRealtimeMixin
from app.ui.main_window_theme import LOCK_THRESHOLD_DEFAULT_SEC, THEME
from app.utils.fetch_date import set_proxy_settings
from app.utils.pathing import resource_path


logger = logging.getLogger(__name__)


class MainWindow(
    MainWindowLayoutMixin,
    MainWindowBlockingMixin,
    MainWindowRealtimeMixin,
    MainWindowDataMixin,
    MainWindowActionsMixin,
    QMainWindow,
):
    _load_result_ready = Signal(object)
    _draw_infos_ready = Signal(object)
    _single_draw_info_ready = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("StarTrace Analyzer" + (" (Admin)" if IS_ADMIN_VERSION else ""))
        self.resize(1400, 900)
        self.setMinimumSize(1180, 720)

        self.chat_service = ChatLogService()
        self.license_service = LicenseService()
        self.settings_service = SettingsService()
        self.account_resolver = AccountResolver()
        self.settings = self.settings_service.load()

        self.current_messages = []
        self.raw_chat_messages = []
        self.current_stats = StatsResult(totals={}, totals_by_group={})
        self.current_visual_rows = []
        self.resolved_db = None
        self.global_block_names: list[str] = []
        self.group_block_rules: dict[str, dict[str, object]] = {}
        self.message_page = 0
        self.messages_per_page = 50
        self._draw_infos = {}
        self._active_site = ""
        self._stats_locked = False
        self._lock_threshold_sec = int(self.settings.get("lock_threshold_sec", LOCK_THRESHOLD_DEFAULT_SEC))
        self._site_card_widgets: dict[str, dict[str, QLabel]] = {}
        self._refreshing_sites: set[str] = set()
        self._draw_retry_counts: dict[str, int] = {}
        self._awaiting_next_period = False
        legacy_period = str(self.settings.get("query_period_override", "")).strip()
        legacy_manual = bool(self.settings.get("manual_period_override", False))
        overrides_raw = self.settings.get("query_period_overrides_by_site", {})
        self._query_period_overrides_by_site = {
            str(key): str(value).strip()
            for key, value in dict(overrides_raw if isinstance(overrides_raw, dict) else {}).items()
            if str(value).strip()
        }
        self._query_period_override = legacy_period
        self._manual_period_override = legacy_manual
        self._last_loaded_signature = None
        self._last_message_cursor: dict[str, tuple[int, int]] = {}
        self._message_load_sequence = 0
        self._message_load_in_progress = False
        self._splitter_initialized = False
        self._is_first_launch = bool(self.settings.get("is_first_launch", True))

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._on_refresh_tick)
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._on_countdown_tick)
        self._message_refresh_timer = QTimer(self)
        self._message_refresh_timer.setInterval(5000)
        self._message_refresh_timer.timeout.connect(self._on_message_refresh_tick)
        self._load_result_ready.connect(self._handle_load_result_ready)
        self._draw_infos_ready.connect(self._apply_draw_infos)
        self._single_draw_info_ready.connect(self._apply_single_draw_info)
        self._worker = ThreadPoolExecutor(max_workers=2)
        self._data_worker = ThreadPoolExecutor(max_workers=1)

        self._apply_icon()
        group_rules_raw = self.settings.get("blocked_names_by_group", {})
        if "global_block_names" in self.settings:
            global_block_source = self.settings.get("global_block_names", [])
        elif group_rules_raw:
            # Legacy `blocked_names` may contain a mix of true global names and
            # flattened group-only names. Preserve only names that are not
            # already present in the saved group rules.
            legacy_blocked_names = self._sanitize_block_names(self.settings.get("blocked_names", []))
            group_rule_names = set()
            normalized_group_rules = self._normalize_saved_block_rules(group_rules_raw)
            for rule in normalized_group_rules.values():
                for name in rule.get("names", []):
                    group_rule_names.add(self._normalize_block_name(str(name)))
            global_block_source = [
                name for name in legacy_blocked_names if self._normalize_block_name(name) not in group_rule_names
            ]
        else:
            global_block_source = self.settings.get("blocked_names", [])
        self.global_block_names = self._sanitize_block_names(global_block_source)
        self._set_group_block_rules(group_rules_raw)

        self.tabs = QStackedWidget()
        self.setCentralWidget(self.tabs)
        self.analysis_page: QWidget | None = None
        self.license_page = QWidget()
        self.tabs.addWidget(self.license_page)

        menubar = QMenuBar()
        help_menu = menubar.addMenu("帮助")
        about_action = QAction("关于", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
        proxy_action = QAction("代理设置", self)
        proxy_action.triggered.connect(self._open_proxy_settings)
        help_menu.addAction(proxy_action)
        if IS_ADMIN_VERSION:
            license_action = QAction("生成激活码", self)
            license_action.triggered.connect(self._show_admin_license_panel)
            help_menu.addAction(license_action)
        self.setMenuBar(menubar)

        self._build_license_page()
        self._apply_theme()
        self._refresh_license_banner()
        set_proxy_settings(self.settings)

        self._activate_and_launch()

    def _activate_and_launch(self) -> None:
        if self.analysis_page is None:
            self.analysis_page = QWidget()
            self._build_analysis_page()
            self.tabs.insertWidget(0, self.analysis_page)
        self._load_initial_state()
        self._refresh_site_cards()
        self.tabs.setCurrentWidget(self.analysis_page)

    def _show_activation_required(self) -> None:
        self.license_status_label.setText("软件未激活。")
        self.tabs.setCurrentWidget(self.license_page)

    def _show_admin_license_panel(self) -> None:
        if not IS_ADMIN_VERSION:
            return
        dlg = LicenseGeneratorDialog(self.license_service, self)
        dlg.exec()

    def _set_status(self, message: str, log_level: str = "debug") -> None:
        if hasattr(self, "status_label"):
            self.status_label.setText(message)
        log_method = getattr(logger, log_level, logger.debug)
        log_method(message)

    def _run_ui_action(
        self,
        action_name: str,
        callback: Callable[[], Any],
        *,
        started: str | None = None,
        finished: str | None = None,
        error_title: str = "操作失败",
    ) -> Any:
        logger.debug("UI action clicked: %s", action_name)
        if started:
            self._set_status(started, "info")
        try:
            result = callback()
        except Exception as exc:
            logger.exception("UI action failed: %s", action_name)
            self._set_status(f"{error_title}: {exc}", "error")
            QMessageBox.warning(self, error_title, str(exc))
            return None
        if finished:
            self._set_status(finished, "info")
        return result

    def _reset_button_text_later(self, button: QPushButton, text: str, delay_ms: int = 1500) -> None:
        QTimer.singleShot(delay_ms, lambda: button.setText(text))

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._splitter_initialized:
            return
        self._splitter_initialized = True
        QTimer.singleShot(0, self._apply_initial_splitter_sizes)
        self._countdown_timer.start(1000)
        self._message_refresh_timer.start()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._refresh_timer.stop()
        self._countdown_timer.stop()
        self._message_refresh_timer.stop()
        self._worker.shutdown(wait=False, cancel_futures=True)
        self._data_worker.shutdown(wait=False, cancel_futures=True)
        super().closeEvent(event)

    def _build_license_page(self) -> None:
        layout = QVBoxLayout(self.license_page)
        self.license_status_label = QLabel("")
        self.license_status_label.setObjectName("headingLabel")
        self.machine_code_label = QLabel(f"机器码: {self.license_service.get_machine_code()}")
        self.machine_code_copy_btn = QPushButton("复制机器码")
        self.machine_code_copy_btn.clicked.connect(self._copy_user_machine_code)
        self.license_input = QTextEdit()
        activate_btn = QPushButton("激活")
        activate_btn.clicked.connect(self._activate_license)
        layout.addWidget(self.license_status_label)
        layout.addWidget(self.machine_code_label)
        layout.addWidget(self.machine_code_copy_btn, alignment=Qt.AlignLeft)
        layout.addWidget(self.license_input)
        layout.addWidget(activate_btn, alignment=Qt.AlignLeft)
        layout.addStretch(1)

    def _copy_user_machine_code(self) -> None:
        QApplication.clipboard().setText(self.license_service.get_machine_code())
        logger.info("Machine code copied to clipboard")
        self.machine_code_copy_btn.setText("已复制")
        self._reset_button_text_later(self.machine_code_copy_btn, "复制机器码")

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            f"""
            QWidget {{
                background: {THEME['bg']};
                color: {THEME['text']};
                font-family: 'Microsoft YaHei UI';
                font-size: 13px;
            }}
            QGroupBox, QFrame#siteFrame, QFrame#statsFrame {{
                background: {THEME['panel']};
                border: 1px solid {THEME['border']};
                border-radius: 14px;
            }}
            QGroupBox {{
                margin-top: 12px;
                padding-top: 14px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 12px;
                padding: 0 6px;
                background: {THEME['panel']};
            }}
            QLineEdit, QTextEdit, QComboBox, QListWidget, QSpinBox {{
                background: white;
                border: 1px solid {THEME['border']};
                border-radius: 10px;
                padding: 6px 8px;
            }}
            QPushButton {{
                background: {THEME['c2']};
                color: white;
                border: none;
                border-radius: 12px;
                padding: 8px 12px;
                font-weight: 700;
            }}
            QLabel#headingLabel, QLabel#emphasisLabel {{
                font-weight: 800;
            }}
            """
        )

    def _apply_icon(self) -> None:
        icon_path = resource_path("assets", "favicon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    def _refresh_license_banner(self) -> None:
        info = self.license_service.load_license()
        if self.license_service.is_activated():
            self.license_status_label.setText(f"已激活，有效期至 {info.expires_at:%Y-%m-%d %H:%M}")
        else:
            self.license_status_label.setText("未激活")

    def _assert_activated(self) -> bool:
        if IS_ADMIN_VERSION:
            return True
        return True

    def _toggle_advanced_time(self) -> None:
        visible = not self.advanced_time_frame.isVisible()
        self.advanced_time_frame.setVisible(visible)
        self.advanced_time_toggle.setText(
            "- 高级时间筛选" if visible else "+ 高级时间筛选"
        )
        logger.debug("Advanced time filter visible=%s", visible)

    def _toggle_chat_panel(self) -> None:
        return None


def run_app() -> None:
    app = QApplication([])
    icon_path = resource_path("assets", "favicon.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    app.exec()
