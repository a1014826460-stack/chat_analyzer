from PySide6.QtWidgets import QApplication, QLineEdit

from app.ui.collapsible_section import CollapsibleSection


def test_collapsible_section_preserves_the_existing_content_widget_and_values():
    app = QApplication.instance() or QApplication([])
    section = CollapsibleSection("高级配置", expanded=True)
    field = QLineEdit("preserved")
    section.content_layout().addWidget(field)
    content = section.content_widget()

    section.set_expanded(False)
    section.set_expanded(True)

    assert section.content_widget() is content
    assert field.text() == "preserved"
    assert section.is_expanded()
