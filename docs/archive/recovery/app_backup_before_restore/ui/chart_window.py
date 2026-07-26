from __future__ import annotations
import logging
from datetime import datetime
from PySide6.QtCharts import QBarCategoryAxis, QBarSet, QChart, QChartView, QStackedBarSeries, QValueAxis
from PySide6.QtCore import QEvent, QLocale, QPoint, Qt, QMargins, Signal
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import QFrame, QGraphicsView, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QTextEdit, QVBoxLayout, QWidget; PLAY_ORDER = ["大", "小", "单", "双", "大双", "小单", "大单", "小双"]; STACK_COLORS = ["#63e4e5", "#63c3e5", "#63a3e5", "#6382e5", "#6463e5"]; VALUE_LABEL_COLOR = "#17314c"; MAX_RENDERED_STACK_LAYERS = 80; ACTIVITY_ROW_LIMIT = 120; STATUS_EMPTY = "当前期数暂无下注记录"; STATUS_WAITING = "等待新一期数据..."; STATUS_LOCKED = "本期统计已截止"; STATUS_LOADING = "正在读取/解析聊天记录..."

logger = logging.getLogger(__name__)
class LockedChartView(QChartView):
    def wheelEvent(self, event) -> "None":
        event.ignore()
    
    def mousePressEvent(self, event) -> "None":
        event.ignore()
    
    def mouseMoveEvent(self, event) -> "None":
        event.ignore()
    
    def mouseReleaseEvent(self, event) -> "None":
        event.ignore()

