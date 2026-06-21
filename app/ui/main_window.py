from __future__ import annotations

import base64
import logging
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer, Signal, Qt
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QShowEvent
from PySide6.QtWidgets import QApplication, QMainWindow, QMenuBar, QMessageBox, QStackedWidget, QTextEdit, QVBoxLayout, QWidget, QLabel, QPushButton

from app.build_config import APP_VERSION, IS_ADMIN_VERSION, UPDATE_PUBLIC_KEY_PEM, update_manifest_url
from app.models import StatsResult
from app.services.account_resolver import AccountResolver
from app.services.chat_service import ChatLogService
from app.services.license_service import LicenseService
from app.services.settings_service import SettingsService
from app.services.summary_check_report_service import SummaryCheckReportService
from app.services.update_installer import schedule_update_install
from app.services.update_service import download_and_verify, fetch_manifest, update_available
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
    _update_check_ready = Signal(object)
    _update_download_ready = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("StarTrace Analyzer" + (" (Admin)" if IS_ADMIN_VERSION else ""))
        self.setMinimumSize(1180, 720)

        self.chat_service = ChatLogService()
        self.license_service = LicenseService()
        self.settings_service = SettingsService()
        self.account_resolver = AccountResolver()
        self.settings = self.settings_service.load()
        summary_export_dir = str(self.settings.get("export_dir", "") or "").strip()
        self.summary_check_report_service = SummaryCheckReportService(Path(summary_export_dir).expanduser() if summary_export_dir else Path.cwd())

        self.current_messages = []
        self.raw_chat_messages = []
        self.summary_check_history = []
        self.current_stats = StatsResult(totals={}, totals_by_group={})
        self.current_visual_rows = []
        self.resolved_db = None
        self.global_block_names: list[str] = []
        self.group_block_rules: dict[str, dict[str, object]] = {}
        self.group_types_by_id: dict[str, str] = {
            str(key).strip(): str(value).strip()
            for key, value in dict(self.settings.get("group_types_by_id", {})).items()
            if str(key).strip() and str(value).strip()
        }
        self.group_type_switches_by_id: dict[str, dict[str, object]] = {
            str(key).strip(): dict(value)
            for key, value in dict(self.settings.get("group_type_switches_by_id", {})).items()
            if str(key).strip() and isinstance(value, dict)
        }
        self.group_robot_ids: dict[str, str] = {
            str(key).strip(): str(value).strip()
            for key, value in dict(self.settings.get("group_robot_ids", {})).items()
            if str(key).strip() and str(value).strip()
        }
        self.chat_service.set_group_robot_ids(self.group_robot_ids)
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
        self._update_check_ready.connect(self._handle_update_check_ready)
        self._update_download_ready.connect(self._handle_update_download_ready)
        self._worker = ThreadPoolExecutor(max_workers=2)
        self._data_worker = ThreadPoolExecutor(max_workers=1)

        self._apply_icon()
        self._restore_window_state()
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
        QTimer.singleShot(1500, self._check_for_updates_async)

    def _activate_and_launch(self) -> None:
        if not self._assert_activated():
            self._show_activation_required()
            return
        if self.analysis_page is None:
            self.analysis_page = QWidget()
            self._build_analysis_page()
            self.tabs.insertWidget(0, self.analysis_page)
        self._load_initial_state()
        self._refresh_site_cards()
        self.tabs.setCurrentWidget(self.analysis_page)

    def _show_activation_required(self) -> None:
        self.license_status_label.setText("软件未激活 — 请输入有效的激活码以继续使用")
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
        self._persist_window_state()
        self._refresh_timer.stop()
        self._countdown_timer.stop()
        self._message_refresh_timer.stop()
        self._worker.shutdown(wait=False, cancel_futures=True)
        self._data_worker.shutdown(wait=False, cancel_futures=True)
        super().closeEvent(event)

    def _restore_window_state(self) -> None:
        settings = getattr(self, "settings", {}) or {}
        restored_geometry = False
        geometry_b64 = str(settings.get("window_geometry_b64", "") or "").strip()
        if geometry_b64:
            try:
                restored_geometry = bool(self.restoreGeometry(base64.b64decode(geometry_b64.encode("ascii"))))
            except Exception:
                logger.warning("Failed to restore window geometry", exc_info=True)
        state_b64 = str(settings.get("window_state_b64", "") or "").strip()
        if state_b64:
            try:
                self.restoreState(base64.b64decode(state_b64.encode("ascii")))
            except Exception:
                logger.warning("Failed to restore window state", exc_info=True)
        if restored_geometry:
            return
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            self.resize(1400, 900)
            return
        available = screen.availableGeometry()
        target_width = max(self.minimumWidth(), int(available.width() * 0.9))
        target_height = max(self.minimumHeight(), int(available.height() * 0.88))
        self.resize(target_width, target_height)

    def _persist_window_state(self) -> None:
        settings = getattr(self, "settings", {}) or {}
        settings["window_geometry_b64"] = base64.b64encode(bytes(self.saveGeometry())).decode("ascii")
        settings["window_state_b64"] = base64.b64encode(bytes(self.saveState())).decode("ascii")
        splitter = getattr(self, "main_splitter", None)
        if splitter is not None and hasattr(splitter, "sizes"):
            settings["main_splitter_sizes"] = [int(value) for value in splitter.sizes()]
        self.settings = settings
        if hasattr(self, "_save_settings"):
            self._save_settings()

    def _build_license_page(self) -> None:
        layout = QVBoxLayout(self.license_page)
        heading = QLabel("StarTrace 激活")
        self.license_status_label = QLabel("")
        self.machine_code_label = QLabel(f"机器码: {self.license_service.get_machine_code()}")
        self.machine_code_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.machine_code_copy_btn = QPushButton("复制机器码")
        self.machine_code_copy_btn.clicked.connect(self._copy_user_machine_code)
        self.license_input = QTextEdit()
        self.license_input.setPlaceholderText("在此粘贴从管理员处获取的激活码...")
        self.license_input.setFixedHeight(80)
        activate_btn = QPushButton("激活")
        activate_btn.clicked.connect(self._activate_license)
        layout.addWidget(heading)
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
        return self.license_service.is_activated()

    def _check_for_updates_async(self) -> None:
        manifest_url = update_manifest_url()
        if not manifest_url or not UPDATE_PUBLIC_KEY_PEM:
            logger.debug("Update check skipped: manifest URL or public key is not configured")
            return
        self._data_worker.submit(self._check_for_updates_worker, manifest_url, UPDATE_PUBLIC_KEY_PEM)

    def _check_for_updates_worker(self, manifest_url: str, public_key_pem: str) -> None:
        try:
            manifest = fetch_manifest(manifest_url, public_key_pem)
            if update_available(APP_VERSION, manifest):
                self._update_check_ready.emit({"ok": True, "manifest": manifest})
            else:
                logger.debug("No update available: current=%s remote=%s", APP_VERSION, manifest.get("version"))
        except Exception as exc:
            logger.warning("Update check failed: %s", exc)

    def _handle_update_check_ready(self, payload: object) -> None:
        if not isinstance(payload, dict) or not payload.get("ok"):
            return
        manifest = payload.get("manifest")
        if not isinstance(manifest, dict):
            return
        version = str(manifest.get("version", ""))
        notes = str(manifest.get("notes", "")).strip()
        force = bool(manifest.get("force", False))
        message = f"检测到新版本 {version}，是否现在下载？"
        if notes:
            message += f"\n\n{notes}"
        buttons = QMessageBox.Ok if force else QMessageBox.Ok | QMessageBox.Cancel
        if QMessageBox.information(self, "软件更新", message, buttons) != QMessageBox.Ok:
            return
        self._data_worker.submit(self._download_update_worker, manifest)

    def _download_update_worker(self, manifest: dict[str, object]) -> None:
        try:
            file_name = Path(str(manifest.get("url", "StarTrace-update.exe"))).name or "StarTrace-update.exe"
            target_path = Path(tempfile.gettempdir()) / "StarTraceUpdates" / file_name
            ok = download_and_verify(manifest, target_path)
            self._update_download_ready.emit({"ok": ok, "path": str(target_path), "manifest": manifest})
        except Exception as exc:
            logger.warning("Update download failed: %s", exc)
            self._update_download_ready.emit({"ok": False, "error": str(exc), "manifest": manifest})

    def _handle_update_download_ready(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        if payload.get("ok"):
            if not getattr(sys, "frozen", False):
                QMessageBox.information(
                    self,
                    "更新已下载",
                    f"新版本已下载并通过校验。\n文件位置：{payload.get('path')}\n开发环境不会自动替换运行文件。",
                )
                return
            choice = QMessageBox.information(
                self,
                "更新已下载",
                "新版本已下载并通过校验。是否立即安装并重启？",
                QMessageBox.Ok | QMessageBox.Cancel,
            )
            if choice == QMessageBox.Ok:
                schedule_update_install(
                    current_exe=Path(sys.executable),
                    staged_exe=Path(str(payload.get("path", ""))),
                )
                QApplication.quit()
        else:
            QMessageBox.warning(self, "更新失败", f"更新下载或校验失败：{payload.get('error', 'hash mismatch')}")

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
