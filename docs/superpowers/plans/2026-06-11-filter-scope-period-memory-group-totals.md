# Filter Scope, Period Memory, And Group Totals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate global and group block-list scope, persist period overrides per site, and expose true grouped totals without rewriting the current PySide main-window/service architecture.

**Architecture:** Keep the current mixin-based main window and `ChatLogService` pipeline, but make three additive corrections: treat `blocked_names` as global-only data, store period overrides in a site-keyed map, and extend `StatsResult` with grouped totals derived from the already-built `visual_rows`. Preserve compatibility with existing settings and existing callers that only read `stats.totals`.

**Tech Stack:** Python, PySide6, pytest, dataclasses, sqlite3

---

## File Map

- `app/models/chat.py`
  - Owns `ParseOptions` and `StatsResult`.
  - This plan adds a global-block alias on `ParseOptions` and a grouped-totals field on `StatsResult`.
- `app/services/settings_service.py`
  - Owns settings defaults.
  - This plan adds `global_block_names` and `query_period_overrides_by_site`.
- `app/services/chat_service.py`
  - Owns block filtering and bet aggregation.
  - This plan fixes scope leakage and adds `totals_by_group`.
- `app/ui/main_window.py`
  - Owns runtime state initialization.
  - This plan initializes `global_block_names` and `query_period_overrides_by_site`.
- `app/ui/main_window_layout.py`
  - Owns widget construction.
  - This plan adds a global block-list editor above the existing group-specific editor.
- `app/ui/main_window_blocking.py`
  - Owns block-list normalization, editing, summaries, and reload hooks.
  - This plan separates global and group block-list helpers.
- `app/ui/main_window_data.py`
  - Owns initial-state restore and parse-option assembly.
  - This plan restores site-keyed period overrides and stops flattening group rules into global filtering.
- `app/ui/main_window_realtime.py`
  - Owns site switch behavior and period-input syncing.
  - This plan derives manual override state per site and keeps overrides when switching sites.
- `app/ui/main_window_actions.py`
  - Owns settings persistence.
  - This plan saves new settings keys and drops the old overloaded save behavior.
- `tests/test_source_recovery.py`
  - Owns regression coverage.
  - This plan adds tests for block scope, period memory, and grouped totals.
- `docs/chat_analysis_mechanisms.md`
  - Owns code-grounded behavior docs.
  - This plan updates current-state notes once implementation lands.

### Task 1: Separate Global And Group Block Lists

**Files:**
- Modify: `tests/test_source_recovery.py`
- Modify: `app/services/settings_service.py`
- Modify: `app/models/chat.py`
- Modify: `app/ui/main_window.py`
- Modify: `app/ui/main_window_layout.py`
- Modify: `app/ui/main_window_blocking.py`
- Modify: `app/ui/main_window_data.py`
- Modify: `app/ui/main_window_actions.py`
- Modify: `app/services/chat_service.py`

- [ ] **Step 1: Write the failing tests for block scope**

Add these tests to `tests/test_source_recovery.py` near the existing block/filter tests:

