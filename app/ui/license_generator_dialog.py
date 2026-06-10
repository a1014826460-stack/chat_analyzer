from __future__ import annotations

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


class LicenseGeneratorDialog(QDialog):
    def __init__(self, service: LicenseService, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("Generate Activation Codes")
        self.resize(620, 480)

        layout = QVBoxLayout(self)
        form_box = QGroupBox("Parameters")
        form_layout = QFormLayout(form_box)
        self.machine_code_edit = QLineEdit(self.service.get_machine_code())
        self.machine_code_edit.setPlaceholderText("Paste target machine code")
        self.unit_combo = QComboBox()
        self.unit_combo.addItem("Days", "days")
        self.unit_combo.addItem("Hours", "hours")
        self.value_combo = QComboBox()
        self._refresh_values()
        self.unit_combo.currentIndexChanged.connect(self._refresh_values)
        form_layout.addRow("Machine code", self.machine_code_edit)
        form_layout.addRow("Unit", self.unit_combo)
        form_layout.addRow("Value", self.value_combo)
        layout.addWidget(form_box)

        output_box = QGroupBox("Generated Codes")
        output_layout = QVBoxLayout(output_box)
        self.output_edit = QTextEdit()
        self.output_edit.setReadOnly(True)
        self.status_label = QLabel("Choose a duration and generate a code.")
        output_layout.addWidget(self.output_edit)
        output_layout.addWidget(self.status_label)
        layout.addWidget(output_box, 1)

        btn_row = QHBoxLayout()
        generate_btn = QPushButton("Generate")
        generate_btn.clicked.connect(self._generate_one)
        copy_btn = QPushButton("Copy machine code")
        copy_btn.clicked.connect(self._copy_machine_code)
        btn_row.addWidget(generate_btn)
        btn_row.addWidget(copy_btn)
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
        self.status_label.setText(f"Generated 1 activation code for {machine_code[:8]}...")

    def _copy_machine_code(self) -> None:
        QApplication.clipboard().setText(self.machine_code_edit.text().strip())
        self.status_label.setText("Machine code copied to clipboard.")
