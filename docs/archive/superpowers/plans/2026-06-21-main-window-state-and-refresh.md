# Main Window State And Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent main-window geometry and splitter restore, durable visible-group memory, and lighter 5-second refresh behavior without changing the business statistics contract.

**Architecture:** Extend the existing settings payload with additive UI-state fields, keep the current mixin boundaries, and add helper methods in `MainWindow`, `MainWindowDataMixin`, and `MainWindowActionsMixin` so startup restore and refresh diffing stay local to the UI layer. Use test-first changes in `tests/test_source_recovery.py` to lock the new persistence and no-op refresh behavior before implementation.

**Tech Stack:** Python 3.11, PySide6, pytest, existing main-window mixin architecture

---

### Task 1: Persist Window Geometry And Splitter State

**Files:**
- Modify: `app/services/settings_service.py`
- Modify: `app/ui/main_window.py`
- Modify: `app/ui/main_window_data.py`
- Test: `tests/test_source_recovery.py`

- [ ] **Step 1: Write the failing tests**

Add tests for:

```python
def test_settings_service_load_includes_window_state_defaults() -> None:
    from app.services.settings_service import SettingsService

    data = SettingsService().load()

    assert "window_geometry_b64" in data
    assert "window_state_b64" in data
    assert "main_splitter_sizes" in data


def test_main_window_initial_splitter_restores_saved_sizes() -> None:
    from types import SimpleNamespace

    from app.ui.main_window_data import MainWindowDataMixin

    class DummySplitter:
        def __init__(self) -> None:
            self.applied = None

        def setSizes(self, sizes):
            self.applied = list(sizes)

    dummy = SimpleNamespace(
        main_splitter=DummySplitter(),
        settings={"main_splitter_sizes": [320, 980]},
        width=lambda: 1400,
    )

    MainWindowDataMixin._apply_initial_splitter_sizes(dummy)

    assert dummy.main_splitter.applied == [320, 980]


def test_main_window_initial_splitter_uses_window_ratio_without_saved_sizes() -> None:
    from types import SimpleNamespace

    from app.ui.main_window_data import MainWindowDataMixin

    class DummySplitter:
        def __init__(self) -> None:
            self.applied = None

        def setSizes(self, sizes):
            self.applied = list(sizes)

    dummy = SimpleNamespace(
        main_splitter=DummySplitter(),
        settings={},
        width=lambda: 1500,
    )

    MainWindowDataMixin._apply_initial_splitter_sizes(dummy)

    assert dummy.main_splitter.applied[0] > 0
    assert sum(dummy.main_splitter.applied) == 1500
    assert 300 <= dummy.main_splitter.applied[0] <= 390
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py -k "window_state_defaults or initial_splitter_restores_saved_sizes or initial_splitter_uses_window_ratio_without_saved_sizes" -v
```

Expected: failures because the new settings keys and restore behavior do not exist yet.

- [ ] **Step 3: Implement minimal settings and splitter restore**

Implement:

1. new default keys in `SettingsService.load()`
2. splitter restore helper logic in `MainWindowDataMixin._apply_initial_splitter_sizes()`
3. helper methods in `MainWindow` for saving/restoring geometry and splitter state on show/close

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py -k "window_state_defaults or initial_splitter_restores_saved_sizes or initial_splitter_uses_window_ratio_without_saved_sizes" -v
```

Expected: PASS


### Task 2: Restore Adaptive Window Startup Behavior

**Files:**
- Modify: `app/ui/main_window.py`
- Test: `tests/test_source_recovery.py`

- [ ] **Step 1: Write the failing tests**

Add tests for:

```python
def test_main_window_close_event_persists_window_and_splitter_state() -> None:
    from types import SimpleNamespace

    from app.ui.main_window import MainWindow

    calls = []

    class DummySplitter:
        def sizes(self):
            return [350, 1050]

    dummy = SimpleNamespace(
        main_splitter=DummySplitter(),
        settings={"existing": True},
        _save_settings=lambda: calls.append("saved"),
        saveGeometry=lambda: b"geom",
        saveState=lambda: b"state",
        _refresh_timer=SimpleNamespace(stop=lambda: None),
        _countdown_timer=SimpleNamespace(stop=lambda: None),
        _message_refresh_timer=SimpleNamespace(stop=lambda: None),
        _worker=SimpleNamespace(shutdown=lambda **kwargs: None),
        _data_worker=SimpleNamespace(shutdown=lambda **kwargs: None),
    )

    MainWindow._persist_window_state(dummy)

    assert dummy.settings["main_splitter_sizes"] == [350, 1050]
    assert dummy.settings["window_geometry_b64"]
    assert dummy.settings["window_state_b64"]
    assert calls == ["saved"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py -k "close_event_persists_window_and_splitter_state" -v
```

Expected: FAIL because `_persist_window_state` does not exist.

- [ ] **Step 3: Implement minimal startup and close persistence**

Implement:

1. `MainWindow._persist_window_state()`
2. `MainWindow._restore_window_state()`
3. screen-adaptive fallback sizing when no saved geometry exists
4. `closeEvent()` calling persistence before shutdown

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py -k "close_event_persists_window_and_splitter_state" -v
```

Expected: PASS


### Task 3: Make Group Check State Durable Across Refreshes

**Files:**
- Modify: `app/services/settings_service.py`
- Modify: `app/ui/main_window_actions.py`
- Modify: `app/ui/main_window_data.py`
- Test: `tests/test_source_recovery.py`

- [ ] **Step 1: Write the failing tests**

Add tests for:

```python
def test_main_window_load_groups_prefers_group_check_memory_by_id() -> None:
    from types import SimpleNamespace

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidget

    from app.models import ChatGroup
    from app.ui.main_window_data import MainWindowDataMixin

    class DummyChatService:
        def list_groups_from_db(self, source_path):
            return [ChatGroup(group_id="g1", group_name="群1"), ChatGroup(group_id="g2", group_name="群2")]

    dummy = SimpleNamespace(
        chat_service=DummyChatService(),
        settings={"group_check_memory_by_id": {"g1": True, "g2": False}, "selected_group_mode": "all"},
        group_list=QListWidget(),
        _current_source_path=lambda: __import__("pathlib").Path("dummy.db"),
        _refresh_block_rule_group_selector=lambda: None,
    )

    MainWindowDataMixin._load_groups_from_current_source(dummy)

    assert dummy.group_list.item(0).checkState() == Qt.Checked
    assert dummy.group_list.item(1).checkState() == Qt.Unchecked


def test_main_window_save_settings_persists_group_check_memory_by_id(qtbot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QComboBox, QLineEdit, QListWidget, QListWidgetItem
    from types import SimpleNamespace

    from app.ui.main_window_actions import MainWindowActionsMixin

    class DummySettingsService:
        def __init__(self) -> None:
            self.saved = None

        def save(self, payload):
            self.saved = dict(payload)

    group_list = QListWidget()
    for group_id, checked in [("g1", True), ("g2", False)]:
        item = QListWidgetItem(group_id)
        item.setData(Qt.UserRole, group_id)
        item.setData(Qt.UserRole + 1, group_id)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        group_list.addItem(item)

    service = DummySettingsService()
    dummy = SimpleNamespace(
        settings={},
        settings_service=service,
        username_combo=QComboBox(),
        resolved_path_edit=QLineEdit(),
        manual_db_edit=QLineEdit(),
        group_list=group_list,
        group_block_rules={},
        _global_block_names=lambda: [],
        _settings_datetime_value=lambda attr: "",
        _selected_group_ids=lambda: MainWindowActionsMixin._selected_group_ids(dummy),
        _selected_group_mode=lambda: MainWindowActionsMixin._selected_group_mode(dummy),
        _selected_block_group_key=lambda: "",
        _group_check_memory_payload=lambda: MainWindowActionsMixin._group_check_memory_payload(dummy),
        _current_source_path=lambda: None,
        _query_period_overrides_by_site={},
        _query_period_override="",
        _manual_period_override=False,
        _lock_threshold_sec=20,
        _is_first_launch=False,
    )

    MainWindowActionsMixin._save_settings(dummy)

    assert service.saved["group_check_memory_by_id"] == {"g1": True, "g2": False}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py -k "group_check_memory_by_id" -v
```

Expected: FAIL because durable group memory is not implemented.

- [ ] **Step 3: Implement minimal durable group memory**

Implement:

1. new `group_check_memory_by_id` settings default
2. helper methods in `MainWindowActionsMixin` to read/write current group memory
3. `_load_groups_from_current_source()` preferring durable memory over legacy mode restore

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py -k "group_check_memory_by_id" -v
```

Expected: PASS


### Task 4: Skip No-Op UI Work During 5-Second Refresh

**Files:**
- Modify: `app/ui/main_window_data.py`
- Test: `tests/test_source_recovery.py`

- [ ] **Step 1: Write the failing tests**

Add tests for:

```python
def test_main_window_apply_load_result_skips_ui_refresh_when_payload_is_unchanged() -> None:
    from datetime import datetime
    from types import SimpleNamespace

    from app.models import StatsResult
    from app.ui.main_window_data import MainWindowDataMixin

    calls = {"message": 0, "chart": 0, "stats": 0}
    rows = [
        {
            "row_id": "a",
            "time": datetime(2026, 6, 21, 10, 0, 0),
            "group": "A群",
            "period": "3449001",
            "play": "大单",
            "amount": 100.0,
            "source_kind": "direct",
        }
    ]
    stats = StatsResult(totals={"大单": 100.0})
    dummy = SimpleNamespace(
        current_messages=[],
        current_visual_rows=list(rows),
        current_stats=stats,
        status_label=SimpleNamespace(setText=lambda text: None),
        _active_site="pc28",
        _last_message_cursor={},
        _last_result_signature=None,
        group_robot_ids={},
        _record_raw_chat_messages=lambda messages: None,
        _refresh_message_view=lambda: calls.__setitem__("message", calls["message"] + 1),
        _update_chart_data=lambda replace=False: calls.__setitem__("chart", calls["chart"] + 1),
        _sync_stats_from_accumulated_visual_rows=lambda: calls.__setitem__("stats", calls["stats"] + 1),
        _sync_chart_status=lambda: None,
    )

    result = {
        "current_messages": [],
        "current_visual_rows": list(rows),
        "current_stats": stats,
        "group_robot_ids": {},
        "current_sig": ("sig",),
        "new_cursor": (1, 1),
        "replace_chart": False,
    }

    MainWindowDataMixin._apply_load_result(dummy, result)
    MainWindowDataMixin._apply_load_result(dummy, result)

    assert calls["message"] == 1
    assert calls["chart"] == 1
    assert calls["stats"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py -k "skips_ui_refresh_when_payload_is_unchanged" -v
```

Expected: FAIL because `_apply_load_result()` always refreshes UI paths.

- [ ] **Step 3: Implement minimal refresh diffing**

Implement:

1. result-signature helper methods in `MainWindowDataMixin`
2. skip repeated `_refresh_message_view()`, `_update_chart_data()`, and `_sync_stats_from_accumulated_visual_rows()` when signature is unchanged
3. keep cursor, status label, and active bookkeeping correct even on no-op results

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py -k "skips_ui_refresh_when_payload_is_unchanged" -v
```

Expected: PASS


### Task 5: Run Focused Regression Suite And Document Behavior

**Files:**
- Modify: `docs/bet-statistics-core-logic.md`
- Test: `tests/test_source_recovery.py`

- [ ] **Step 1: Update docs**

Document:

1. window and splitter restore behavior
2. visible-group persistence behavior
3. no-op refresh optimization behavior

- [ ] **Step 2: Run focused regression suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py -k "window_state_defaults or initial_splitter or group_check_memory_by_id or skips_ui_refresh_when_payload_is_unchanged or summary_check or robot_summary" -v
```

Expected: PASS

- [ ] **Step 3: Run compile verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m compileall app tests tools
```

Expected: exit code `0`