```python
def test_main_window_data_gather_parse_options_does_not_flatten_group_rules_into_global_names() -> None:
    from PySide6.QtCore import Qt

    from app.ui.main_window_data import MainWindowDataMixin

    class DummyItem:
        def __init__(self, checked: bool, group_id: str, group_name: str) -> None:
            self._checked = checked
            self._group_id = group_id
            self._group_name = group_name

        def checkState(self):
            return Qt.Checked if self._checked else Qt.Unchecked

        def data(self, role):
            return {32: self._group_id, 33: self._group_name}.get(role)

        def text(self):
            return self._group_name

    class DummyList:
        def __init__(self) -> None:
            self.items = [DummyItem(True, "g1", "GroupA")]

        def count(self):
            return len(self.items)

        def item(self, index):
            return self.items[index]

    class DummyCombo:
        def currentText(self):
            return "Alice"

    class DummyText:
        def text(self):
            return "9001"

    class DummyWindow(MainWindowDataMixin):
        def _global_block_names(self):
            return []

    dummy = DummyWindow()
    dummy.group_list = DummyList()
    dummy.username_combo = DummyCombo()
    dummy.period_input = DummyText()
    dummy.group_block_rules = {"g1": {"group_id": "g1", "group_name": "GroupA", "names": ["Blocked"]}}
    dummy._active_site = "pc28"

    options = dummy._gather_parse_options()

    assert options.blocked_names == []
    assert options.global_block_names == []
    assert options.blocked_names_by_group == {
        "g1": {"group_id": "g1", "group_name": "GroupA", "names": ["Blocked"]}
    }


def test_main_window_actions_save_settings_persists_global_block_names_separately() -> None:
    from types import SimpleNamespace

    from app.ui.main_window_actions import MainWindowActionsMixin

    saved_payloads: list[dict[str, object]] = []

    class DummyService:
        def save(self, payload):
            saved_payloads.append(payload)

    class DummyCombo:
        def currentText(self):
            return "Alice"

        def count(self):
            return 1

        def itemText(self, index: int):
            return "Alice"

    class DummyText:
        def text(self):
            return ""

    class DummyWindow(MainWindowActionsMixin):
        def _current_source_path(self):
            return None

        def _selected_group_ids(self):
            return ["g1"]

        def _selected_block_group_key(self):
            return "g1"

        def _global_block_names(self):
            return ["Robot"]

    dummy = DummyWindow()
    dummy.settings_service = DummyService()
    dummy.username_combo = DummyCombo()
    dummy.resolved_path_edit = DummyText()
    dummy.manual_db_edit = DummyText()
    dummy.settings = {"export_dir": "", "proxy_enabled": False, "proxy_http": "", "proxy_https": ""}
    dummy.group_block_rules = {"g1": {"group_id": "g1", "group_name": "GroupA", "names": ["Blocked"]}}
    dummy._lock_threshold_sec = 20
    dummy._is_first_launch = False
    dummy._query_period_overrides_by_site = {}

    dummy._save_settings()

    payload = saved_payloads[-1]
    assert payload["global_block_names"] == ["Robot"]
    assert payload["blocked_names"] == ["Robot"]
    assert payload["blocked_names_by_group"] == {
        "g1": {"group_id": "g1", "group_name": "GroupA", "names": ["Blocked"]}
    }


def test_chat_service_global_block_list_applies_to_all_groups() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 11, 10, 0, 0),
            group="GroupA",
            username="Robot",
            sender_id="robot-a",
            content="大10 1001",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 11, 10, 0, 5),
            group="GroupB",
            username="Robot",
            sender_id="robot-b",
            content="大20 1001",
        ),
    ]

    filtered = service.filter_blocked_messages(messages, blocked_names=["Robot"], blocked_ids=[])

    assert filtered == []
```

- [ ] **Step 2: Run the new block-scope tests and verify they fail**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -k "does_not_flatten_group_rules_into_global_names or persists_global_block_names_separately or global_block_list_applies_to_all_groups" -v
```

Expected:

- `test_main_window_data_gather_parse_options_does_not_flatten_group_rules_into_global_names` fails because the current implementation still flattens group rules into `blocked_names`.
- `test_main_window_actions_save_settings_persists_global_block_names_separately` fails because `_save_settings()` still serializes flattened group names through `_blocked_names()`.

- [ ] **Step 3: Add the new settings defaults and parse-option alias**

Update `app/services/settings_service.py` defaults and `app/models/chat.py` dataclasses with this shape:

```python
class SettingsService:
    def load(self) -> "dict":
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
                "selected_group_ids": [],
                "selected_group_name": "",
                "selected_block_group_key": "",
                "fallback_db_path": "",
                "query_period_override": "",
                "manual_period_override": False,
                "query_period_overrides_by_site": {},
                "lock_threshold_sec": 20,
                "is_first_launch": True,
                "proxy_enabled": False,
                "proxy_http": "",
                "proxy_https": "",
            }
        )
        return data
