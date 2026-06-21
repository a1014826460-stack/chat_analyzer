from __future__ import annotations

import logging

from app.services.storage_service import JsonStore


logger = logging.getLogger(__name__)


class SettingsService:
    def __init__(self) -> None:
        self.store = JsonStore("settings.json")

    def load(self) -> dict:
        data = self.store.load(
            {
                "username": "",
                "recent_usernames": [],
                "data_source": "",
                "db_dir": "",
                "export_dir": "",
                "blocked_names": [],
                "global_block_names": [],
                "blocked_names_by_group": {},
                "group_types_by_id": {},
                "group_type_switches_by_id": {},
                "group_robot_ids": {},
                "selected_group_ids": [],
                "selected_group_mode": "",
                "selected_group_name": "",
                "selected_block_group_key": "",
                "group_check_memory_by_id": {},
                "fallback_db_path": "",
                "query_period_override": "",
                "manual_period_override": False,
                "query_period_overrides_by_site": {},
                "advanced_time_filter_enabled": False,
                "advanced_time_start": "",
                "advanced_time_end": "",
                "window_geometry_b64": "",
                "window_state_b64": "",
                "main_splitter_sizes": [],
                "lock_threshold_sec": 20,
                "is_first_launch": True,
                "proxy_enabled": False,
                "proxy_http": "",
                "proxy_https": "",
            }
        )

        logger.debug(
            "加载设置: username=%s, blocked_groups=%d, groups=%d, proxy=%s",
            data.get("username"),
            len(data.get("blocked_names_by_group", {})),
            len(data.get("selected_group_ids", [])),
            data.get("proxy_enabled"),
        )
        return data

    def save(self, payload: dict) -> None:
        self.store.save(payload)
        logger.debug("保存设置: username=%s", payload.get("username", ""))
