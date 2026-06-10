from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.ui.chart_window import ChartWindow
from app.ui.main_window_theme import THEME


class MainWindowLayoutMixin:
    def _build_analysis_page(self) -> None:
        outer = QHBoxLayout(self.analysis_page)
        outer.setContentsMargins(0, 0, 0, 0)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setHandleWidth(4)
        self.main_splitter.setStyleSheet(
            f"QSplitter::handle {{ background: {THEME['border']}; }}"
        )
        outer.addWidget(self.main_splitter)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_container = QWidget()
        left_scroll.setWidget(left_container)
        left = QVBoxLayout(left_container)
        left.setSpacing(10)
        self.main_splitter.addWidget(left_scroll)

        site_frame = QFrame()
        site_frame.setObjectName("siteFrame")
        site_layout = QVBoxLayout(site_frame)
        site_title = QLabel("Sites")
        site_title.setObjectName("headingLabel")
        site_layout.addWidget(site_title)
        self.site_cards_layout = QGridLayout()
        site_layout.addLayout(self.site_cards_layout)
        self.site_status_label = QLabel("Loading site cards...")
        site_layout.addWidget(self.site_status_label)
        left.addWidget(site_frame)

        account_box = QGroupBox("Account and Data Source")
        account_layout = QGridLayout(account_box)
        account_layout.setColumnStretch(1, 1)
        self.username_combo = QComboBox()
        self.username_combo.setEditable(True)
        self.resolve_button = QPushButton("Resolve database")
        self.resolve_button.clicked.connect(self._resolve_database)
        self.resolved_path_edit = QLineEdit()
        self.resolved_path_edit.setPlaceholderText("Resolved or manual data source path")
        self.db_status_label = QLabel("Resolve a database or choose a manual source.")
        self.db_status_label.setWordWrap(True)
        account_layout.addWidget(QLabel("Username"), 0, 0)
        account_layout.addWidget(self.username_combo, 0, 1)
        account_layout.addWidget(self.resolve_button, 0, 2)
        account_layout.addWidget(QLabel("Current source"), 1, 0)
        account_layout.addWidget(self.resolved_path_edit, 1, 1, 1, 2)
        account_layout.addWidget(self.db_status_label, 2, 0, 1, 3)
        left.addWidget(account_box)

        self.fallback_box = QGroupBox("Manual Source")
        fallback_layout = QGridLayout(self.fallback_box)
        self.manual_db_edit = QLineEdit()
        browse_manual_btn = QPushButton("Browse")
        browse_manual_btn.clicked.connect(self._pick_manual_data_source)
        use_manual_btn = QPushButton("Use source")
        use_manual_btn.clicked.connect(self._load_manual_data_source)
        fallback_layout.addWidget(QLabel("File"), 0, 0)
        fallback_layout.addWidget(self.manual_db_edit, 0, 1)
        fallback_layout.addWidget(browse_manual_btn, 0, 2)
        fallback_layout.addWidget(use_manual_btn, 1, 2)
        left.addWidget(self.fallback_box)

        filter_box = QGroupBox("Filters")
        filter_layout = QVBoxLayout(filter_box)
        self.advanced_time_toggle = QPushButton("Advanced time filter")
        self.advanced_time_toggle.clicked.connect(self._toggle_advanced_time)
        filter_layout.addWidget(self.advanced_time_toggle)
        self.group_list = QListWidget()
        self.group_list.itemChanged.connect(self._handle_group_item_changed)
        filter_layout.addWidget(self.group_list)
        group_bar = QHBoxLayout()
        all_btn = QPushButton("All")
        all_btn.clicked.connect(lambda: self._set_checked_state(self.group_list, True))
        invert_btn = QPushButton("Invert")
        invert_btn.clicked.connect(lambda: self._invert_checked_state(self.group_list))
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(lambda: self._set_checked_state(self.group_list, False))
        group_bar.addWidget(all_btn)
        group_bar.addWidget(invert_btn)
        group_bar.addWidget(clear_btn)
        group_bar.addStretch(1)
        filter_layout.addLayout(group_bar)
        left.addWidget(filter_box)

        block_box = QGroupBox("Blocked Names")
        block_layout = QVBoxLayout(block_box)
        chooser_row = QHBoxLayout()
        chooser_row.addWidget(QLabel("Group"))
        self.block_group_combo = QComboBox()
        self.block_group_combo.currentIndexChanged.connect(self._on_block_group_changed)
        chooser_row.addWidget(self.block_group_combo, 1)
        block_layout.addLayout(chooser_row)
        self.block_names_edit = QTextEdit()
        self.block_names_edit.setPlaceholderText("One name per line")
        block_layout.addWidget(self.block_names_edit)
        btn_row = QHBoxLayout()
        self.block_rule_save_btn = QPushButton("Save")
        self.block_rule_save_btn.clicked.connect(self._apply_block_rule_from_editor)
        self.block_rule_clear_btn = QPushButton("Clear")
        self.block_rule_clear_btn.clicked.connect(self._clear_block_rule_for_selected_group)
        btn_row.addWidget(self.block_rule_save_btn)
        btn_row.addWidget(self.block_rule_clear_btn)
        btn_row.addStretch(1)
        block_layout.addLayout(btn_row)
        self.block_rule_status_label = QLabel("No group selected.")
        block_layout.addWidget(self.block_rule_status_label)
        self.block_rule_summary_view = QTextEdit()
        self.block_rule_summary_view.setReadOnly(True)
        self.block_rule_summary_view.setMinimumHeight(120)
        block_layout.addWidget(self.block_rule_summary_view)
        left.addWidget(block_box)

        action_box = QGroupBox("Status")
        action_layout = QVBoxLayout(action_box)
        self.status_title = QLabel("Current Status")
        self.status_title.setObjectName("headingLabel")
        self.status_label = QLabel("Choose a site and load messages.")
        self.status_label.setWordWrap(True)
        action_layout.addWidget(self.status_title)
        action_layout.addWidget(self.status_label)
        left.addWidget(action_box)

        right_container = QWidget()
        right = QVBoxLayout(right_container)
        self.main_splitter.addWidget(right_container)

        info_frame = QFrame()
        info_frame.setObjectName("statsFrame")
        info_layout = QVBoxLayout(info_frame)
        site_bar = QHBoxLayout()
        site_bar.addWidget(QLabel("Site:"))
        self.active_site_label = QLabel("-")
        site_bar.addWidget(self.active_site_label)
        site_bar.addWidget(QLabel("Current period:"))
        self.active_period_label = QLabel("-")
        site_bar.addWidget(self.active_period_label)
        site_bar.addWidget(QLabel("Next period:"))
        self.next_period_label = QLabel("-")
        site_bar.addWidget(self.next_period_label)
        site_bar.addWidget(QLabel("Query period:"))
        self.period_input = QLineEdit()
        self.period_input.setPlaceholderText("Optional period override")
        self.period_input.editingFinished.connect(self._on_period_input_changed)
        site_bar.addWidget(self.period_input)
        site_bar.addWidget(QLabel("Countdown:"))
        self.countdown_label = QLabel("--:--")
        site_bar.addWidget(self.countdown_label)
        site_bar.addStretch(1)
        site_bar.addWidget(QLabel("Lock threshold (s):"))
        self.lock_threshold_spin = QSpinBox()
        self.lock_threshold_spin.setRange(5, 300)
        self.lock_threshold_spin.setValue(self._lock_threshold_sec)
        self.lock_threshold_spin.valueChanged.connect(self._on_lock_threshold_changed)
        site_bar.addWidget(self.lock_threshold_spin)
        self.auto_refresh_label = QLabel("Idle")
        site_bar.addWidget(self.auto_refresh_label)
        info_layout.addLayout(site_bar)

        self.lock_status_label = QLabel("")
        info_layout.addWidget(self.lock_status_label)

        self.chart_window = ChartWindow(parent=self)
        self.chart_window.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        info_layout.addWidget(self.chart_window, 1)
        right.addWidget(info_frame, 1)

        message_frame = QFrame()
        message_layout = QVBoxLayout(message_frame)
        self.result_view = QTextEdit()
        self.result_view.setReadOnly(True)
        message_layout.addWidget(self.result_view, 1)
        pager = QHBoxLayout()
        prev_btn = QPushButton("Prev")
        prev_btn.clicked.connect(self._prev_page)
        next_btn = QPushButton("Next")
        next_btn.clicked.connect(self._next_page)
        self.page_label = QLabel("Page 1 / 1")
        pager.addWidget(prev_btn)
        pager.addWidget(next_btn)
        pager.addWidget(self.page_label)
        pager.addStretch(1)
        message_layout.addLayout(pager)
        right.addWidget(message_frame, 1)
