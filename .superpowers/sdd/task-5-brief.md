# Task 5: Auto Bet GUI Panel

**Goal:** Create the PySide6 GUI panel widget for auto-bet configuration and control.

**File to create:** `app/ui/auto_bet_panel.py`

**Dependencies:** Task 1 models (`app/models/auto_bet.py`) already committed.

## Requirements

1. `AutoBetPanel(QGroupBox)` — widget with title "自动下注"
2. Signals: `config_changed(StrategyConfig)`, `start_clicked()`, `stop_clicked()`
3. Strategy type dropdown ("趋势跟踪")
4. Site dropdown (pc28, macao, australia, norway)
5. Target group checklist (populated externally)
6. Parameter inputs: observation_window (3-100, default 10), trigger_threshold (2-50, default 3), bet_amount (0.01-999999, default 10.0)
7. Play type checkboxes (大, 小, 单, 双, 大单, 小单, 大双, 小双)
8. Lock threshold spin (5-120, default 15)
9. Start/Stop buttons with status label
10. Read-only run log QTextEdit (max height 150)
11. `set_available_groups(groups: list[tuple[str, str]])` — populate group list
12. `set_running(bool)` — toggle UI state
13. `append_log(InjectRecord)` — add log line
14. `get_config() -> StrategyConfig` — build config from UI
15. `load_config(StrategyConfig)` — apply config to UI

## Exact Code