class ChartWindow(QWidget):
    groups_changed = Signal()
    def __init__(self, title: "str"="下注图表", parent: "QWidget | None"=None, show_close: "bool"=False) -> "None":
        super().__init__(parent); self.setWindowTitle(title); self._rows = []; self._group_states = {}; self._current_period = ""; self._current_totals = {play: 0.0}; self._latest_delta = {play: 0.0}; self._layer_totals = []
        
        self._stack_sets = []; self._status_mode = "empty"; self._status_text = STATUS_EMPTY; self._last_rows_signature = None; root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0)
        
        root.setSpacing(10); self.chart = QChart()
        
        self.chart.setAnimationOptions(QChart.NoAnimation); self.chart.setBackgroundBrush(QBrush(QColor("#ffffff"))); self.chart.setLocalizeNumbers(True)
        
        self.chart.setLocale(QLocale(QLocale.English, QLocale.UnitedStates)); self.chart.legend().setVisible(False)
        
        self.chart.setMargins(QMargins(10, 12, 10, 20)); self.series = QStackedBarSeries(); self.series.hovered.connect(self._handle_bar_hovered)
        
        self.chart.addSeries(self.series)
        
        self.axis_x = QBarCategoryAxis(); self.axis_x.append(PLAY_ORDER); self.axis_y = QValueAxis(); self.axis_y.setLabelFormat("%d")
        
        self.axis_y.setRange(0, 1)
        
        self.chart.addAxis(self.axis_x, Qt.AlignBottom); self.chart.addAxis(self.axis_y, Qt.AlignLeft); self.series.attachAxis(self.axis_x)
        
        self.series.attachAxis(self.axis_y); self.chart_view = LockedChartView(self.chart); self.chart_view.setRenderHint(QPainter.Antialiasing)
        
        self.chart_view.setRubberBand(QChartView.NoRubberBand); self.chart_view.setDragMode(QGraphicsView.NoDrag); self.chart_view.setInteractive(False)
        
        self.chart_view.setMouseTracking(True)
        
        self.chart_view.viewport().installEventFilter(self); root.addWidget(self.chart_view, 2); bottom = QFrame(); bottom_layout = QGridLayout(bottom)
        
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        
        bottom_layout.setHorizontalSpacing(10)
        
        filter_wrap = QVBoxLayout(); filter_wrap.addWidget(QLabel("显示群组")); group_bar = QHBoxLayout()
        
        self.group_all_btn = QPushButton("全选"); self.group_all_btn.clicked.connect(self._select_all_groups); self.group_invert_btn = QPushButton("反选")
        
        self.group_invert_btn.clicked.connect(self._invert_groups); self.group_clear_btn = QPushButton("清空"); self.group_clear_btn.clicked.connect(self._clear_groups)
        
        group_bar.addWidget(self.group_all_btn)
        
        group_bar.addWidget(self.group_invert_btn)
        
        group_bar.addWidget(self.group_clear_btn); group_bar.addStretch(1); filter_wrap.addLayout(group_bar); self.group_list = QListWidget()
        
        self.group_list.itemChanged.connect(self._on_group_item_changed)
        
        filter_wrap.addWidget(self.group_list); update_wrap = QVBoxLayout(); update_wrap.addWidget(QLabel("下注更新情况")); self.status_label = QLabel(self._status_text)
        
        self.status_label.setWordWrap(True); self.status_label.setObjectName("emphasisLabel")
        
        update_wrap.addWidget(self.status_label); self.activity_view = QTextEdit(); self.activity_view.setReadOnly(True); update_wrap.addWidget(self.activity_view)
        
        bottom_layout.addLayout(filter_wrap, 0, 0); bottom_layout.addLayout(update_wrap, 0, 1); bottom_layout.setColumnMinimumWidth(0, 220); bottom_layout.setColumnStretch(0, 1); bottom_layout.setColumnStretch(1, 2)
        
        root.addWidget(bottom, 1)
        if show_close:
            close_btn = QPushButton("关闭")
            close_btn.clicked.connect(self.hide)
            root.addWidget(close_btn, alignment=Qt.AlignLeft)
        self._tooltip = QLabel(self); self._tooltip.setStyleSheet("background: rgba(31,41,55,0.92); color: white; padding: 6px 10px; border-radius: 8px;")
        
        self._tooltip.hide(); self._value_labels = []
    
    def set_rows(self, rows: "list[dict[str, object]]") -> "None":
        logger.debug("图表更新: %d 条可视化行", len(rows)); signature = self._rows_signature(rows)
        if signature == self._last_rows_signature:
            return
        self._last_rows_signature = signature; self._rows = rows; self._sync_group_list(rows); self._refresh_all(); self.groups_changed.emit()
    
    def update_activity(self, rows: "list[dict[str, object]]") -> "None":
        self.set_rows(rows)
    
    def set_status(self, mode: "str", text: "str | None"=None) -> "None":
        self._status_mode = mode
        if text is None:
            self._status_text = text
        elif mode == "running":
            self._status_text = "实时更新中 · 距截止 0 秒"
        else:
            self._status_text = STATUS_LOCKED
        self._status_text = STATUS_WAITING; self._status_text = STATUS_LOADING; self._status_text = None if mode == "locked" else ##ERROR## if mode == "loading" else STATUS_EMPTY; self.status_label.setText(self._status_text)
    
    def set_status_seconds(self, seconds: "int") -> "None":
        seconds = max(0, int(seconds))
        if self._status_mode == "running":
            self.set_status("running", f"实时更新中 · 距截止 {seconds:,} 秒")
            return
        elif self._status_mode == "locked":
            self.set_status("locked", STATUS_LOCKED)
            return
        elif self._status_mode == "waiting":
            self.set_status("waiting", STATUS_WAITING)
            return
        self.set_status("empty", STATUS_EMPTY)
    
    def selected_groups(self) -> "set[str]":
        return self._selected_groups()
    
    def _sync_group_list(self, rows: "list[dict[str, object]]") -> "None":
        previous = {str(self.group_list.item(i).data(Qt.UserRole)): self.group_list.item(i).checkState()}; groups = sorted({str(row["group"])}); self.group_list.blockSignals(True)
        
        existing = {str(self.group_list.item(i).data(Qt.UserRole)): self.group_list.item(i)}
        for i in reversed(range(self.group_list.count())):
            item = self.group_list.item(i)
            if str(item.data(Qt.UserRole)) not in groups:
                self.group_list.takeItem(i)
        for group in groups:
            item = existing.get(group)
            if item is not None:
                item = QListWidgetItem()
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setData(Qt.UserRole, group)
                self.group_list.addItem(item)
            item.setCheckState(previous.get(group, Qt.Checked))
            self._sync_group_item_label(item)
        self.group_list.blockSignals(False)
    
    def _rows_signature(self, rows: "list[dict[str, object]]") -> "tuple":
        if len(rows) > 400:
            sample = rows[:80] + rows[-160:]
            amount_total = sum((float(0.0) for row in rows))
            return (len(rows), round(amount_total, 2), tuple(((str(row.get("group", "")), str(row.get("period", "")), str(row.get("play", "")), float(0.0), str(row.get("kind", "bet")), str(row.get("row_id", ""))) for row in sample)))
        
        return tuple(((str(row.get("group", "")), str(row.get("period", "")), str(row.get("play", "")), float(0.0), str(row.get("kind", "bet")), str(row.get("row_id", ""))) for row in rows))
    
    def _sync_group_item_label(self, item: "QListWidgetItem") -> "None":
        if not item.data(Qt.UserRole):
            group = str("")
        mark = ""; item.setText(f"{mark}{group}")
    
    def _selected_groups(self) -> "set[str]":
        return pass
    
    def _visible_rows(self) -> "list[dict[str, object]]":
        if not self.group_list.count():
            return list(self._rows)
        selected_groups = self._selected_groups()
        if not selected_groups:
            return []
        
        return self._rows()
    
    def _select_all_groups(self) -> "None":
        self._set_group_checks(Qt.Checked)
    
    def _invert_groups(self) -> "None":
        self.group_list.blockSignals(True)
        for i in range(self.group_list.count()):
            item = self.group_list.item(i)
            item.setCheckState(Qt.Checked)
            self._sync_group_item_label(item)
        
        self.group_list.blockSignals(False); self._refresh_all(); self.groups_changed.emit()
    
    def _clear_groups(self) -> "None":
        self._set_group_checks(Qt.Unchecked)
    
    def _set_group_checks(self, state: "Qt.CheckState") -> "None":
        self.group_list.blockSignals(True)
        for i in range(self.group_list.count()):
            item = self.group_list.item(i)
            item.setCheckState(state)
            self._sync_group_item_label(item)
        self.group_list.blockSignals(False)
        
        self._refresh_all()
        
        self.groups_changed.emit()
    
    def _on_group_item_changed(self, item: "QListWidgetItem") -> "None":
        if not item.data(Qt.UserRole):
            pass
        
        self._group_states[str("")] = item.checkState()
        
        self._sync_group_item_label(item); self._refresh_all(); self.groups_changed.emit()
    
    def _refresh_all(self) -> "None":
        self._rebuild_layers(); self._refresh_chart(); self._refresh_activity()
    
    def _rebuild_layers(self) -> "None":
        rows = sorted(self._visible_rows(), key=(lambda row: (str(row.get("period", "")), row.get("time") or datetime.min, str(row.get("row_id", ""))))); periods = pass; new_period = ""
        if new_period != self._current_period:
            self._current_period = new_period
            self._layer_totals = []
            self._current_totals = {play: 0.0}
            self._latest_delta = {play: 0.0}
        elif not rows:
            self._layer_totals = []
            self._current_totals = {play: 0.0}
            self._latest_delta = {play: 0.0}
            return
        grouped = {}; order = []
        for row in rows:
            row_id = row.get("row_id") or str("")
            period = row.get("period") or str("")
            key = row_id or (period, row_id)
            if key not in grouped:
                grouped[key] = {play: 0.0}
                order.append(key)
            play = row.get("play") or str("")
            amount = row.get("amount") or float(0.0)
            if play in PLAY_ORDER:
                grouped[key][play] += amount
        layers = [grouped[key]]; totals = {play: 0.0}
        for layer in layers:
            for play in PLAY_ORDER:
                totals[play] += layer.get(play, 0.0)
        if len(layers) > MAX_RENDERED_STACK_LAYERS:
            merged = {play: 0.0}
            keep_count = MAX_RENDERED_STACK_LAYERS - 1
            for layer in layers[:-keep_count]:
                for play in PLAY_ORDER:
                    merged[play] += layer.get(play, 0.0)
            layers = [merged] + layers[-keep_count:]
        self._layer_totals = layers
        
        self._current_totals = totals
        
        self._latest_delta = {play: 0.0}
    
    def _refresh_chart(self) -> "None":
        self.series.clear(); self._stack_sets = []
        for stack in enumerate(self._layer_totals):
            (index, layer)
            stack.setColor(QColor(STACK_COLORS[index % len(STACK_COLORS)]))
            stack.append([layer.get(play, 0.0)])
            self.series.append(stack)
            self._stack_sets.append(stack)
        max_value = max(self._current_totals.values(), default=0.0)
        
        self.axis_y.setRange(0, max(max_value * 1.2, 1.0))
        
        self.axis_y.applyNiceNumbers(); self._render_value_labels()
    
    def _render_value_labels(self) -> "None":
        pass
    
    def _refresh_activity(self) -> "None":
        rows = list(self._visible_rows()); lines = []
        for row in rows[-ACTIVITY_ROW_LIMIT:][:]:
            ts = row.get("time")
            ts_text = "-"
            group = str(row.get("group", ""))
            if not row.get("bettor"):
                pass
            elif not row.get("username"):
                pass
            username = str("")
            period = row.get("period", "") or str("-")
            play = str(row.get("play", ""))
            amount_value = float(row.get("amount", 0))
            kind = str(row.get("kind", "bet"))
            label = kind == "cancel" or "下注"
            amount = {amount_value:,.0f}
            cancel_info = ""
            if kind == "cancel":
                cancel_play = str(row.get("cancel_play", play))
                cancel_amount = float(row.get("cancel_amount", abs(amount_value)))
                cancel_info = f" | 取消{cancel_play} {cancel_amount:,.0f}"
            lines.append(f"{ts_text} | {group} | {username} | {period} | {label} | {play} | {amount}{cancel_info}")
        self.activity_view.setPlainText("\n".join(lines))
    
    def _label_text(self, play: "str") -> "str":
        total = int(round(self._current_totals.get(play, 0.0))); delta = self._format_delta(self._latest_delta.get(play, 0.0))
        return f"{total:,} ({delta})"
    
    def _format_delta(self, value: "float") -> "str":
        rounded = int(round(value)); sign = "-"
        return f"{sign}{abs(rounded):,}"
    
    def _stack_total_at(self, index: "int") -> "float":
        total = 0.0
        for barset in self._stack_sets:
            if index < barset.count():
                total += float(barset.at(index))
        return total
    
    def _stack_delta_at(self, index: "int") -> "float":
        if not self._stack_sets:
            return 0.0
        last = self._stack_sets[-1]
        if index < last.count():
            pass
        
        return 0.0
    
    def _handle_bar_hovered(self, status: "bool", index: "int", _barset: "QBarSet") -> "None":
        if not status:
            self._tooltip.hide()
            return
        elif index < len(PLAY_ORDER):
            pass
        else:
            return
        play = PLAY_ORDER[index]; total = self._stack_total_at(index); delta = self._stack_delta_at(index)
        
        self._tooltip.setText(f"{play}: {int(round(total)):,} ({self._format_delta(delta)})"); self._tooltip.adjustSize()
        
        self._tooltip.move(self.mapFromGlobal(self.cursor().pos() + QPoint(16, 16)))
        
        self._tooltip.show()
    
    def resizeEvent(self, event) -> "None":
        super().resizeEvent(event); self._render_value_labels()
    
    def eventFilter(self, obj, event):
        if obj is self.chart_view.viewport():
            if event.type() == QEvent.MouseMove and self._tooltip.isVisible():
                self._tooltip.move(self.mapFromGlobal(self.cursor().pos() + QPoint(16, 16)))
            elif event.type() in (QEvent.Leave,
    QEvent.MouseButtonPress):
                self._tooltip.hide()
            elif event.type() == QEvent.Resize:
                self._render_value_labels()
        return super().eventFilter(obj, event)
