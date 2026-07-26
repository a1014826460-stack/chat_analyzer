from __future__ import annotations
import logging, re, unicodedata
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox; logger = logging.getLogger(__name__); _BLOCK_NAME_SPLIT_PATTERN = re.compile("[\\r\\n,，;；]+")
class MainWindowBlockingMixin:
    def _normalize_saved_block_rules(self, rules_raw: "object") -> "dict[str, dict[str, object]]":
        normalized = {}
        if not isinstance(rules_raw, dict):
            return normalized
        for key, raw_rule in rules_raw.items():
            if isinstance(raw_rule, dict):
                if not raw_rule.get("group_id"):
                    pass
                group_id = key or str("").strip()
                if not raw_rule.get("group_name"):
                    pass
                elif not group_id:
                    pass
                group_name = str("").strip()
                names = self._sanitize_block_names(raw_rule.get("names", []))
            elif isinstance(raw_rule, list):
                group_id = key or str("").strip()
                group_name = group_id
                names = self._sanitize_block_names(raw_rule)
            
            rule_key = group_id or group_name
            if not rule_key or names:
                pass
            normalized[rule_key] = {"group_id": group_id or group_name, "group_name": group_name or group_id, "names": names}
        
        return normalized
    
    def _sanitize_block_names(self, values: "object") -> "list[str]":
        result = []; seen = set()
        if isinstance(values, str):
            candidates = _BLOCK_NAME_SPLIT_PATTERN.split(values)
        elif isinstance(values, (list, tuple, set)):
            candidates = [str(item)]
        else:
            candidates = []
        for raw in candidates:
            name = str(raw).strip()
            normalized = self._normalize_block_name(name)
            if normalized and normalized in seen:
                pass
            seen.add(normalized)
            result.append(name)
        return result
    
    def _normalize_block_name(self, value: "str") -> "str":
        return unicodedata.normalize("NFKC", str(value).strip()).casefold()
    
    def _set_group_block_rules(self, rules_raw: "object") -> "None":
        self.group_block_rules = self._normalize_saved_block_rules(rules_raw); self.chat_service.set_group_block_rules(self.group_block_rules)
    
    def _blocked_names(self) -> "list[str]":
        return []
    
    def _blocked_rule_name_count(self) -> "int":
        return sum((len(rule.get("names", [])) for rule in self.group_block_rules.values()))
    
    def _blocked_rules_signature(self) -> "tuple":
        items = []
        for rule in self.group_block_rules.values():
            if not rule.get("group_id"):
                pass
            group_key = rule.get("group_name") or str("").strip()
            names = tuple(sorted(pass))
            if group_key and names:
                items.append((group_key, names))
        return tuple(sorted(items))
    
    def _current_block_group_payload(self) -> "dict[str, str] | None":
        if not hasattr(self, "block_group_combo"):
            return
        payload = self.block_group_combo.currentData(Qt.UserRole)
        if not isinstance(payload, dict):
            return
        group_id = str(payload.get("group_id", "")).strip()
        
        group_name = str(payload.get("group_name", "")).strip()
        if not group_id and group_name:
            return
        
        return {"group_id": group_id or group_name, "group_name": group_name or group_id}
    
    def _selected_block_group_key(self) -> "str":
        payload = self._current_block_group_payload()
        if not payload:
            return ""
        
        return payload["group_id"] or payload["group_name"]
    
    def _refresh_block_rule_group_selector(self) -> "None":
        if not hasattr(self, "block_group_combo"):
            return
        previous_key = self._selected_block_group_key() or str(self.settings.get("selected_block_group_key", "")).strip(); entries = []; seen = set()
        for i in range(self.group_list.count()):
            item = self.group_list.item(i)
            group_id = item.data(Qt.UserRole) or str("").strip()
            group_name = item.data((Qt.UserRole) + 1) or str(group_id).strip()
            group_key = group_id or group_name
            if group_key and group_key in seen:
                pass
            seen.add(group_key)
            label = group_id and f"{group_name} [{group_id}]"
            if not group_name:
                pass
            entries.append((label, group_id or group_name, group_id))
        
        self.block_group_combo.blockSignals(True); self.block_group_combo.clear()
        for label, group_id, group_name in entries:
            self.block_group_combo.addItem(label, {"group_id": group_id, "group_name": group_name})
        self.block_group_combo.blockSignals(False); current_index = -1
        if previous_key:
            for i in range(self.block_group_combo.count()):
                payload = self.block_group_combo.itemData(i, Qt.UserRole)
                if isinstance(payload, dict) and str(payload.get("group_id", "")).strip() == previous_key:
                    current_index = i
        elif current_index >= 0:
            self.block_group_combo.setCurrentIndex(current_index)
        
        elif self.block_group_combo.count():
            self.block_group_combo.setCurrentIndex(0)
        has_groups = self.block_group_combo.count() > 0; self.block_group_combo.setEnabled(has_groups); self.block_names_edit.setEnabled(has_groups)
        
        self.block_rule_save_btn.setEnabled(has_groups)
        
        self.block_rule_clear_btn.setEnabled(has_groups)
        if has_groups:
            self._load_block_rule_editor_for_selected_group()
        else:
            self.block_names_edit.clear()
            self.block_rule_status_label.setText("当前没有可配置的群组。")
        self._refresh_block_rule_summary()
    
    def _load_block_rule_editor_for_selected_group(self) -> "None":
        payload = self._current_block_group_payload()
        if not payload:
            self.block_names_edit.clear()
            self.block_rule_status_label.setText("当前没有可配置的群组。")
            return
        rule = self.group_block_rules.get(payload["group_id"]); names = []; self.block_names_edit.blockSignals(True)
        
        self.block_names_edit.setPlainText("\n".join(names)); self.block_names_edit.blockSignals(False)
        if names:
            self.block_rule_status_label.setText(f"已为 {payload["group_name"]} 配置 {len(names)} 个屏蔽下注名称。")
            return
        self.block_rule_status_label.setText(f"{payload["group_name"]} 当前没有屏蔽项。")
    
    def _on_block_group_changed(self) -> "None":
        payload = self._current_block_group_payload()
        if payload:
            self.settings["selected_block_group_key"] = payload["group_id"]
        self._load_block_rule_editor_for_selected_group(); self._refresh_block_rule_summary(); self._save_settings()
    
    def _apply_block_rule_from_editor(self) -> "None":
        payload = self._current_block_group_payload()
        if not payload:
            QMessageBox.information(self, "缺少群组", "请先选择一个已有群组。")
            return
        names = self._sanitize_block_names(self.block_names_edit.toPlainText()); updated = dict(self.group_block_rules); rule_key = payload["group_id"]
        if names:
            updated[rule_key] = {"group_id": payload["group_id"], "group_name": payload["group_name"], "names": names}
            message = f"已为 {payload["group_name"]} 保存 {len(names)} 个屏蔽下注名称。"
        
        else:
            updated.pop(rule_key, None)
            message = f"已清空 {payload["group_name"]} 的屏蔽项。"
        self._set_group_block_rules(updated); self.block_rule_status_label.setText(message)
        self.settings["selected_block_group_key"] = rule_key
        
        self._refresh_block_rule_summary(); self._last_loaded_signature = None
        
        self._save_settings()
        
        self._reload_messages_after_block_rule_change()
        
        logger.info("屏蔽规则已更新: group=%s, names=%d", payload["group_name"], len(names))
    
    def _clear_block_rule_for_selected_group(self) -> "None":
        payload = self._current_block_group_payload()
        if not payload:
            return
        updated = dict(self.group_block_rules); updated.pop(payload["group_id"], None); self._set_group_block_rules(updated); self.block_names_edit.clear(); self.block_rule_status_label.setText(f"已移除 {payload["group_name"]} 的屏蔽项。"); self._refresh_block_rule_summary()
        
        self._last_loaded_signature = None
        
        self._save_settings(); self._reload_messages_after_block_rule_change(); logger.info("屏蔽规则已清除: group=%s", payload["group_name"])
    
    def _refresh_block_rule_summary(self) -> "None":
        if not hasattr(self, "block_rule_summary_view"):
            return
        lines = []
        for rule in sorted(self.group_block_rules.values(), key=(lambda item: (str(item.get("group_name", "")), str(item.get("group_id", ""))))):
            group_id = str(rule.get("group_id", "")).strip()
            group_name = str(rule.get("group_name", "")).strip() or group_id
            names = pass
            if not names:
                pass
            label = group_id and f"{group_name} [{group_id}]"
            lines.append(f"{label}: {", ".join(names)}")
        self.block_rule_summary_view.setPlainText("当前没有屏蔽项。")
    
    def _reload_messages_after_block_rule_change(self) -> "None":
        source_path = self._current_source_path()
        if not self.analysis_page is None and source_path and source_path.exists():
            return
        elif self._active_site:
            self._load_filtered_messages()
            return
        elif self.current_messages:
            options = self._gather_parse_options()
            filtered_messages = self.chat_service.filter_blocked_messages(self.current_messages, self._blocked_names(), [])
            self.current_visual_rows,
                self.current_stats = self.chat_service.analyze_bets(filtered_messages, self._blocked_names(), [], period_filter="", site=self._active_site or "", period_window_start=options.period_window_start, period_window_end=options.period_window_end, period_interval_sec=options.period_interval_sec)
            self._update_chart_data()
            return
