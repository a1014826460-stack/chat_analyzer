from __future__ import annotations

import logging
import re
import unicodedata

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox


logger = logging.getLogger(__name__)
_BLOCK_NAME_SPLIT_PATTERN = re.compile(r"[\r\n,，、;；]+")


class MainWindowBlockingMixin:
    def _normalize_saved_block_rules(self, rules_raw: object) -> dict[str, dict[str, object]]:
        normalized: dict[str, dict[str, object]] = {}
        if not isinstance(rules_raw, dict):
            return normalized
        for key, raw_rule in rules_raw.items():
            group_id = str(key).strip()
            group_name = group_id
            names: list[str] = []
            if isinstance(raw_rule, dict):
                group_id = str(raw_rule.get("group_id", group_id)).strip()
                group_name = str(raw_rule.get("group_name", group_name)).strip() or group_id
                names = self._sanitize_block_names(raw_rule.get("names", []))
            elif isinstance(raw_rule, (list, tuple, set, str)):
                names = self._sanitize_block_names(raw_rule)
            rule_key = group_id or group_name
            if not rule_key:
                continue
            normalized[rule_key] = {
                "group_id": group_id or group_name,
                "group_name": group_name or group_id,
                "names": names,
            }
        return normalized

    def _sanitize_block_names(self, values: object) -> list[str]:
        if isinstance(values, str):
            candidates = _BLOCK_NAME_SPLIT_PATTERN.split(values)
        elif isinstance(values, (list, tuple, set)):
            candidates = [str(item) for item in values]
        else:
            candidates = []
        seen: set[str] = set()
        result: list[str] = []
        for raw in candidates:
            name = str(raw).strip()
            normalized = self._normalize_block_name(name)
            if not name or normalized in seen:
                continue
            seen.add(normalized)
            result.append(name)
        return result

    def _normalize_block_name(self, value: str) -> str:
        return unicodedata.normalize("NFKC", str(value).strip()).casefold()

    def _set_group_block_rules(self, rules_raw: object) -> None:
        self.group_block_rules = self._normalize_saved_block_rules(rules_raw)
        self.chat_service.set_group_block_rules(self.group_block_rules)

    def _blocked_names(self) -> list[str]:
        names: list[str] = []
        for rule in self.group_block_rules.values():
            names.extend([str(item) for item in rule.get("names", [])])
        return names

    def _blocked_rule_name_count(self) -> int:
        return len(self._blocked_names())

    def _blocked_rules_signature(self) -> tuple:
        items = []
        for rule in self.group_block_rules.values():
            group_key = str(rule.get("group_id", "") or rule.get("group_name", "")).strip()
            names = tuple(sorted(self._sanitize_block_names(rule.get("names", []))))
            items.append((group_key, names))
        return tuple(sorted(items))

    def _current_block_group_payload(self) -> dict[str, str] | None:
        payload = self.block_group_combo.currentData(Qt.UserRole)
        return payload if isinstance(payload, dict) else None

    def _selected_block_group_key(self) -> str:
        payload = self._current_block_group_payload()
        if not payload:
            return ""
        return str(payload.get("group_id", "") or payload.get("group_name", "")).strip()

    def _refresh_block_rule_group_selector(self) -> None:
        previous_key = self._selected_block_group_key() or str(
            self.settings.get("selected_block_group_key", "")
        ).strip()
        entries: list[tuple[str, str, str]] = []
        for index in range(self.group_list.count()):
            item = self.group_list.item(index)
            group_id = str(item.data(Qt.UserRole) or "").strip()
            group_name = str(item.data(Qt.UserRole + 1) or group_id).strip()
            if not (group_id or group_name):
                continue
            label = f"{group_name} [{group_id}]" if group_id and group_id != group_name else group_name
            entries.append((label, group_id or group_name, group_name))

        self.block_group_combo.blockSignals(True)
        self.block_group_combo.clear()
        for label, group_id, group_name in entries:
            self.block_group_combo.addItem(label, {"group_id": group_id, "group_name": group_name})
        self.block_group_combo.blockSignals(False)

        if previous_key:
            for index in range(self.block_group_combo.count()):
                payload = self.block_group_combo.itemData(index, Qt.UserRole)
                if isinstance(payload, dict) and str(payload.get("group_id", "")).strip() == previous_key:
                    self.block_group_combo.setCurrentIndex(index)
                    break
        elif self.block_group_combo.count():
            self.block_group_combo.setCurrentIndex(0)
        self._load_block_rule_editor_for_selected_group()
        self._refresh_block_rule_summary()

    def _load_block_rule_editor_for_selected_group(self) -> None:
        payload = self._current_block_group_payload()
        if not payload:
            self.block_names_edit.clear()
            self.block_rule_status_label.setText("No group available.")
            return
        rule = self.group_block_rules.get(str(payload["group_id"]))
        names = self._sanitize_block_names((rule or {}).get("names", []))
        self.block_names_edit.setPlainText("\n".join(names))
        if names:
            self.block_rule_status_label.setText(f"{payload['group_name']}: {len(names)} blocked names")
        else:
            self.block_rule_status_label.setText(f"{payload['group_name']}: no blocked names")

    def _on_block_group_changed(self) -> None:
        payload = self._current_block_group_payload()
        if payload:
            self.settings["selected_block_group_key"] = payload["group_id"]
        self._load_block_rule_editor_for_selected_group()
        self._refresh_block_rule_summary()
        self._save_settings()

    def _apply_block_rule_from_editor(self) -> None:
        payload = self._current_block_group_payload()
        if not payload:
            QMessageBox.information(self, "Group required", "Choose a group first.")
            return
        names = self._sanitize_block_names(self.block_names_edit.toPlainText())
        updated = dict(self.group_block_rules)
        key = str(payload["group_id"])
        if names:
            updated[key] = {"group_id": key, "group_name": payload["group_name"], "names": names}
            self.block_rule_status_label.setText(
                f"Saved {len(names)} blocked names for {payload['group_name']}."
            )
        else:
            updated.pop(key, None)
            self.block_rule_status_label.setText(
                f"Removed blocked names for {payload['group_name']}."
            )
        self._set_group_block_rules(updated)
        self._refresh_block_rule_summary()
        self._save_settings()
        self._reload_messages_after_block_rule_change()

    def _clear_block_rule_for_selected_group(self) -> None:
        payload = self._current_block_group_payload()
        if not payload:
            return
        updated = dict(self.group_block_rules)
        updated.pop(str(payload["group_id"]), None)
        self._set_group_block_rules(updated)
        self.block_names_edit.clear()
        self.block_rule_status_label.setText(f"Cleared blocked names for {payload['group_name']}.")
        self._refresh_block_rule_summary()
        self._save_settings()
        self._reload_messages_after_block_rule_change()

    def _refresh_block_rule_summary(self) -> None:
        lines = []
        for rule in sorted(self.group_block_rules.values(), key=lambda item: str(item.get("group_name", ""))):
            names = self._sanitize_block_names(rule.get("names", []))
            if not names:
                continue
            label = str(rule.get("group_name", "") or rule.get("group_id", "")).strip()
            lines.append(f"{label}: {', '.join(names)}")
        self.block_rule_summary_view.setPlainText(
            "\n".join(lines) if lines else "No blocked names configured."
        )

    def _reload_messages_after_block_rule_change(self) -> None:
        if self._current_source_path():
            self._load_filtered_messages()