```

```python
@dataclass
class ParseOptions:
    username: str = ""
    groups: list[str] = field(default_factory=list)
    blocked_names: list[str] = field(default_factory=list)
    blocked_names_by_group: dict[str, dict[str, object]] = field(default_factory=dict)
    group_ids: list[str] = field(default_factory=list)
    blocked_user_ids: list[str] = field(default_factory=list)
    start_time: datetime | None = None
    end_time: datetime | None = None
    period_filter: str = ""
    site: str = ""
    period_window_start: datetime | None = None
    period_window_end: datetime | None = None
    period_interval_sec: int = 0
    incremental_since: datetime | None = None
    incremental_cursor_value: int = 0
    incremental_cursor_rand: int = 0

    @property
    def global_block_names(self) -> list[str]:
        return self.blocked_names

    @property
    def blacklist_users(self) -> list[str]:
        return self.global_block_names

    @property
    def masked_bettors(self) -> list[str]:
        return self.global_block_names
```

- [ ] **Step 4: Wire a dedicated global block-list editor into the main window**

Update `app/ui/main_window.py`, `app/ui/main_window_layout.py`, `app/ui/main_window_blocking.py`, `app/ui/main_window_data.py`, and `app/ui/main_window_actions.py` with this structure:

```python
# app/ui/main_window.py
self.global_block_names: list[str] = self._sanitize_block_names(
    self.settings.get("global_block_names", self.settings.get("blocked_names", []))
)
self._set_group_block_rules(self.settings.get("blocked_names_by_group", {}))
```

```python
# app/ui/main_window_layout.py
global_row = QHBoxLayout()
global_row.addWidget(QLabel("全局"))
self.global_block_names_edit = QTextEdit()
self.global_block_names_edit.setPlaceholderText("全局屏蔽名称，每行一个，也可用逗号/分号分隔")
self.global_block_names_edit.setMaximumHeight(90)
block_layout.addLayout(global_row)
block_layout.addWidget(self.global_block_names_edit)

global_btn_row = QHBoxLayout()
self.global_block_save_btn = QPushButton("保存全局")
self.global_block_save_btn.clicked.connect(self._apply_global_block_names_from_editor)
self.global_block_clear_btn = QPushButton("清空全局")
self.global_block_clear_btn.clicked.connect(self._clear_global_block_names)
global_btn_row.addWidget(self.global_block_save_btn)
global_btn_row.addWidget(self.global_block_clear_btn)
global_btn_row.addStretch(1)
block_layout.addLayout(global_btn_row)
```

```python
# app/ui/main_window_blocking.py
def _set_global_block_names(self, values: object) -> None:
    self.global_block_names = self._sanitize_block_names(values)

def _global_block_names(self) -> list[str]:
    return list(self.global_block_names)

def _apply_global_block_names_from_editor(self) -> None:
    names = self._sanitize_block_names(self.global_block_names_edit.toPlainText())
    self._set_global_block_names(names)
    self.global_block_names_edit.setPlainText("\n".join(names))
    self.block_rule_status_label.setText(f"已保存 {len(names)} 个全局屏蔽名称。")
    self._refresh_block_rule_summary()
    self._save_settings()
    self._reload_messages_after_block_rule_change()

def _clear_global_block_names(self) -> None:
    self._set_global_block_names([])
    self.global_block_names_edit.clear()
    self.block_rule_status_label.setText("已清空全局屏蔽名称。")
    self._refresh_block_rule_summary()
    self._save_settings()
    self._reload_messages_after_block_rule_change()
```

```python
# app/ui/main_window_data.py
return ParseOptions(
    username=self.username_combo.currentText().strip(),
    groups=selected_groups,
    blocked_names=self._global_block_names(),
    blocked_names_by_group=self.group_block_rules,
    group_ids=selected_group_ids,
    blocked_user_ids=[],
    period_filter=period_filter,
    site=site,
    period_interval_sec=period_interval_sec,
)
```

```python
# app/ui/main_window_actions.py
"global_block_names": self._global_block_names(),
"blocked_names": self._global_block_names(),
"blocked_names_by_group": self.group_block_rules,
```

- [ ] **Step 5: Fix service-side filtering so scopes stay separate**

Update `app/services/chat_service.py` so global filtering and group filtering stay independent:

```python
def filter_blocked_messages(
    self,
    messages: list[ChatMessage],
    blocked_names: list[str],
    blocked_ids: list[str] | None,
) -> list[ChatMessage]:
    global_block_name_keys = {self._normalize_text(name) for name in blocked_names}
    blocked_id_keys = {self._normalize_text(item) for item in (blocked_ids or [])}
    filtered: list[ChatMessage] = []
    for msg in messages:
        if self._normalize_text(msg.username) in global_block_name_keys:
            continue
        if self._normalize_text(msg.sender_id) in blocked_id_keys:
            continue
        if self._is_group_blocked_name(msg.group, msg.username):
            continue
        filtered.append(msg)
    return filtered

