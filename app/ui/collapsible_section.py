"""Small state-preserving disclosure container for settings panels."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QToolButton, QVBoxLayout, QWidget


class CollapsibleSection(QWidget):
    """Show or hide one permanent content widget without recreating children."""

    expanded_changed = Signal(bool)

    def __init__(self, title: str, *, expanded: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._expanded = False
        self._button = QToolButton()
        self._button.setText(title)
        self._button.setCheckable(True)
        self._button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._button.toggled.connect(self.set_expanded)
        self._content = QWidget()
        self._content.setLayout(QVBoxLayout())
        self._content.layout().setContentsMargins(8, 0, 0, 0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self._button)
        layout.addWidget(self._content)
        self.set_expanded(expanded)

    def content_widget(self) -> QWidget:
        return self._content

    def content_layout(self) -> QVBoxLayout:
        return self._content.layout()  # type: ignore[return-value]

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        if self._button.isChecked() != expanded:
            self._button.blockSignals(True)
            self._button.setChecked(expanded)
            self._button.blockSignals(False)
        changed = self._expanded != expanded
        self._expanded = expanded
        self._content.setVisible(expanded)
        self._button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        if changed:
            self.expanded_changed.emit(expanded)
