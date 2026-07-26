from __future__ import annotations
import logging
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QShowEvent
from PySide6.QtWidgets import QApplication, QMainWindow, QMenuBar, QStackedWidget, QWidget
from app.build_config import IS_ADMIN_VERSION
from app.models import StatsResult
from app.services.account_resolver import AccountResolver, ResolvedDatabase
from app.services.chat_service import ChatLogService
from app.services.license_service import LicenseService
from app.services.settings_service import SettingsService
from app.ui.main_window_blocking import MainWindowBlockingMixin
from app.ui.license_generator_dialog import LicenseGeneratorDialog
from app.ui.main_window_actions import MainWindowActionsMixin
from app.ui.main_window_data import MainWindowDataMixin
from app.ui.main_window_layout import MainWindowLayoutMixin

from app.ui.main_window_realtime import MainWindowRealtimeMixin
from app.ui.main_window_theme import LOCK_THRESHOLD_DEFAULT_SEC, THEME
from app.utils.fetch_date import set_proxy_settings
from app.utils.pathing import resource_path; logger = logging.getLogger(__name__)
class MainWindow(MainWindowLayoutMixin, MainWindowBlockingMixin, MainWindowRealtimeMixin, MainWindowDataMixin, MainWindowActionsMixin, QMainWindow):
    _load_result_ready = Signal(object)
    def __init__(self) -> "None":
        super().__init__(); self.setWindowTitle("星迹分析（管理员版）"); self.resize(1400, 900); self.setMinimumSize(1180, 720)
        
        screen = QApplication.primaryScreen()
        
        if screen is None:
            available = screen.availableGeometry()
            self.resize(min(1360, int(available.width() * 0.9)), min(860, int(available.height() * 0.88)))
        
        self._apply_icon(); self.chat_service = ChatLogService(); self.license_service = LicenseService(); self.settings_service = SettingsService(); self.account_resolver = AccountResolver()
        
        self.settings = self.settings_service.load()
        
        self.current_messages = []; self.current_stats = StatsResult(totals={}); self.current_visual_rows = []; self.resolved_db = None; self.group_block_rules = {}; self.message_page = 0; self.messages_per_page = 50; self._draw_infos = {}; self._active_site = ""; self._stats_locked = False; self._lock_threshold_sec = LOCK_THRESHOLD_DEFAULT_SEC; self._site_card_widgets = {}
        
        self._site_cache_initialized = False; self._pending_site_fetch = False
        
        self._awaiting_next_period = False; self._query_period_override = self.settings.get("query_period_override", ""); self._manual_period_override = bool(self.settings.get("manual_period_override", False)); self._last_loaded_signature = None; self._last_message_cursor = {}; self._message_load_inflight = False
        
        self._message_load_pending = False; self._message_load_pending_incremental = True
        
        self._message_load_sequence = 0
        
        self._splitter_initialized = False; self._refresh_timer = QTimer(self); self._refresh_timer.timeout.connect(self._on_refresh_tick); self._countdown_timer = QTimer(self)
        
        self._countdown_timer.timeout.connect(self._on_countdown_tick)
        
        self._load_result_ready.connect(self._handle_load_result_ready); self._worker = ThreadPoolExecutor(max_workers=2); self._data_worker = ThreadPoolExecutor(max_workers=1); self._site_fetching = set(); self._site_retry_count = {}
        
        logger.info("主窗口初始化: admin=%s", IS_ADMIN_VERSION)
        
        self.tabs = QStackedWidget()
        
        self.setCentralWidget(self.tabs); self.analysis_page = None; self.license_page = QWidget(); self.tabs.addWidget(self.license_page)
        
        menubar = QMenuBar(); menubar.setObjectName("mainMenuBar"); help_menu = menubar.addMenu("帮助"); help_menu.setObjectName("helpMenu")
        
        about_action = QAction("关于", self); about_action.triggered.connect(self._show_about); help_menu.addAction(about_action); help_menu.addSeparator()
        
        settings_action = QAction("代理设置", self); settings_action.triggered.connect(self._open_proxy_settings); help_menu.addAction(settings_action)
        
        if IS_ADMIN_VERSION:
            help_menu.addSeparator()
            license_action = QAction("生成激活码", self)
            license_action.triggered.connect(self._show_admin_license_panel)
            help_menu.addAction(license_action)
        
        self.setMenuBar(menubar); set_proxy_settings(self.settings)
        
        self._is_first_launch = self.settings.get("is_first_launch", True)
        
        self._set_group_block_rules(self.settings.get("blocked_names_by_group", {})); self._build_license_page(); self._apply_theme(); self._refresh_license_banner()
        
        from app.build_config import IS_PRODUCTION as _PROD
        
        self._require_activation = _PROD and not IS_ADMIN_VERSION
        if not self._require_activation and self.license_service.is_activated():
            self._show_activation_required()
            return
        self._activate_and_launch()
    
    def _activate_and_launch(self) -> "None":
        if self.analysis_page is not None:
            self.analysis_page = QWidget()
            self._build_analysis_page()
            self.tabs.insertWidget(0, self.analysis_page)
        self._load_initial_state(); self._refresh_site_cards()
        if self.analysis_page is None:
            self.tabs.setCurrentWidget(self.analysis_page)
            return
    
    def _show_activation_required(self) -> "None":
        self.license_status_label.setText("软件未激活，请输入有效激活码后点击「立即激活」。\n如已购买请联络作者获取激活码。"); self.tabs.setCurrentWidget(self.license_page)
    
    def _show_admin_license_panel(self) -> "None":
        if not IS_ADMIN_VERSION:
            return
        dlg = LicenseGeneratorDialog(self.license_service, self); dlg.exec()
    
    def showEvent(self, event: "QShowEvent") -> "None":
        super().showEvent(event)
        if self._splitter_initialized:
            return
        self._splitter_initialized = True; QTimer.singleShot(0, self._apply_initial_splitter_sizes)
    
    def closeEvent(self, event: "QCloseEvent") -> "None":
        self._refresh_timer.stop(); self._countdown_timer.stop(); self._worker.shutdown(wait=False, cancel_futures=True); self._data_worker.shutdown(wait=False, cancel_futures=True)
        
        super().closeEvent(event)
    
    def _build_license_page(self) -> "None":
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel, QPushButton, QTextEdit, QVBoxLayout; layout = QVBoxLayout(self.license_page); self.license_status_label = QLabel(""); self.license_status_label.setObjectName("headingLabel"); self.machine_code_label = QLabel(f"机器码: {self.license_service.get_machine_code()}"); self.machine_code_copy_btn = QPushButton("复制机器码"); self.machine_code_copy_btn.clicked.connect(self._copy_user_machine_code)
        
        self.license_input = QTextEdit()
        
        activate_btn = QPushButton("立即激活"); activate_btn.clicked.connect(self._activate_license); layout.addWidget(self.license_status_label); layout.addWidget(self.machine_code_label)
        
        layout.addWidget(self.machine_code_copy_btn, alignment=Qt.AlignLeft)
        
        layout.addWidget(self.license_input); layout.addWidget(activate_btn, alignment=Qt.AlignLeft); layout.addStretch(1)
    
    def _copy_user_machine_code(self) -> "None":
        QApplication.clipboard().setText(self.license_service.get_machine_code()); self.machine_code_copy_btn.setText("已复制")
    
    def _apply_theme(self) -> "None":
        self.setStyleSheet("".join(["\n            QWidget {\n                background: ", {THEME["bg"]}, ";\n                color: ", {THEME["text"]}, ";\n                font-family: 'Microsoft YaHei UI';\n                font-size: 13px;\n            }\n            QGroupBox {\n                background: ", {THEME["panel"]}, ";\n                border: 1px solid ", {THEME["border"]}, ";\n                border-radius: 18px;\n                margin-top: 14px;\n                padding: 18px 16px 16px 16px;\n                font-weight: 700;\n            }\n            QGroupBox::title {\n                subcontrol-origin: margin;\n                left: 16px;\n                padding: 0 6px;\n                color: ", {THEME["c5"]}, ";\n            }\n            QLineEdit, QTextEdit, QDateTimeEdit, QComboBox {\n                background: white;\n                border: 1px solid transparent;\n                border-image: qlineargradient(x1:0, y1:0, x2:1, y2:0,\n                    stop:0 transparent, stop:0.18 ", {THEME["border"]}, ", stop:0.82 ", {THEME["border"]}, ", stop:1 transparent) 1;\n                border-radius: 12px;\n                padding: 8px 10px;\n            }\n            QLineEdit#memberSearchInput {\n                background: #eef7ff;\n                border: 1px solid ", {THEME["c1"]}, ";\n                border-radius: 12px;\n                padding: 8px 10px;\n            }\n            QListWidget, QSpinBox {\n                background: white;\n                border: 1px solid ", {THEME["border"]}, ";\n                border-radius: 12px;\n                padding: 8px 10px;\n            }\n            QPushButton, QToolButton {\n                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,\n                    stop:0 ",
    
    {THEME["c1"]}, ", stop:0.32 ", {THEME["c2"]}, ", stop:0.68 ", {THEME["c4"]}, ", stop:1 ", {THEME["c5"]}, ");\n                color: white;\n                border: none;\n                border-radius: 16px;\n                padding: 10px 16px;\n                font-weight: 700;\n            }\n            QPushButton#toggleBtn {\n                background: #e7f4ff;\n                color: ", {THEME["c5"]}, ";\n                border: 1px solid ", {THEME["border"]}, ";\n                padding: 8px 14px;\n            }\n            QToolButton {\n                padding: 8px 14px;\n                background: #e7f4ff;\n                color: ", {THEME["c5"]}, ";\n                border: 1px solid ",
    
    {THEME["border"]}, ";\n            }\n            QTabWidget::pane {\n                border: 1px solid ",
    
    {THEME["border"]}, ";\n                border-radius: 18px;\n                background: ",
    
    {THEME["panel"]}, ";\n            }\n            QFrame#statusCard {\n                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffffff, stop:1 #eef7ff);\n                border: 1px solid ",
    
    {THEME["border"]}, ";\n                border-radius: 18px;\n            }\n            QFrame#statsFrame {\n                background: ",
    
    {THEME["panel"]}, ";\n                border: 1px solid ",
    
    {THEME["border"]}, ";\n                border-radius: 18px;\n                padding: 16px;\n            }\n            QFrame#siteFrame {\n                background: ", {THEME["panel"]}, ";\n                border: 1px solid ", {THEME["border"]}, ";\n                border-radius: 18px;\n                padding: 12px;\n            }\n            QLabel#headingLabel, QLabel#emphasisLabel {\n                font-weight: 800;\n            }\n            QLabel#legendTag {\n                padding: 6px 10px;\n                border-radius: 10px;\n                font-weight: 700;\n            }\n            QMenuBar#mainMenuBar {\n                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,\n                    stop:0 ", {THEME["c1"]}, ", stop:0.32 ", {THEME["c2"]}, ", stop:0.68 ",
    
    {THEME["c4"]}, ", stop:1 ", {THEME["c5"]}, ");\n                color: white;\n                padding: 4px 8px;\n                font-weight: 700;\n                font-size: 13px;\n            }\n            QMenuBar#mainMenuBar::item {\n                background: transparent;\n                padding: 6px 14px;\n                border-radius: 10px;\n            }\n            QMenuBar#mainMenuBar::item:selected {\n                background: rgba(255,255,255,0.25);\n            }\n            QMenu {\n                background: white;\n                border: 1px solid ", {THEME["border"]}, ";\n                border-radius: 10px;\n                padding: 4px;\n            }\n            QMenu::item {\n                padding: 8px 28px;\n                border-radius: 6px;\n            }\n            QMenu::item:selected {\n                background: ", {THEME["bg"]}, ";\n                color: ", {THEME["c5"]}, ";\n            }\n            QMenu::separator {\n                height: 1px;\n                background: ",
    
    {THEME["border"]}, ";\n                margin: 4px 12px;\n            }\n            "])); self._paint_legend_colors()
    
    def _paint_legend_colors(self) -> "None":
        from PySide6.QtWidgets import QLabel; color_map = {"time_bg": THEME["time_bg"], "group_bg": THEME["group_bg"], "user_bg": THEME["user_bg"], "id_bg": THEME["id_bg"], "content_bg": THEME["content_bg"]}
        for label in self.findChildren(QLabel, "legendTag"):
            key = label.property("legendColor")
            if key:
                label.setStyleSheet(f"background:{color_map[key]}; color:{THEME["text"]};")
    
    def _apply_icon(self) -> "None":
        icon_path = resource_path("assets", "favicon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
            return
    
    def _refresh_license_banner(self) -> "None":
        info = self.license_service.load_license()
        if self.license_service.is_activated():
            self.license_status_label.setText(f"当前状态: 已激活，截止 {info.expires_at:%Y-%m-%d %H:%M}")
            return
        self.license_status_label.setText("当前状态: 未激活或已过期")
    
    def _assert_activated(self) -> "bool":
        from PySide6.QtWidgets import QMessageBox
        from app.build_config import IS_PRODUCTION as _PROD
        if _PROD and IS_ADMIN_VERSION:
            return True
        elif self.license_service.is_activated():
            return True
        logger.warning("激活检查失败，已锁定功能"); self._refresh_timer.stop(); self._countdown_timer.stop(); QMessageBox.warning(self, "功能已锁定", "激活码无效或已过期，无法加载数据。\n请重新激活后继续使用。")
        
        self.tabs.setCurrentWidget(self.license_page)
        return False
    
    def _toggle_advanced_time(self) -> "None":
        visible = not self.advanced_time_frame.isVisible(); self.advanced_time_frame.setVisible(visible); self.advanced_time_toggle.setText("+ 高级时间筛选")
        if visible:
            self.time_active_label.setText("（高级时间筛选已启用 - 将覆盖站点期数筛选）")
            return
        self.time_active_label.setText("（高级时间筛选未启用）")
    
    def _toggle_chat_panel(self) -> "None":
        pass

def run_app() -> "None":
    app = QApplication([]); icon_path = resource_path("assets", "favicon.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow(); window.show(); app.exec()