def extract_bet_visual_data(
    self,
    messages: list[ChatMessage],
    blocked_names: list[str],
    blocked_ids: list[str] | None,
    period_filter: str,
    site: str,
    period_window_start: datetime | None,
    period_window_end: datetime | None,
    period_interval_sec: int,
) -> list[dict[str, object]]:
    global_block_name_set = {self._normalize_text(name) for name in blocked_names}
    blocked_id_set = {self._normalize_text(item) for item in (blocked_ids or [])}
    ...
    if normalized_source_name in global_block_name_set:
        continue
    if normalized_source_name in group_block_names:
        continue
```

- [ ] **Step 6: Run the targeted block-scope tests until they pass**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -k "does_not_flatten_group_rules_into_global_names or persists_global_block_names_separately or global_block_list_applies_to_all_groups" -v
```

Expected:

- all 3 tests pass

- [ ] **Step 7: Commit the block-scope repair**

Run:

```bash
git add tests/test_source_recovery.py app/services/settings_service.py app/models/chat.py app/ui/main_window.py app/ui/main_window_layout.py app/ui/main_window_blocking.py app/ui/main_window_data.py app/ui/main_window_actions.py app/services/chat_service.py
git commit -m "fix: separate global and group block scopes"
```

### Task 2: Persist Period Overrides Per Site

**Files:**
- Modify: `tests/test_source_recovery.py`
- Modify: `app/services/settings_service.py`
- Modify: `app/ui/main_window.py`
- Modify: `app/ui/main_window_data.py`
- Modify: `app/ui/main_window_realtime.py`
- Modify: `app/ui/main_window_actions.py`

- [ ] **Step 1: Write the failing tests for per-site period memory**

Add these tests to `tests/test_source_recovery.py` near the current period-input tests:

