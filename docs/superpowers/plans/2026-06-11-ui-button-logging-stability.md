# UI Button Logging Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the PySide main window readable, adaptive, button-feedback friendly, and debug-loggable.

**Architecture:** Keep the existing mixin-based UI structure. Add focused helper behavior to `MainWindow`, restore user-visible strings in the UI mixins, adjust layout constraints, and cover the repairs with offscreen Qt tests.

**Tech Stack:** Python 3, PySide6, pytest, standard `logging`.

---

## File Structure

- Modify `app/utils/logging_config.py`: readable log setup, debug root level, log-path message.
- Modify `app/ui/main_window.py`: action feedback helpers, readable license/help text, advanced time toggle text.
- Modify `app/ui/main_window_layout.py`: readable labels and adaptive sizing.
- Modify `app/ui/main_window_data.py`: readable data-source messages and action logging.
- Modify `app/ui/main_window_realtime.py`: readable realtime statuses and site card feedback.
- Modify `app/ui/main_window_blocking.py`: readable split regex and block-rule messages.
- Modify `app/ui/chart_window.py`: readable chart labels/statuses and debug click logging.
- Modify `tests/test_source_recovery.py`: update old mojibake assertions to current readable behavior and add smoke coverage.

### Task 1: Logging And UI Helper Tests

- [ ] **Step 1: Write failing tests**

Add tests to `tests/test_source_recovery.py` that assert `logging_config.configure(debug=True)` sets the root logger to `DEBUG`, and `MainWindow._set_status` updates `status_label` and logs.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_source_recovery.py::test_logging_config_debug_sets_root_to_debug tests/test_source_recovery.py::test_main_window_status_helper_updates_label_and_logs -q`

Expected: at least one test fails because the helper does not exist and debug currently leaves root at `INFO`.

- [ ] **Step 3: Implement minimal code**

Update `app/utils/logging_config.py` and add `_set_status`, `_run_ui_action`, and `_reset_button_text_later` to `app/ui/main_window.py`.

- [ ] **Step 4: Verify GREEN**

Run the same pytest command. Expected: both tests pass.

### Task 2: Readable UI Text And Adaptive Layout

- [ ] **Step 1: Write failing tests**

Update/add tests that instantiate `MainWindowLayoutMixin` offscreen and assert readable button/label text, path edits have no narrow maximum widths, and splitter allows a wider left panel.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_source_recovery.py::test_main_window_layout_uses_readable_chinese_labels tests/test_source_recovery.py::test_main_window_layout_splitter_can_expand_left_panel tests/test_source_recovery.py::test_main_window_left_controls_are_not_narrowly_capped -q`

Expected: text and width assertions fail against the mojibake/fixed-width current UI.

- [ ] **Step 3: Implement minimal code**

Restore labels/placeholders in `main_window_layout.py`, remove `setMaximumWidth(360)` and `setMaximumWidth(300)`, add stretch columns and word wrap where needed.

- [ ] **Step 4: Verify GREEN**

Run the same pytest command. Expected: all pass.

### Task 3: Button Feedback And Data Action Messages

- [ ] **Step 1: Write failing tests**

Add tests for `_toggle_advanced_time`, missing username auto-locate, invalid manual source, paging at boundaries, and block-rule save/clear messages using dummy widgets where dialogs can be monkeypatched.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_source_recovery.py::test_main_window_advanced_time_toggle_shows_filter_frame tests/test_source_recovery.py::test_resolve_database_without_username_reports_readable_feedback tests/test_source_recovery.py::test_load_manual_data_source_missing_file_reports_readable_feedback tests/test_source_recovery.py::test_block_rule_save_and_clear_use_readable_feedback -q`

Expected: readable text assertions fail.

- [ ] **Step 3: Implement minimal code**

Update action/data/blocking/realtime/chart strings and add debug/info logs around button handlers. Use `_set_status` for visible status updates where `status_label` exists.

- [ ] **Step 4: Verify GREEN**

Run the same pytest command. Expected: all pass.

### Task 4: End-To-End Smoke Verification

- [ ] **Step 1: Write failing test**

Add an offscreen smoke test that creates `MainWindow`, lists all `QPushButton` texts, and clicks safe buttons while excluding native-dialog buttons and destructive/manual-dialog actions.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_source_recovery.py::test_main_window_safe_buttons_click_without_crashing -q`

Expected: current UI fails because at least one safe button path has unreadable/missing feedback or errors.

- [ ] **Step 3: Implement final fixes**

Patch remaining button handlers discovered by the smoke test without changing service behavior.

- [ ] **Step 4: Verify all**

Run:

```powershell
python -m compileall app tests
python -m pytest -q
```

Expected: compile succeeds and pytest passes.
