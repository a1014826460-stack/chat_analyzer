from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateTimeEdit,
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


LEFT_SECTION_MIN_WIDTH = 360
LEFT_SECTION_MAX_WIDTH = 440
LEFT_SECTION_MIN_HEIGHT = 150
LEFT_CONTROL_MIN_HEIGHT = 34
LEFT_TEXT_MIN_HEIGHT = 110


class MainWindowLayoutMixin:
    def _configure_left_section(self, widget: QWidget, min_height: int = LEFT_SECTION_MIN_HEIGHT) -> None:
        widget.setMinimumWidth(LEFT_SECTION_MIN_WIDTH)
        widget.setMaximumWidth(LEFT_SECTION_MAX_WIDTH)
        widget.setMinimumHeight(min_height)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def _configure_left_control(
        self,
        widget: QWidget,
        *,
        max_width: int = 210,
        min_height: int = LEFT_CONTROL_MIN_HEIGHT,
        vertical_policy: QSizePolicy.Policy = QSizePolicy.Fixed,
    ) -> None:
        widget.setMaximumWidth(max_width)
        widget.setMinimumHeight(min_height)
        widget.setSizePolicy(QSizePolicy.Preferred, vertical_policy)

    def _configure_left_expanding_control(
        self,
        widget: QWidget,
        *,
        min_height: int,
    ) -> None:
        widget.setMinimumWidth(LEFT_SECTION_MIN_WIDTH)
        widget.setMaximumWidth(LEFT_SECTION_MAX_WIDTH)
        widget.setMinimumHeight(min_height)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def _build_analysis_page(self) -> None:
        outer = QHBoxLayout(self.analysis_page)
        outer.setContentsMargins(0, 0, 0, 0)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setHandleWidth(4)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setStyleSheet(
            f"QSplitter::handle {{ background: {THEME['border']}; }}"
        )
        outer.addWidget(self.main_splitter)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setMinimumWidth(180)
        left_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        left_container = QWidget()
        left_scroll.setWidget(left_container)
        left = QVBoxLayout(left_container)
        left.setSpacing(10)
        self.main_splitter.addWidget(left_scroll)

        site_frame = QFrame()
        site_frame.setObjectName("siteFrame")
        self._configure_left_section(site_frame)
        site_layout = QVBoxLayout(site_frame)
        site_layout.setContentsMargins(10, 10, 10, 8)
        site_layout.setSpacing(6)
        site_title = QLabel("线路选择")
        site_title.setObjectName("headingLabel")
        site_layout.addWidget(site_title)
        self.site_cards_layout = QGridLayout()
        site_layout.addLayout(self.site_cards_layout)
        self.site_status_label = QLabel("正在加载线路数据...")
        site_layout.addWidget(self.site_status_label)
        left.addWidget(site_frame)

        account_box = QGroupBox("账号与数据源")
        account_layout = QGridLayout(account_box)
        account_layout.setColumnStretch(1, 1)
        account_layout.setColumnMinimumWidth(1, 160)
        self.username_combo = QComboBox()
        self.username_combo.setEditable(True)
        self._configure_left_control(self.username_combo, max_width=190)
        self.resolve_button = QPushButton("自动定位数据库")
        self._configure_left_control(self.resolve_button, max_width=120)
        self.resolve_button.clicked.connect(self._resolve_database)
        self.resolved_path_edit = QLineEdit()
        self.resolved_path_edit.setPlaceholderText("自动解析或手动选择的数据源路径")
        self._configure_left_control(self.resolved_path_edit)
        self.db_status_label = QLabel("输入用户名后可自动定位本地聊天数据库，也可手动选择数据源。")
        self.db_status_label.setWordWrap(True)
        account_layout.addWidget(QLabel("用户名"), 0, 0)
        account_layout.addWidget(self.username_combo, 0, 1)
        account_layout.addWidget(self.resolve_button, 0, 2)
        account_layout.addWidget(QLabel("当前数据源"), 1, 0)
        account_layout.addWidget(self.resolved_path_edit, 1, 1, 1, 2)
        account_layout.addWidget(self.db_status_label, 2, 0, 1, 3)
        left.addWidget(account_box)
        self._configure_left_section(account_box)

        self.fallback_box = QGroupBox("手动数据源")
        fallback_layout = QGridLayout(self.fallback_box)
        fallback_layout.setColumnStretch(1, 1)
        fallback_layout.setColumnMinimumWidth(1, 160)
        self.manual_db_edit = QLineEdit()
        self.manual_db_edit.setPlaceholderText("自动定位失败时选择 msg_0.db / sqlite / txt")
        self._configure_left_control(self.manual_db_edit)
        browse_manual_btn = QPushButton("浏览")
        self._configure_left_control(browse_manual_btn, max_width=70)
        browse_manual_btn.clicked.connect(self._pick_manual_data_source)
        use_manual_btn = QPushButton("使用数据源")
        self._configure_left_control(use_manual_btn, max_width=100)
        use_manual_btn.clicked.connect(self._load_manual_data_source)
        fallback_layout.addWidget(QLabel("文件"), 0, 0)
        fallback_layout.addWidget(self.manual_db_edit, 0, 1)
        fallback_layout.addWidget(browse_manual_btn, 0, 2)
        fallback_layout.addWidget(use_manual_btn, 1, 2)
        left.addWidget(self.fallback_box)
        self._configure_left_section(self.fallback_box)

        filter_box = QGroupBox("筛选条件")
        filter_layout = QVBoxLayout(filter_box)
        self.advanced_time_toggle = QPushButton("+ 高级时间筛选")
        self.advanced_time_toggle.setObjectName("toggleBtn")
        self.advanced_time_toggle.clicked.connect(self._toggle_advanced_time)
        filter_layout.addWidget(self.advanced_time_toggle)
        self.advanced_time_frame = QFrame()
        self.advanced_time_frame.setVisible(False)
        time_row = QGridLayout(self.advanced_time_frame)
        time_row.setColumnStretch(1, 1)
        time_row.setColumnStretch(3, 1)
        self.start_edit = QDateTimeEdit()
        self.end_edit = QDateTimeEdit()
        for widget in (self.start_edit, self.end_edit):
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        time_row.addWidget(QLabel("开始时间"), 0, 0)
        time_row.addWidget(self.start_edit, 0, 1)
        time_row.addWidget(QLabel("结束时间"), 0, 2)
        time_row.addWidget(self.end_edit, 0, 3)
        self.time_active_label = QLabel("展开后将按此时间范围读取消息。")
        self.time_active_label.setObjectName("emphasisLabel")
        time_row.addWidget(self.time_active_label, 1, 0, 1, 4)
        filter_layout.addWidget(self.advanced_time_frame)
        self.group_list = QListWidget()
        self._configure_left_expanding_control(
            self.group_list,
            min_height=140,
        )
        self.group_list.itemChanged.connect(self._handle_group_item_changed)
        filter_layout.addWidget(self.group_list)
        group_bar = QHBoxLayout()
        all_btn = QPushButton("全选")
        all_btn.clicked.connect(lambda: self._set_checked_state(self.group_list, True))
        invert_btn = QPushButton("反选")
        invert_btn.clicked.connect(lambda: self._invert_checked_state(self.group_list))
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(lambda: self._set_checked_state(self.group_list, False))
        group_bar.addWidget(all_btn)
        group_bar.addWidget(invert_btn)
        group_bar.addWidget(clear_btn)
        group_bar.addStretch(1)
        filter_layout.addLayout(group_bar)
        left.addWidget(filter_box)
        self._configure_left_section(filter_box)

        block_box = QGroupBox("屏蔽名单")
        block_layout = QVBoxLayout(block_box)
        global_row = QHBoxLayout()
        global_row.addWidget(QLabel("全局"))
        block_layout.addLayout(global_row)
        self.global_block_names_edit = QTextEdit()
        self.global_block_names_edit.setPlaceholderText("全局屏蔽名称，每行一个，也可用逗号/分号分隔")
        self._configure_left_expanding_control(
            self.global_block_names_edit,
            min_height=LEFT_TEXT_MIN_HEIGHT,
        )
        block_layout.addWidget(self.global_block_names_edit)
        global_btn_row = QHBoxLayout()
        self.global_block_save_btn = QPushButton("保存全局")
        self.global_block_save_btn.clicked.connect(self._apply_global_block_names_from_editor)
        self.global_block_clear_btn = QPushButton("清空全局")
        self.global_block_clear_btn.clicked.connect(self._clear_global_block_names)
        global_btn_row.addWidget(self.global_block_save_btn)
        global_btn_row.addWidget(self.global_block_clear_btn)
        global_btn_row.addStretch(1)
        block_layout.addLayout(global_btn_row)
        chooser_row = QHBoxLayout()
        chooser_row.addWidget(QLabel("群组"))
        self.block_group_combo = QComboBox()
        self.block_group_combo.currentIndexChanged.connect(self._on_block_group_changed)
        chooser_row.addWidget(self.block_group_combo, 1)
        block_layout.addLayout(chooser_row)
        self.block_names_edit = QTextEdit()
        self.block_names_edit.setPlaceholderText("每行一个名称，也可用逗号/分号分隔")
        self._configure_left_expanding_control(
            self.block_names_edit,
            min_height=LEFT_TEXT_MIN_HEIGHT,
        )
        block_layout.addWidget(self.block_names_edit)
        btn_row = QHBoxLayout()
        self.block_rule_save_btn = QPushButton("保存")
        self.block_rule_save_btn.clicked.connect(self._apply_block_rule_from_editor)
        self.block_rule_clear_btn = QPushButton("清空")
        self.block_rule_clear_btn.clicked.connect(self._clear_block_rule_for_selected_group)
        btn_row.addWidget(self.block_rule_save_btn)
        btn_row.addWidget(self.block_rule_clear_btn)
        btn_row.addStretch(1)
        block_layout.addLayout(btn_row)
        self.block_rule_status_label = QLabel("请选择一个群组。")
        block_layout.addWidget(self.block_rule_status_label)
        self.block_rule_summary_view = QTextEdit()
        self.block_rule_summary_view.setReadOnly(True)
        self._configure_left_expanding_control(
            self.block_rule_summary_view,
            min_height=120,
        )
        block_layout.addWidget(self.block_rule_summary_view)
        left.addWidget(block_box)
        self._configure_left_section(block_box)

        action_box = QGroupBox("状态")
        action_layout = QVBoxLayout(action_box)
        self.status_title = QLabel("当前状态")
        self.status_title.setObjectName("headingLabel")
        self.status_label = QLabel("请选择线路并加载聊天记录。")
        self.status_label.setWordWrap(True)
        action_layout.addWidget(self.status_title)
        action_layout.addWidget(self.status_label)
        left.addWidget(action_box)
        self._configure_left_section(action_box)

        right_container = QWidget()
        right_container.setMinimumWidth(360)
        right_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right = QVBoxLayout(right_container)
        self.main_splitter.addWidget(right_container)

        info_frame = QFrame()
        info_frame.setObjectName("statsFrame")
        info_layout = QVBoxLayout(info_frame)
        site_bar = QHBoxLayout()
        site_bar.addWidget(QLabel("线路:"))
        self.active_site_label = QLabel("-")
        site_bar.addWidget(self.active_site_label)
        site_bar.addWidget(QLabel("当前期数:"))
        self.active_period_label = QLabel("-")
        site_bar.addWidget(self.active_period_label)
        site_bar.addWidget(QLabel("下一期数:"))
        self.next_period_label = QLabel("-")
        site_bar.addWidget(self.next_period_label)
        site_bar.addWidget(QLabel("查询期数:"))
        self.period_input = QLineEdit()
        self.period_input.setPlaceholderText("默认跟随下一期")
        self.period_input.editingFinished.connect(self._on_period_input_changed)
        site_bar.addWidget(self.period_input)
        site_bar.addWidget(QLabel("倒计时:"))
        self.countdown_label = QLabel("--:--")
        site_bar.addWidget(self.countdown_label)
        site_bar.addStretch(1)
        site_bar.addWidget(QLabel("锁定阈值(秒):"))
        self.lock_threshold_spin = QSpinBox()
        self.lock_threshold_spin.setRange(5, 300)
        self.lock_threshold_spin.setValue(self._lock_threshold_sec)
        self.lock_threshold_spin.valueChanged.connect(self._on_lock_threshold_changed)
        site_bar.addWidget(self.lock_threshold_spin)
        self.auto_refresh_label = QLabel("待机")
        site_bar.addWidget(self.auto_refresh_label)
        info_layout.addLayout(site_bar)

        self.lock_status_label = QLabel("")
        info_layout.addWidget(self.lock_status_label)

        self.chart_window = ChartWindow(parent=self)
        self.chart_window.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        info_layout.addWidget(self.chart_window, 1)
        right.addWidget(info_frame, 1)

        raw_chat_row = QHBoxLayout()
        self.raw_chat_button = QPushButton("原始聊天记录")
        self.raw_chat_button.clicked.connect(getattr(self, "_open_raw_chat_dialog", lambda: None))
        raw_chat_row.addWidget(self.raw_chat_button)
        self.summary_check_button = QPushButton("机器人汇总校验结果")
        self.summary_check_button.clicked.connect(getattr(self, "_open_summary_check_dialog", lambda: None))
        raw_chat_row.addWidget(self.summary_check_button)
        self.unresolved_receipt_button = QPushButton("未归属回执诊断")
        self.unresolved_receipt_button.clicked.connect(getattr(self, "_open_unresolved_receipt_dialog", lambda: None))
        raw_chat_row.addWidget(self.unresolved_receipt_button)
        raw_chat_row.addStretch(1)
        right.addLayout(raw_chat_row)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