```python
def test_main_window_data_load_initial_state_restores_period_override_map() -> None:
    from app.ui.main_window_data import MainWindowDataMixin

    class DummyCombo:
        def __init__(self) -> None:
            self.items: list[str] = []
            self.current = ""

        def clear(self) -> None:
            self.items = []

        def addItems(self, values) -> None:
            self.items.extend(values)

        def setCurrentText(self, value: str) -> None:
            self.current = value

    class DummyEdit:
        def __init__(self) -> None:
            self.value = ""

        def setText(self, value: str) -> None:
            self.value = value

    class DummyDateTimeEdit:
        def __init__(self) -> None:
            self.value = None

        def setDateTime(self, value) -> None:
            self.value = value

    class DummyTabs:
        def __init__(self) -> None:
            self.current = None

        def setCurrentWidget(self, widget) -> None:
            self.current = widget

    class DummyLicenseService:
        def is_activated(self) -> bool:
            return False

    class DummyWindow(MainWindowDataMixin):
        def _refresh_block_rule_summary(self) -> None:
            return None

        def _refresh_block_rule_group_selector(self) -> None:
            return None

        def _refresh_license_banner(self) -> None:
            return None

        def _resolve_database(self, silent=False) -> None:
            self.resolve_called = silent

    dummy = DummyWindow()
    dummy.analysis_page = object()
    dummy.settings = {
        "recent_usernames": ["Alice"],
        "username": "Alice",
        "fallback_db_path": "D:/db.sqlite",
        "query_period_overrides_by_site": {"pc28": "7788"},
    }
    dummy.username_combo = DummyCombo()
    dummy.manual_db_edit = DummyEdit()
    dummy.resolved_path_edit = DummyEdit()
    dummy.period_input = DummyEdit()
    dummy.start_edit = DummyDateTimeEdit()
    dummy.end_edit = DummyDateTimeEdit()
    dummy.tabs = DummyTabs()
    dummy.license_page = object()
    dummy._query_period_override = ""
    dummy._manual_period_override = False
    dummy._query_period_overrides_by_site = {}
    dummy._active_site = "pc28"
    dummy._require_activation = True
    dummy.license_service = DummyLicenseService()

    dummy._load_initial_state()

    assert dummy._query_period_overrides_by_site == {"pc28": "7788"}
    assert dummy.period_input.value == "7788"


def test_main_window_realtime_period_override_is_stored_per_site() -> None:
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    class DummyPeriodInput:
        def __init__(self) -> None:
            self.value = ""
            self.blocked = False

        def blockSignals(self, value: bool) -> None:
            self.blocked = value

        def setText(self, value: str) -> None:
            self.value = value

        def text(self) -> str:
            return self.value

    dummy = SimpleNamespace(
        _active_site="pc28",
        _query_period_overrides_by_site={"pc28": "7788", "macao": "8899"},
        _draw_infos={
            "pc28": DrawInfo(current_period="1001", next_period="1002"),
            "macao": DrawInfo(current_period="2001", next_period="2002"),
        },
        period_input=DummyPeriodInput(),
        active_site_label=SimpleNamespace(setText=lambda value: None),
        active_period_label=SimpleNamespace(setText=lambda value: None),
        next_period_label=SimpleNamespace(setText=lambda value: None),
        countdown_label=SimpleNamespace(setText=lambda value: None),
        lock_status_label=SimpleNamespace(setText=lambda value: None),
        auto_refresh_label=SimpleNamespace(setText=lambda value: None, setStyleSheet=lambda value: None),
        chart_window=SimpleNamespace(set_status=lambda *args, **kwargs: None, set_status_seconds=lambda *args, **kwargs: None),
        current_visual_rows=[],
        _stats_locked=False,
        _last_message_cursor={},
        _awaiting_next_period=False,
        _format_countdown=lambda value: "00:00",
        _set_status=lambda *args, **kwargs: None,
        _load_filtered_messages=lambda: None,
        _sync_chart_status=lambda: None,
    )
    dummy._refresh_active_site_info = lambda: MainWindowRealtimeMixin._refresh_active_site_info(dummy)

    MainWindowRealtimeMixin._refresh_active_site_info(dummy)
    assert dummy.period_input.value == "7788"

    MainWindowRealtimeMixin._select_site(dummy, "macao")
    assert dummy.period_input.value == "8899"
    assert dummy._query_period_overrides_by_site["pc28"] == "7788"
```

- [ ] **Step 2: Run the new period-memory tests and verify they fail**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -k "restores_period_override_map or period_override_is_stored_per_site" -v
```

Expected:

- the initial-state test fails because `_load_initial_state()` only reads `_query_period_override`
- the realtime test fails because `_select_site()` clears period override state

- [ ] **Step 3: Add the new runtime state and settings persistence**

Update `app/services/settings_service.py`, `app/ui/main_window.py`, and `app/ui/main_window_actions.py` like this:

```python
# app/ui/main_window.py
self._query_period_overrides_by_site = {
    str(key): str(value).strip()
    for key, value in dict(self.settings.get("query_period_overrides_by_site", {})).items()
    if str(value).strip()
}
legacy_period = str(self.settings.get("query_period_override", "")).strip()
legacy_manual = bool(self.settings.get("manual_period_override", False))
if legacy_manual and legacy_period and "pc28" not in self._query_period_overrides_by_site:
    self._query_period_overrides_by_site["pc28"] = legacy_period
```

```python
# app/ui/main_window_actions.py
"query_period_overrides_by_site": dict(self._query_period_overrides_by_site),
"query_period_override": "",
"manual_period_override": False,
```

- [ ] **Step 4: Replace global period-override behavior with site-keyed helpers**

Update `app/ui/main_window_data.py` and `app/ui/main_window_realtime.py` with helper-driven logic:

```python
# app/ui/main_window_data.py
def _load_initial_state(self) -> None:
    ...
    overrides_raw = self.settings.get("query_period_overrides_by_site", {})
    if isinstance(overrides_raw, dict):
        self._query_period_overrides_by_site = {
            str(key): str(value).strip()
            for key, value in overrides_raw.items()
            if str(value).strip()
        }
    if hasattr(self, "period_input"):
        current_override = self._query_period_overrides_by_site.get(self._active_site or "", "")
        self.period_input.setText(current_override)
