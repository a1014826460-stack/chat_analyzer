# Raw Chat Dialog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move raw chat browsing out of the always-visible main window area into an on-demand dialog with group filtering and paging.

**Architecture:** Add a focused `RawChatDialog` widget that owns raw-message rendering, pagination, and group filtering. Keep the main window responsible for loading data and opening/updating the dialog with `current_messages`.

**Tech Stack:** Python, PySide6, pytest.

---

### Task 1: Add Raw Chat Dialog

**Files:**
- Create: `app/ui/raw_chat_dialog.py`
- Test: `tests/test_source_recovery.py`

- [ ] **Step 1: Write the failing test**

Add a test that constructs `RawChatDialog` with two messages from different groups, verifies the required header format, verifies user nickname and user ID are shown separately, and verifies group filtering narrows the displayed messages.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_source_recovery.py::test_raw_chat_dialog_formats_and_filters_messages -q`

Expected: FAIL because `app.ui.raw_chat_dialog` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Create `RawChatDialog` with:
- `QComboBox` group filter containing `全部群组` plus unique message groups.
- `QTextEdit` read-only message view.
- `上一页` / `下一页` buttons and page label.
- Message HTML format: `时间 | 群组 | 用户nickname | 用户ID` then content on the next line.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_source_recovery.py::test_raw_chat_dialog_formats_and_filters_messages -q`

Expected: PASS.

### Task 2: Replace Inline Main Window Raw Chat Panel With Dialog Entry

**Files:**
- Modify: `app/ui/main_window_layout.py`
- Modify: `app/ui/main_window_actions.py`
- Test: `tests/test_source_recovery.py`

- [ ] **Step 1: Write the failing test**

Add a test that calls `_open_raw_chat_dialog()` on a dummy main-window object with `current_messages`, verifies a dialog object is created, and verifies later calls update the same dialog instance.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_source_recovery.py::test_main_window_opens_and_reuses_raw_chat_dialog -q`

Expected: FAIL because `_open_raw_chat_dialog` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

In layout, replace the always-visible `message_frame/result_view/pager` block with an `原始聊天记录` button wired to `_open_raw_chat_dialog`.

In actions, add `_open_raw_chat_dialog()` that creates `RawChatDialog(self.current_messages, self)` on first use, otherwise calls `set_messages(self.current_messages)`, then shows/raises/activates it.

- [ ] **Step 4: Run target tests**

Run:
- `python -m pytest tests/test_source_recovery.py::test_raw_chat_dialog_formats_and_filters_messages -q`
- `python -m pytest tests/test_source_recovery.py::test_main_window_opens_and_reuses_raw_chat_dialog -q`

Expected: both PASS.

### Task 3: Regression Verification

**Files:**
- No additional files.

- [ ] **Step 1: Run focused UI tests**

Run: `python -m pytest tests/test_source_recovery.py -q`

Expected: PASS.

- [ ] **Step 2: Compile changed Python files**

Run: `python -m py_compile app/ui/raw_chat_dialog.py app/ui/main_window_layout.py app/ui/main_window_actions.py`

Expected: no output and exit code 0.