```python
from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.models.auto_bet import InjectRecord, StrategyConfig


logger = logging.getLogger(__name__)

PLAY_TYPE_OPTIONS = ["大", "小", "单", "双", "大单", "小单", "大双", "小双"]
SITE_OPTIONS = ["pc28", "macao", "australia", "norway"]


class AutoBetPanel(QGroupBox):
    """Auto-betting configuration and control panel.

    Signals:
        config_changed(StrategyConfig) — emitted when any parameter changes
        start_clicked() — start button pressed
        stop_clicked()  — stop button pressed
    """

    config_changed = Signal(object)
    start_clicked = Signal()
    stop_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("自动下注", parent)
        self._config = StrategyConfig()
        self._running = False
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_available_groups(self, groups: list[tuple[str, str]]) -> None:
        """Populate target group checklist. Each item is (group_id, group_name)."""
        self._target_group_list.clear()
        for group_id, group_name in groups:
            item = QListWidgetItem(group_name)
            item.setData(Qt.UserRole, group_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(
                Qt.Checked if group_id in self._config.target_groups else Qt.Unchecked
            )
            self._target_group_list.addItem(item)

    def set_running(self, running: bool) -> None:
        """Update UI for running/stopped state."""
        self._running = running
        self._start_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)
        self._status_label.setText("● 运行中" if running else "○ 已停止")
        self._status_label.setStyleSheet(
            "color: #4caf50; font-weight: bold;" if running else "color: #9e9e9e;"
        )

    def append_log(self, record: InjectRecord) -> None:
        """Append a line to the run log."""
        ts = record.ts.strftime("%H:%M:%S")
        icon = "✓" if record.success else "✗"
        if record.play_type:
            line = f"{ts} {icon} [{record.group_name}] → {record.play_type} {record.amount}"
        else:
            line = f"{ts} {icon} {record.content}"
        if record.error:
            line += f"  ({record.error})"
        self._log_edit.append(line)

    def get_config(self) -> StrategyConfig:
        """Build config from current UI state."""
        checked_groups: list[str] = []
        for i in range(self._target_group_list.count()):
            item = self._target_group_list.item(i)
            if item.checkState() == Qt.Checked:
                gid = str(item.data(Qt.UserRole) or "")
                if gid:
                    checked_groups.append(gid)

        checked_plays: list[str] = []
        for pt, cb in self._play_checkboxes.items():
            if cb.isChecked():
                checked_plays.append(pt)

        return StrategyConfig(
            strategy_type="trend_following",
            enabled=self._running,
            site=self._site_combo.currentText().strip(),
            target_groups=checked_groups,
            observation_window=self._obs_window_spin.value(),
            trigger_threshold=self._trigger_spin.value(),
            bet_amount=self._amount_spin.value(),
            play_types=checked_plays,
            lock_threshold_sec=self._lock_spin.value(),
        )

    def load_config(self, config: StrategyConfig) -> None:
        """Apply config to UI fields."""
        self._config = config
        idx = self._site_combo.findText(config.site)
        if idx >= 0:
            self._site_combo.setCurrentIndex(idx)
        self._obs_window_spin.setValue(config.observation_window)
        self._trigger_spin.setValue(config.trigger_threshold)
        self._amount_spin.setValue(config.bet_amount)
        self._lock_spin.setValue(config.lock_threshold_sec)
        for pt, cb in self._play_checkboxes.items():
            cb.setChecked(pt in config.play_types)

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # --- Row: strategy type ---
        strategy_row = QHBoxLayout()
        strategy_row.addWidget(QLabel("策略:"))
        self._strategy_combo = QComboBox()
        self._strategy_combo.addItem("趋势跟踪", "trend_following")
        self._strategy_combo.currentIndexChanged.connect(self._emit_config)
        strategy_row.addWidget(self._strategy_combo, 1)
        layout.addLayout(strategy_row)

        # --- Row: site ---
        site_row = QHBoxLayout()
        site_row.addWidget(QLabel("站点:"))
        self._site_combo = QComboBox()
        self._site_combo.addItems(SITE_OPTIONS)
        self._site_combo.currentTextChanged.connect(self._emit_config)
        site_row.addWidget(self._site_combo, 1)
        layout.addLayout(site_row)

        # --- Target groups ---
        layout.addWidget(QLabel("目标群组:"))
        self._target_group_list = QListWidget()
        self._target_group_list.setMaximumHeight(80)
        self._target_group_list.itemChanged.connect(self._emit_config)
        layout.addWidget(self._target_group_list)

        # --- Parameters grid ---
        grid = QHBoxLayout()
        grid.addWidget(QLabel("观察窗口:"))
        self._obs_window_spin = QSpinBox()
        self._obs_window_spin.setRange(3, 100)
        self._obs_window_spin.setValue(10)
        self._obs_window_spin.valueChanged.connect(self._emit_config)
        grid.addWidget(self._obs_window_spin)
        grid.addWidget(QLabel("期"))
        grid.addWidget(QLabel("触发阈值:"))
        self._trigger_spin = QSpinBox()
        self._trigger_spin.setRange(2, 50)
        self._trigger_spin.setValue(3)
        self._trigger_spin.valueChanged.connect(self._emit_config)
        grid.addWidget(self._trigger_spin)
        grid.addWidget(QLabel("次"))
        grid.addStretch(1)
        layout.addLayout(grid)

        # --- Amount ---
        amt_row = QHBoxLayout()
        amt_row.addWidget(QLabel("下注金额:"))
        self._amount_spin = QDoubleSpinBox()
        self._amount_spin.setRange(0.01, 999999.0)
        self._amount_spin.setDecimals(2)
        self._amount_spin.setValue(10.0)
        self._amount_spin.valueChanged.connect(self._emit_config)
        amt_row.addWidget(self._amount_spin)
        amt_row.addStretch(1)
        layout.addLayout(amt_row)

        # --- Play types ---
        play_row = QHBoxLayout()
        play_row.addWidget(QLabel("玩法:"))
        self._play_checkboxes: dict[str, QCheckBox] = {}
        for pt in PLAY_TYPE_OPTIONS:
            cb = QCheckBox(pt)
            cb.setChecked(pt in ("大", "小"))
            cb.toggled.connect(self._emit_config)
            self._play_checkboxes[pt] = cb
            play_row.addWidget(cb)
        play_row.addStretch(1)
        layout.addLayout(play_row)

        # --- Lock threshold ---
        lock_row = QHBoxLayout()
        lock_row.addWidget(QLabel("封盘提前:"))
        self._lock_spin = QSpinBox()
        self._lock_spin.setRange(5, 120)
        self._lock_spin.setValue(15)
        self._lock_spin.valueChanged.connect(self._emit_config)
        lock_row.addWidget(self._lock_spin)
        lock_row.addWidget(QLabel("秒"))
        lock_row.addStretch(1)
        layout.addLayout(lock_row)

        # --- Start/Stop buttons ---
        btn_row = QHBoxLayout()
        self._start_btn = QPushButton("▶ 启动")
        self._start_btn.clicked.connect(self._on_start)
        btn_row.addWidget(self._start_btn)
        self._stop_btn = QPushButton("■ 停止")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop)
        btn_row.addWidget(self._stop_btn)
        self._status_label = QLabel("○ 已停止")
        self._status_label.setStyleSheet("color: #9e9e9e;")
        btn_row.addWidget(self._status_label)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        # --- Run log ---
        layout.addWidget(QLabel("运行日志:"))
        self._log_edit = QTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setMaximumHeight(150)
        self._log_edit.setPlaceholderText("策略运行日志将显示在这里...")
        layout.addWidget(self._log_edit)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _emit_config(self) -> None:
        self.config_changed.emit(self.get_config())

    def _on_start(self) -> None:
        self.set_running(True)
        self.start_clicked.emit()

    def _on_stop(self) -> None:
        self.set_running(False)
        self.stop_clicked.emit()
```

## Testing

```bash
.\.venv\Scripts\python.exe -c "
import sys
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from app.ui.auto_bet_panel import AutoBetPanel
panel = AutoBetPanel()
# Test get_config with defaults
cfg = panel.get_config()
assert cfg.strategy_type == 'trend_following'
assert cfg.site == 'pc28'
assert cfg.observation_window == 10
assert cfg.trigger_threshold == 3
assert cfg.bet_amount == 10.0
# Test load_config
from app.models.auto_bet import StrategyConfig
cfg2 = StrategyConfig(site='macao', bet_amount=99.0, play_types=['单', '双'])
panel.load_config(cfg2)
cfg3 = panel.get_config()
assert cfg3.site == 'macao'
assert cfg3.bet_amount == 99.0
assert '单' in cfg3.play_types
# Test log append
from app.models.auto_bet import InjectRecord
from datetime import datetime
panel.append_log(InjectRecord(ts=datetime.now(), group_name='test', play_type='大', amount=100, content='大 100', success=True))
print('All GUI panel tests passed!')
"
```