```

```python
# app/ui/main_window_realtime.py
def _current_period_override(self) -> str:
    return str(self._query_period_overrides_by_site.get(self._active_site or "", "")).strip()

def _has_manual_period_override(self) -> bool:
    return bool(self._current_period_override())

def _select_site(self, site: str) -> None:
    logger.info("Switch site: %s", site)
    self._active_site = site
    self._stats_locked = False
    self._awaiting_next_period = False
    self._last_message_cursor.pop(site, None)
    self.lock_status_label.setText("")
    self.auto_refresh_label.setText("自动刷新")
    self.auto_refresh_label.setStyleSheet("")
    self._refresh_active_site_info()
    if hasattr(self, "_set_status"):
        self._set_status(f"已切换线路: {site_label(site)}", "info")
    self._load_filtered_messages()

def _sync_period_input_from_site(self, info: DrawInfo) -> None:
    override = self._current_period_override()
    text = override or self._default_query_period(info)
    self.period_input.blockSignals(True)
    self.period_input.setText(text)
    self.period_input.blockSignals(False)

def _on_period_input_changed(self) -> None:
    if not self._active_site:
        return
    value = self.period_input.text().strip()
    if value:
        self._query_period_overrides_by_site[self._active_site] = value
    else:
        self._query_period_overrides_by_site.pop(self._active_site, None)
    logger.debug("Query period changed: site=%s period=%s", self._active_site, value)
    self._save_settings()
```

- [ ] **Step 5: Run the targeted period-memory tests until they pass**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -k "restores_period_override_map or period_override_is_stored_per_site" -v
```

Expected:

- both tests pass

- [ ] **Step 6: Commit the per-site period-memory repair**

Run:

```bash
git add tests/test_source_recovery.py app/services/settings_service.py app/ui/main_window.py app/ui/main_window_data.py app/ui/main_window_realtime.py app/ui/main_window_actions.py
git commit -m "fix: persist query period per site"
```

### Task 3: Extend StatsResult With Grouped Totals

**Files:**
- Modify: `tests/test_source_recovery.py`
- Modify: `app/models/chat.py`
- Modify: `app/services/chat_service.py`
- Modify: `app/ui/main_window.py`

- [ ] **Step 1: Write the failing grouped-totals tests**

Add these tests to `tests/test_source_recovery.py` near the existing `analyze_bets()` coverage:

```python
def test_chat_service_analyze_bets_returns_totals_by_group() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 11, 12, 0, 0),
            group="GroupA",
            username="Alice",
            sender_id="alice-1",
            content="大10 1001",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 11, 12, 0, 5),
            group="GroupB",
            username="Bob",
            sender_id="bob-1",
            content="小20 1001",
        ),
    ]

    rows, stats = service.analyze_bets(
        messages,
        blocked_names=[],
        blocked_ids=[],
        period_filter="",
        site="",
        period_window_start=None,
        period_window_end=None,
        period_interval_sec=0,
    )

    assert len(rows) == 2
    assert stats.totals == {"大": 10.0, "小": 20.0}
    assert stats.totals_by_group == {
        "GroupA": {"大": 10.0},
        "GroupB": {"小": 20.0},
    }
```

- [ ] **Step 2: Run the grouped-totals test and verify it fails**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -k "returns_totals_by_group" -v
```

Expected:

- failure because `StatsResult` does not yet expose `totals_by_group`

- [ ] **Step 3: Extend the stats dataclass and aggregate grouped totals**

Update `app/models/chat.py`, `app/services/chat_service.py`, and `app/ui/main_window.py` with this shape:

```python
@dataclass
class StatsResult:
    totals: dict[str, float]
    totals_by_group: dict[str, dict[str, float]] = field(default_factory=dict)
    matched_messages: int = 0
    exported_records: int = 0
