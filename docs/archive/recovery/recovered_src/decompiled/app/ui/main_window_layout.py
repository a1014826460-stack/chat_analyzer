from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDateTimeEdit, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QScrollArea, QSizePolicy, QSplitter, QSpinBox, QTextEdit, QVBoxLayout, QWidget
from app.ui.chart_window import ChartWindow
from app.ui.main_window_theme import THEME

class MainWindowLayoutMixin:
    def _build_analysis_page(self) -> "None":
        outer = QHBoxLayout(self.analysis_page); outer.setContentsMargins(0, 0, 0, 0); splitter = QSplitter(Qt.Horizontal); self.main_splitter = splitter; splitter.setHandleWidth(4)
        
        splitter.setStyleSheet(f"QSplitter::handle { background: {THEME["border"]}; }")
        
        left_scroll = QScrollArea(); left_scroll.setWidgetResizable(True); left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        left_scroll.setFrameShape(QFrame.NoFrame); left_scroll.setStyleSheet("QScrollArea { border: none; }"); self.left_scroll = left_scroll; left_container = QWidget(); self.left_panel_container = left_container; left = QVBoxLayout(left_container); left.setSpacing(10)
        
        site_frame = QFrame()
        
        site_frame.setObjectName("siteFrame"); site_layout = QVBoxLayout(site_frame); site_title = QLabel("选择站点（点击对应卡片即可按该站点期数筛选）"); site_title.setObjectName("headingLabel"); site_layout.addWidget(site_title); self.site_cards_layout = QGridLayout()
        
        self.site_cards_layout.setSpacing(8)
        
        site_layout.addLayout(self.site_cards_layout); self.site_status_label = QLabel("站点数据加载中..."); self.site_status_label.setObjectName("emphasisLabel"); site_layout.addWidget(self.site_status_label); left.addWidget(site_frame)
        
        account_box = QGroupBox("账号与数据库")
        
        account_layout = QGridLayout(account_box); account_layout.setColumnStretch(1, 1); self.username_combo = QComboBox(); self.username_combo.setEditable(True)
        
        self.username_combo.setInsertPolicy(QComboBox.NoInsert); self.resolve_button = QPushButton("自动定位数据库")
        
        self.resolve_button.clicked.connect(self._resolve_database); self.resolved_path_edit = QLineEdit(); self.resolved_path_edit.setPlaceholderText("可手动输入 msg_0.db 或 txt 数据源路径"); self.db_status_label = QLabel("输入用户名后，将优先自动解析本地聊天数据库。")
        
        self.db_status_label.setWordWrap(True); self.db_status_label.setObjectName("emphasisLabel"); account_layout.addWidget(QLabel("用户名"), 0, 0)
        
        account_layout.addWidget(self.username_combo, 0, 1); account_layout.addWidget(self.resolve_button, 0, 2); account_layout.addWidget(QLabel("当前数据库"), 2, 0)
        
        account_layout.addWidget(self.resolved_path_edit, 2, 1, 1, 2)
        
        account_layout.addWidget(self.db_status_label, 3, 0, 1, 3); left.addWidget(account_box); self.fallback_box = QGroupBox("数据源"); fallback_layout = QGridLayout(self.fallback_box); fallback_layout.setColumnStretch(1, 1)
        
        self.fallback_box.setVisible(False)
        
        self.manual_db_edit = QLineEdit(); self.manual_db_edit.setPlaceholderText("仅在自动解析失败时使用"); browse_manual_btn = QPushButton("选择数据源"); browse_manual_btn.clicked.connect(self._pick_manual_data_source)
        
        use_manual_btn = QPushButton("使用手动数据源"); use_manual_btn.clicked.connect(self._load_manual_data_source)
        
        fallback_layout.addWidget(QLabel("备用路径"), 0, 0); fallback_layout.addWidget(self.manual_db_edit, 0, 1); fallback_layout.addWidget(browse_manual_btn, 0, 2); fallback_layout.addWidget(use_manual_btn, 1, 2); left.addWidget(self.fallback_box)
        
        filter_box = QGroupBox("筛选条件")
        
        filter_layout = QVBoxLayout(filter_box); self.advanced_time_toggle = QPushButton("+ 高级时间筛选"); self.advanced_time_toggle.setObjectName("toggleBtn")
        
        self.advanced_time_toggle.clicked.connect(self._toggle_advanced_time); filter_layout.addWidget(self.advanced_time_toggle); self.advanced_time_frame = QFrame(); self.advanced_time_frame.setVisible(False); time_row = QGridLayout(self.advanced_time_frame)
        
        time_row.setContentsMargins(0, 4, 0, 4)
        
        self.start_edit = QDateTimeEdit(); self.end_edit = QDateTimeEdit()
        for widget in (self.start_edit,
            self.end_edit):
            widget.setDisplayFormat("yyyy-MM-dd HH:mm")
            widget.setCalendarPopup(True)
        
        time_row.addWidget(QLabel("起始时间"), 0, 0); time_row.addWidget(self.start_edit, 0, 1); time_row.addWidget(QLabel("结束时间"), 0, 2); time_row.addWidget(self.end_edit, 0, 3)
        
        self.time_active_label = QLabel("（高级时间筛选未启用）")
        
        self.time_active_label.setObjectName("emphasisLabel"); time_row.addWidget(self.time_active_label, 1, 0, 1, 4); filter_layout.addWidget(self.advanced_time_frame); group_bar = QHBoxLayout()
        
        group_bar.addWidget(QLabel("群组多选"))
        
        group_bar.addStretch(1); group_bar.addWidget(QPushButton("全选", clicked=(lambda: self._set_checked_state(self.group_list, True)))); group_bar.addWidget(QPushButton("反选", clicked=(lambda: self._invert_checked_state(self.group_list))))
        
        group_bar.addWidget(QPushButton("清空", clicked=(lambda: self._set_checked_state(self.group_list, False)))); filter_layout.addLayout(group_bar); self.group_list = QListWidget(); self.group_list.itemChanged.connect(self._handle_group_item_changed)
        
        filter_layout.addWidget(self.group_list)
        
        left.addWidget(filter_box); block_box = QGroupBox("屏蔽名单 - 板块"); block_layout = QVBoxLayout(block_box); block_tip = QLabel("先选择一个群组，再输入需要屏蔽的下注名称。每行一个名称，或使用逗号/分号分隔。"); block_tip.setWordWrap(True); block_tip.setObjectName("emphasisLabel")
        
        block_layout.addWidget(block_tip); chooser_row = QHBoxLayout(); chooser_row.addWidget(QLabel("目标群组")); self.block_group_combo = QComboBox()
        
        self.block_group_combo.currentIndexChanged.connect(self._on_block_group_changed); chooser_row.addWidget(self.block_group_combo, 1); block_layout.addLayout(chooser_row); self.block_names_edit = QTextEdit()
        
        self.block_names_edit.setPlaceholderText("请输入需要屏蔽的下注名称，例如：\n张三\n李四\n财哥"); block_layout.addWidget(self.block_names_edit); block_btn_row = QHBoxLayout(); self.block_rule_save_btn = QPushButton("保存屏蔽项")
        
        self.block_rule_save_btn.clicked.connect(self._apply_block_rule_from_editor); self.block_rule_clear_btn = QPushButton("清空当前群组")
        
        self.block_rule_clear_btn.clicked.connect(self._clear_block_rule_for_selected_group)
        
        block_btn_row.addWidget(self.block_rule_save_btn); block_btn_row.addWidget(self.block_rule_clear_btn); block_btn_row.addStretch(1); block_layout.addLayout(block_btn_row)
        
        self.block_rule_status_label = QLabel("请先从群组列表中选择一个群组。"); self.block_rule_status_label.setWordWrap(True)
        
        block_layout.addWidget(self.block_rule_status_label); self.block_rule_summary_view = QTextEdit(); self.block_rule_summary_view.setReadOnly(True); self.block_rule_summary_view.setMinimumHeight(120)
        
        self.block_rule_summary_view.setPlaceholderText("当前没有屏蔽项。"); block_layout.addWidget(self.block_rule_summary_view)
        
        left.addWidget(block_box); action_box = QGroupBox("操作"); action_layout = QVBoxLayout(action_box); self.status_card = QFrame(); self.status_card.setObjectName("statusCard"); status_layout = QVBoxLayout(self.status_card)
        
        self.status_title = QLabel("当前状态")
        
        self.status_title.setObjectName("headingLabel"); self.status_label = QLabel("请先选择站点并加载聊天记录。")
        
        self.status_label.setWordWrap(True); status_layout.addWidget(self.status_title)
        
        status_layout.addWidget(self.status_label)
        
        action_layout.addWidget(self.status_card); left.addWidget(action_box); left_scroll.setWidget(left_container); splitter.addWidget(left_scroll); right_container = QWidget()
        
        right = QVBoxLayout(right_container)
        
        right.setSpacing(10); stats_frame = QFrame(); stats_frame.setObjectName("statsFrame"); stats_layout = QVBoxLayout(stats_frame); site_bar = QHBoxLayout()
        
        site_bar.addWidget(QLabel("当前站点:")); self.active_site_label = QLabel("-"); self.active_site_label.setObjectName("headingLabel"); site_bar.addWidget(self.active_site_label)
        
        site_bar.addWidget(QLabel("当前期数:"))
        
        self.active_period_label = QLabel("-"); self.active_period_label.setObjectName("emphasisLabel"); site_bar.addWidget(self.active_period_label); site_bar.addWidget(QLabel("下一期数:"))
        
        self.next_period_label = QLabel("-")
        
        self.next_period_label.setObjectName("emphasisLabel"); site_bar.addWidget(self.next_period_label); site_bar.addWidget(QLabel("检索期数:")); self.period_input = QLineEdit()
        
        self.period_input.setMaximumWidth(180)
        
        self.period_input.setPlaceholderText("默认跟随下一期"); self.period_input.editingFinished.connect(self._on_period_input_changed); site_bar.addWidget(self.period_input)
        
        site_bar.addWidget(QLabel("倒计时:")); self.countdown_label = QLabel("--:--"); self.countdown_label.setObjectName("headingLabel"); self.countdown_label.setStyleSheet(f"color:{THEME["c4"]}; font-size:15px;")
        
        site_bar.addWidget(self.countdown_label)
        
        site_bar.addStretch(1); site_bar.addWidget(QLabel("锁定阈值(秒):")); self.lock_threshold_spin = QSpinBox(); self.lock_threshold_spin.setRange(5, 300)
        
        self.lock_threshold_spin.setValue(self._lock_threshold_sec)
        
        self.lock_threshold_spin.valueChanged.connect(self._on_lock_threshold_changed); site_bar.addWidget(self.lock_threshold_spin); self.auto_refresh_label = QLabel("自动刷新中"); self.auto_refresh_label.setObjectName("emphasisLabel"); site_bar.addWidget(self.auto_refresh_label)
        
        stats_layout.addLayout(site_bar); self.lock_status_label = QLabel(""); self.lock_status_label.setObjectName("headingLabel"); self.lock_status_label.setStyleSheet(f"color:{THEME["c5"]}; font-size:14px; padding:4px 0;")
        
        stats_layout.addWidget(self.lock_status_label)
        
        self.chart_window = ChartWindow(parent=self)
        
        self.chart_window.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding); stats_layout.addWidget(self.chart_window, 1); right.addWidget(stats_frame, 1); splitter.addWidget(right_container)
        
        splitter.setStretchFactor(0, 1)
        
        splitter.setStretchFactor(1, 2)
        
        outer.addWidget(splitter)
