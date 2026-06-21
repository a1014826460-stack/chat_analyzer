from __future__ import annotations

import logging

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from app.services.license_service import DAY_OPTIONS, HOUR_OPTIONS, LicenseService


logger = logging.getLogger(__name__)


class LicenseGeneratorDialog(QDialog):
    def __init__(self, service: LicenseService, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("生成激活码")
        self.resize(620, 480)

        layout = QVBoxLayout(self)
        form_box = QGroupBox("参数")
        form_layout = QFormLayout(form_box)
        self.machine_code_edit = QLineEdit(self.service.get_machine_code())
        self.machine_code_edit.setPlaceholderText("粘贴目标机器码")
        self.unit_combo = QComboBox()
        self.unit_combo.addItem("天", "days")
        self.unit_combo.addItem("小时", "hours")
        self.value_combo = QComboBox()
        self._refresh_values()
        self.unit_combo.currentIndexChanged.connect(self._refresh_values)
        form_layout.addRow("机器码", self.machine_code_edit)
        form_layout.addRow("单位", self.unit_combo)
        form_layout.addRow("数值", self.value_combo)
        layout.addWidget(form_box)

        output_box = QGroupBox("生成结果")
        output_layout = QVBoxLayout(output_box)
        self.output_edit = QTextEdit()
        self.output_edit.setReadOnly(True)
        self.status_label = QLabel("请选择有效期并生成激活码。")
        output_layout.addWidget(self.output_edit)
        output_layout.addWidget(self.status_label)
        layout.addWidget(output_box, 1)

        btn_row = QHBoxLayout()
        generate_btn = QPushButton("生成")
        generate_btn.clicked.connect(self._generate_one)
        copy_machine_btn = QPushButton("复制机器码")
        copy_machine_btn.clicked.connect(self._copy_machine_code)
        self.copy_key_btn = QPushButton("复制激活码")
        self.copy_key_btn.clicked.connect(self._copy_activation_code)
        btn_row.addWidget(generate_btn)
        btn_row.addWidget(copy_machine_btn)
        btn_row.addWidget(self.copy_key_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

    def _refresh_values(self) -> None:
        self.value_combo.clear()
        unit = self.unit_combo.currentData()
        values = DAY_OPTIONS if unit == "days" else HOUR_OPTIONS
        for value in values:
            self.value_combo.addItem(str(value), value)

    def _generate_one(self) -> None:
        value = int(self.value_combo.currentData())
        unit = str(self.unit_combo.currentData())
        machine_code = self.machine_code_edit.text().strip() or self.service.get_machine_code()
        key = self.service.generate_key(value, machine_code, unit=unit)
        self.output_edit.setPlainText(key)
        self.status_label.setText(f"已为 {machine_code[:8]}... 生成 1 个激活码。")
        logger.info("Generated activation code machine=%s unit=%s value=%s", machine_code[:8], unit, value)

    def _copy_machine_code(self) -> None:
        QApplication.clipboard().setText(self.machine_code_edit.text().strip())
        self.status_label.setText("机器码已复制到剪贴板。")
        logger.info("Copied machine code from license generator")

    def _copy_activation_code(self) -> None:
        code = self.output_edit.toPlainText().strip()
        if not code:
            self.status_label.setText("请先生成激活码。")
            return
        QApplication.clipboard().setText(code)
        self.status_label.setText("激活码已复制到剪贴板。")
        self.copy_key_btn.setText("已复制")
        QTimer.singleShot(1500, lambda: self.copy_key_btn.setText("复制激活码"))
        logger.info("Copied activation code from license generator")