```

```python
def analyze_bets(
    self,
    messages: list[ChatMessage],
    blocked_names: list[str],
    blocked_ids: list[str] | None,
    period_filter: str,
    site: str,
    period_window_start: datetime | None,
    period_window_end: datetime | None,
    period_interval_sec: int,
) -> tuple[list[dict[str, object]], StatsResult]:
    filtered = self.filter_blocked_messages(messages, blocked_names, blocked_ids)
    visual_rows = self.extract_bet_visual_data(
        filtered,
        blocked_names=blocked_names,
        blocked_ids=blocked_ids,
        period_filter=period_filter,
        site=site,
        period_window_start=period_window_start,
        period_window_end=period_window_end,
        period_interval_sec=period_interval_sec,
    )
    totals: dict[str, float] = defaultdict(float)
    totals_by_group: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in visual_rows:
        play = str(row["play"])
        group = str(row.get("group", "") or "")
        amount = float(row["amount"])
        totals[play] += amount
        if group:
            totals_by_group[group][play] += amount
    return visual_rows, StatsResult(
        totals=dict(totals),
        totals_by_group={group: dict(group_totals) for group, group_totals in totals_by_group.items()},
        matched_messages=len(filtered),
    )
```

```python
# app/ui/main_window.py
self.current_stats = StatsResult(totals={}, totals_by_group={})
```

- [ ] **Step 4: Run the grouped-totals tests and nearby regressions**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -k "returns_totals_by_group or receipt_group_keeps_latest_amount_per_bettor_period_play or direct_group_accumulates_amount_per_bettor_period_play or cancel_removes_receipt_group_latest_row_without_residue" -v
```

Expected:

- the new grouped-totals test passes
- the existing totals tests still pass unchanged

- [ ] **Step 5: Commit the grouped-totals extension**

Run:

```bash
git add tests/test_source_recovery.py app/models/chat.py app/services/chat_service.py app/ui/main_window.py
git commit -m "feat: add grouped bet totals"
```

### Task 4: Sync Docs And Run Full Verification

**Files:**
- Modify: `docs/chat_analysis_mechanisms.md`
- Modify: `CONTEXT.md`
- Modify: `tests/test_source_recovery.py` if any names need cleanup during final pass

- [ ] **Step 1: Update the mechanism docs to remove resolved mismatch notes**

Edit `docs/chat_analysis_mechanisms.md` so the current-state sections reflect the implemented behavior:

```md
### 4.1 当前实现

- `全局屏蔽名单` 通过独立设置项保存，并对所有群统一生效。
- `群组屏蔽名单` 只在对应群组内生效，不再泄漏成全局过滤。

### 5.5 右侧“期号筛选”

当前行为：

- 默认跟随当前线路下一期
- 手动输入后只覆盖当前线路
- 切换线路时恢复该线路自己的历史输入
- 设置持久化时使用 `query_period_overrides_by_site`

### 6. 已对齐实现

1. 屏蔽名单已分成“全局屏蔽名单”和“群组屏蔽名单”，作用域互不泄漏。
2. 期号筛选已按线路分别记忆。
3. `StatsResult` 已提供 `totals_by_group`。
```

- [ ] **Step 2: Run the full test suite**

Run:

```bash
.\.venv\Scripts\python.exe -m pytest -q
```

Expected:

- all tests pass

- [ ] **Step 3: Run compile verification**

Run:

```bash
.\.venv\Scripts\python.exe -m compileall app tests
```

Expected:

- no syntax errors

- [ ] **Step 4: Commit final doc sync and verification-safe changes**

Run:

```bash
git add docs/chat_analysis_mechanisms.md CONTEXT.md tests/test_source_recovery.py
git commit -m "docs: sync filter scope and grouped totals behavior"
```

## Self-Review Checklist

- Task 1 covers the spec requirement that global and group block scope be separated without changing the whole service interface.
- Task 2 covers the spec requirement that period overrides be persisted per site with legacy fallback.
- Task 3 covers the spec requirement that `StatsResult` expose grouped totals while preserving `stats.totals`.
- Task 4 covers documentation sync and whole-project verification.
- No execution step leaves unresolved placeholders or vague follow-up work.
- Function and field names are consistent across tasks:
  - `global_block_names`
  - `blocked_names_by_group`
  - `query_period_overrides_by_site`
  - `totals_by_group`
