from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTextEdit, QVBoxLayout, QWidget
from app.services.license_service import DAY_OPTIONS, HOUR_OPTIONS, LicenseService
from app.ui.main_window_theme import THEME

class LicenseGeneratorDialog(QDialog):
    def __init__(self, service: "LicenseService", parent: "QWidget | None"=None) -> "None":
        super().__init__(parent); self.service = service; self.setWindowTitle("管理员激活码工作台"); self.setModal(True); self.setMinimumSize(980, 680)
        
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        
        self.machine_code_edit = QLineEdit(self.service.get_machine_code()); self.machine_code_edit.setPlaceholderText("输入或粘贴目标机器码"); self.unit_combo = QComboBox()
        
        self.unit_combo.addItem("天", "days"); self.unit_combo.addItem("小时", "hours"); self.unit_combo.currentIndexChanged.connect(self._refresh_duration_options); self.value_combo = QComboBox(); self.count_spin = QSpinBox()
        
        self.count_spin.setRange(1, 100); self.count_spin.setValue(1); self.output_edit = QTextEdit()
        
        self.output_edit.setPlaceholderText("生成结果会显示在这里"); self.output_edit.setReadOnly(True); self.output_edit.setMinimumHeight(240); self.status_label = QLabel("请选择有效期和机器码后开始生成。"); self.status_label.setObjectName("emphasisLabel")
        
        self._build_ui()
        
        self._apply_style(); self._refresh_duration_options()
    
    def _build_ui(self) -> "None":
        root = QVBoxLayout(self); root.setContentsMargins(20, 20, 20, 20); root.setSpacing(16); hero = QFrame(); hero.setObjectName("licenseHero"); hero_layout = QVBoxLayout(hero); hero_layout.setContentsMargins(20, 18, 20, 18); hero_layout.setSpacing(8); title = QLabel("管理员激活码工作台")
        
        title.setObjectName("heroTitle")
        
        subtitle = QLabel("支持目标机器码、天/小时有效期、批量生成与文件导出。")
        
        subtitle.setObjectName("heroSubtitle"); tip = QLabel("与当前发布版本共用固定签名密钥，不会因重新打包而失效。"); tip.setObjectName("heroTip"); hero_layout.addWidget(title); hero_layout.addWidget(subtitle); hero_layout.addWidget(tip)
        
        body = QHBoxLayout()
        
        body.setSpacing(16); form_box = QGroupBox("生成参数"); form_layout = QGridLayout(form_box); form_layout.setHorizontalSpacing(12); form_layout.setVerticalSpacing(12)
        
        form_layout.addWidget(QLabel("目标机器码"), 0, 0)
        
        form_layout.addWidget(self.machine_code_edit, 0, 1, 1, 3); copy_btn = QPushButton("复制"); copy_btn.clicked.connect(self._copy_machine_code)
        
        form_layout.addWidget(copy_btn, 0, 4); form_layout.addWidget(QLabel("有效期单位"), 1, 0); form_layout.addWidget(self.unit_combo, 1, 1)
        
        form_layout.addWidget(QLabel("有效期数值"), 1, 2); form_layout.addWidget(self.value_combo, 1, 3)
        
        form_layout.addWidget(QLabel("生成数量"), 2, 0); form_layout.addWidget(self.count_spin, 2, 1); button_row = QHBoxLayout(); self.single_btn = QPushButton("生成单个")
        
        self.single_btn.clicked.connect(self._generate_single); self.batch_btn = QPushButton("批量生成"); self.batch_btn.clicked.connect(self._generate_batch); self.save_btn = QPushButton("保存结果")
        
        self.save_btn.clicked.connect(self._save_results); button_row.addWidget(self.single_btn); button_row.addWidget(self.batch_btn); button_row.addWidget(self.save_btn); button_row.addStretch(1)
        
        form_layout.addLayout(button_row, 3, 0, 1, 4)
        
        form_layout.addWidget(self.status_label, 4, 0, 1, 4); output_box = QGroupBox("生成结果"); output_layout = QVBoxLayout(output_box)
        
        output_layout.addWidget(self.output_edit); body.addWidget(form_box, 2); body.addWidget(output_box, 3)
        
        footer = QHBoxLayout(); footer.addStretch(1); close_btn = QPushButton("关闭"); close_btn.clicked.connect(self.reject)
        
        footer.addWidget(close_btn); root.addWidget(hero); root.addLayout(body); root.addLayout(footer)
    
    def _apply_style(self) -> "None":
        self.setStyleSheet(f"\n            QDialog {\n                background: {THEME["bg"]};\n            }\n            QGroupBox {\n                background: {THEME["panel"]};\n                border: 1px solid {THEME["border"]};\n                border-radius: 18px;\n                margin-top: 14px;\n                padding: 18px 16px 16px 16px;\n                font-weight: 700;\n            }\n            QGroupBox::title {\n                subcontrol-origin: margin;\n                left: 16px;\n                padding: 0 6px;\n                color: {THEME["c5"]};\n            }\n            QFrame#licenseHero {\n                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,\n                    stop:0 #ffffff, stop:1 #eef7ff);\n                border: 1px solid {THEME["border"]};\n                border-radius: 22px;\n            }\n            QLabel#heroTitle {\n                font-size: 20px;\n                font-weight: 800;\n                color: {THEME["text"]};\n            }\n            QLabel#heroSubtitle {\n                color: {THEME["muted"]};\n            }\n            QLabel#heroTip {\n                color: {THEME["c5"]};\n                font-weight: 700;\n            }\n            QLineEdit, QTextEdit, QComboBox, QSpinBox {\n                background: white;\n                border: 1px solid {THEME["border"]};\n                border-radius: 12px;\n                padding: 8px 10px;\n            }\n            QPushButton {\n                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,\n                    stop:0 {THEME["c4"]}, stop:1 {THEME["c5"]});\n                color: white;\n                border: none;\n                border-radius: 12px;\n                padding: 9px 16px;\n                font-weight: 700;\n            }\n            QPushButton:hover {\n                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,\n                    stop:0 {THEME["c3"]}, stop:1 {THEME["c4"]});\n            }\n            QPushButton:pressed {\n                background: {THEME["c5"]};\n            }\n            ")
    
    def _refresh_duration_options(self) -> "None":
        unit = str(self.unit_combo.currentData()); self.value_combo.blockSignals(True); self.value_combo.clear(); options = DAY_OPTIONS if unit == "days" else HOUR_OPTIONS; unit_label = "小时"
        for value in options:
            self.value_combo.addItem(f"{value} {unit_label}", value)
        
        self.value_combo.blockSignals(False)
    
    def _current_duration(self) -> "tuple[int, str]":
        return (int(self.value_combo.currentData()), str(self.unit_combo.currentData()))
    
    def _generate_single(self) -> "None":
        machine_code = self.machine_code_edit.text().strip(); value, unit = self._current_duration()
        try:
            key = self.service.generate_key(value, machine_code, unit=unit)
        except Exception:
            QMessageBox.warning(self, "生成失败", str(exc))
        
        self.output_edit.setPlainText(key)
        if not machine_code:
            pass
        self.status_label.setText(f"已生成 1 个激活码，目标机器码 {"当前机器"}。")
    
    def _generate_batch(self) -> "None":
        machine_code = self.machine_code_edit.text().strip(); value, unit = self._current_duration(); count = self.count_spin.value(); keys = []
        for _ in range(count):
            keys.append(self.service.generate_key(value, machine_code, unit=unit))
        
        self.output_edit.setPlainText("\n".join(keys)); unit_label = "小时"
        
        self.status_label.setText(f"已生成 {len(keys)} 个激活码，{value} {unit_label}。")
    
    def _save_results(self) -> "None":
        text = self.output_edit.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "无内容", "请先生成激活码。")
            return
        value, unit = self._current_duration(); unit_suffix = "h"; file_path, _ = QFileDialog.getSaveFileName(self, "保存激活码", f"activation_keys_{value}{unit_suffix}.txt", "Text (*.txt);;All Files (*)")
        if not file_path:
            return
        Path(file_path).write_text(text, encoding="utf-8")
        
        self.status_label.setText(f"激活码已保存至 {file_path}")
    
    def _copy_machine_code(self) -> "None":
        QApplication.clipboard().setText(self.machine_code_edit.text().strip()); self.status_label.setText("机器码已复制到剪贴板。")
