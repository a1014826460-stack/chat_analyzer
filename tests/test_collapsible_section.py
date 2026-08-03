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


def test_module_accordion_expands_one_primary_module_without_recreating_content():
    from app.ui.collapsible_section import ModuleAccordion

    app = QApplication.instance() or QApplication([])
    site = CollapsibleSection("线路选择", expanded=True)
    account = CollapsibleSection("账号与数据源")
    blocked = CollapsibleSection("屏蔽名单")
    auto_bet = CollapsibleSection("自动下注")
    field = QLineEdit("retained")
    account.content_layout().addWidget(field)
    accordion = ModuleAccordion(site, account, blocked, auto_bet)

    account.set_expanded(True)

    assert not site.is_expanded()
    assert account.is_expanded()
    assert not blocked.is_expanded()
    assert not auto_bet.is_expanded()
    assert field.text() == "retained"
    assert "border-radius" in account.header_button().styleSheet()
    assert account._content_animation.duration() > 0
    assert "background: #ffffff" in account.content_widget().styleSheet()


def test_auto_bet_panel_is_a_primary_collapsible_module():
    from app.ui.auto_bet_panel import AutoBetPanel

    app = QApplication.instance() or QApplication([])
    panel = AutoBetPanel()

    assert isinstance(panel, CollapsibleSection)
    assert panel.header_button().text() == "自动下注"
    assert panel.is_expanded()


def test_primary_module_card_uses_compact_header_to_content_spacing():
    app = QApplication.instance() or QApplication([])
    section = CollapsibleSection("线路选择", expanded=True)

    assert section.layout().spacing() == 3


def test_collapsed_primary_module_uses_only_its_header_height():
    app = QApplication.instance() or QApplication([])
    section = CollapsibleSection("筛选条件")

    assert section.minimumHeight() == 0
    assert section.minimumSizeHint().height() <= section.header_button().sizeHint().height()
    assert section.sizeHint().height() <= section.header_button().sizeHint().height()
