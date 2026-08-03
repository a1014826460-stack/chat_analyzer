"""State-preserving animated disclosure containers for primary modules."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, Property, QPropertyAnimation, QSize, Qt, Signal
from PySide6.QtWidgets import QLayout, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from app.ui.main_window_theme import THEME


class CollapsibleSection(QWidget):
    """Show or hide one permanent content widget without recreating children."""

    expanded_changed = Signal(bool)

    def __init__(self, title: str, *, expanded: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._expanded = False
        self._arrow_rotation = 0.0
        self._button = QToolButton()
        self._button.setText(title)
        self._button.setCheckable(True)
        self._button.setCursor(Qt.PointingHandCursor)
        self._button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._button.setStyleSheet(
            f"QToolButton {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            f"stop:0 {THEME['c3']}, stop:1 {THEME['c2']}); color: white; border: 1px solid {THEME['c2']}; "
            "border-radius: 10px; padding: 10px 12px; font-weight: 700; text-align: left; }"
            f"QToolButton:hover {{ border-color: {THEME['c1']}; background: {THEME['c2']}; }}"
            f"QToolButton:pressed {{ background: {THEME['c4']}; padding-top: 11px; padding-bottom: 9px; }}"
        )
        self._button.toggled.connect(self.set_expanded)
        self._content = QWidget()
        self._content.setObjectName("primaryModuleContent")
        self._content.setStyleSheet(
            f"QWidget#primaryModuleContent {{ background: {THEME['panel']}; "
            f"border: 1px solid {THEME['border']}; border-radius: 12px; }}"
        )
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(8, 8, 8, 4)
        content_layout.setSpacing(6)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.setSizeConstraint(QLayout.SetFixedSize)
        layout.addWidget(self._button)
        layout.addWidget(self._content)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._arrow_animation = QPropertyAnimation(self, b"arrow_rotation", self)
        self._arrow_animation.setDuration(160)
        self._arrow_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._content_animation_target_expanded = False
        self._content_animation = QPropertyAnimation(self._content, b"maximumHeight", self)
        self._content_animation.setDuration(160)
        self._content_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._content_animation.finished.connect(self._finish_content_animation)
        self.set_expanded(expanded)

    def header_button(self) -> QToolButton:
        return self._button

    def content_widget(self) -> QWidget:
        return self._content

    def content_layout(self) -> QVBoxLayout:
        return self._content.layout()  # type: ignore[return-value]

    def is_expanded(self) -> bool:
        return self._expanded

    def sizeHint(self) -> QSize:
        if not self._expanded:
            return self._button.sizeHint()
        return super().sizeHint()

    def minimumSizeHint(self) -> QSize:
        if not self._expanded:
            return self._button.minimumSizeHint()
        return super().minimumSizeHint()

    def get_arrow_rotation(self) -> float:
        return self._arrow_rotation

    def set_arrow_rotation(self, rotation: float) -> None:
        self._arrow_rotation = rotation
        self._button.setArrowType(Qt.DownArrow if rotation >= 45 else Qt.RightArrow)

    arrow_rotation = Property(float, get_arrow_rotation, set_arrow_rotation)

    def _finish_content_animation(self) -> None:
        if self._content_animation_target_expanded:
            self._content.setMaximumHeight(16_777_215)
        else:
            self._content.setVisible(False)

    def set_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        if self._button.isChecked() != expanded:
            self._button.blockSignals(True)
            self._button.setChecked(expanded)
            self._button.blockSignals(False)
        changed = self._expanded != expanded
        self._expanded = expanded
        self._content_animation.stop()
        self._content_animation_target_expanded = expanded
        content_height = max(1, self._content.sizeHint().height())
        if expanded:
            self._content.setVisible(True)
            start_height = min(self._content.maximumHeight(), content_height)
            if not self._content.isVisibleTo(self):
                start_height = 0
            end_height = content_height
        else:
            start_height = max(0, min(self._content.height(), content_height))
            end_height = 0
        self._content_animation.setStartValue(start_height)
        self._content_animation.setEndValue(end_height)
        self._content_animation.start()
        self.updateGeometry()
        self._arrow_animation.stop()
        self._arrow_animation.setStartValue(self._arrow_rotation)
        self._arrow_animation.setEndValue(90.0 if expanded else 0.0)
        self._arrow_animation.start()
        if changed:
            self.expanded_changed.emit(expanded)


class ModuleAccordion:
    """Keep exactly one primary module expanded at a time."""

    def __init__(self, *sections: CollapsibleSection) -> None:
        self._sections = tuple(sections)
        for section in self._sections:
            section.expanded_changed.connect(lambda expanded, source=section: self._on_expanded(source, expanded))

    def _on_expanded(self, source: CollapsibleSection, expanded: bool) -> None:
        if not expanded:
            return
        for section in self._sections:
            if section is not source:
                section.set_expanded(False)
