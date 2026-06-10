# Source Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the damaged `app/` source tree from the decompiled recovery output, then hand-repair the highest-risk modules so the project source is compilable again.

**Architecture:** Use the extracted `pyc` recovery output as the primary source of truth, but only copy files back into `app/` after a failing regression test exists. Treat cleanly decompiled modules as direct replacements, and treat damaged decompilations as reconstruction targets guided by surrounding modules plus `dis`/`pyasm` output.

**Tech Stack:** Python 3.11, pytest, apply_patch, decompiled source in `.codex_recovery/recovered_src`, disassembly artifacts in `.codex_recovery/recovered_src/disassembly`

---

### Task 1: Establish Recovery Safety Net

**Files:**
- Create: `tests/test_source_recovery.py`
- Create: `docs/superpowers/plans/2026-06-10-source-recovery.md`

- [ ] **Step 1: Write the failing test**

Create a test module that:
- asserts critical `app/` source files compile with `py_compile`
- asserts `app/services/chat_service.py` defines `ChatLogService` with the expected public API
- asserts `app/ui/main_window_data.py` defines `MainWindowDataMixin` with the expected methods

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_source_recovery.py -q`
Expected: FAIL because the current damaged source contains null bytes / syntax errors / missing APIs

- [ ] **Step 3: Keep the test as the regression gate**

Do not relax the test. Make code changes satisfy the existing test.

### Task 2: Restore Direct-Replacement Modules

**Files:**
- Modify: `app/build_config.py`
- Modify: `app/models/__init__.py`
- Modify: `app/models/chat.py`
- Modify: `app/services/settings_service.py`
- Modify: `app/services/storage_service.py`
- Modify: `app/utils/logging_config.py`
- Modify: `app/utils/pathing.py`
- Modify: `app/utils/protection.py`
- Modify: `app/utils/proxy.py`
- Modify: `app/ui/main_window_theme.py`
- Reference: `.codex_recovery/recovered_src/decompiled/app/**/*`

- [ ] **Step 1: Replace obviously damaged files with clean recovered source**

Copy back the decompiled files that already compile or only require no semantic reconstruction.

- [ ] **Step 2: Re-run the targeted regression test**

Run: `python -m pytest tests/test_source_recovery.py -q`
Expected: still FAIL, but with fewer compile failures focused on higher-risk files

### Task 3: Repair Syntax-Damaged Decompilations Around the UI/Services Perimeter

**Files:**
- Modify: `app/main.py`
- Modify: `app/services/license_service.py`
- Modify: `app/services/account_resolver.py`
- Modify: `app/ui/main_window.py`
- Modify: `app/ui/chart_window.py`
- Modify: `app/ui/license_generator_dialog.py`
- Modify: `app/ui/main_window_actions.py`
- Modify: `app/ui/main_window_blocking.py`
- Modify: `app/ui/main_window_layout.py`
- Modify: `app/ui/main_window_realtime.py`
- Modify: `app/utils/fetch_date.py`
- Reference: `.codex_recovery/recovered_src/decompiled/app/**/*`

- [ ] **Step 1: Restore the recovered file bodies**

Move the decompiled versions into place as the baseline instead of the binary-garbage current files.

- [ ] **Step 2: Fix decompiler-specific syntax breaks**

Repair issues such as:
- malformed f-strings
- `return pass`
- placeholder `##ERROR##`
- broken conditional rewrites
- invalid comprehensions / literal formatting

- [ ] **Step 3: Re-run the regression test**

Run: `python -m pytest tests/test_source_recovery.py -q`
Expected: failures narrow to the two most complex modules, `chat_service.py` and `main_window_data.py`

### Task 4: Hand-Reconstruct `chat_service.py`

**Files:**
- Modify: `app/services/chat_service.py`
- Reference: `.codex_recovery/recovered_src/disassembly/app/services/chat_service.dis.txt`
- Reference: `.codex_recovery/recovered_src/decompiled/app/services/chat_service.pyasm`
- Reference: `app/models/chat.py`
- Reference: `app/ui/main_window*.py`

- [ ] **Step 1: Preserve the required public surface**

Implement `ChatLogService` with the public methods required by the UI and regression tests.

- [ ] **Step 2: Rebuild the minimal working parsing/export pipeline**

Prioritize:
- source loading from text/sqlite
- cached incremental loading
- blocked-name filtering
- bet summary / visual row extraction
- export helpers used by UI actions

- [ ] **Step 3: Prefer correct, simplified behavior over speculative complexity**

Where bytecode reconstruction is ambiguous, keep the implementation explicit and conservative rather than inventing hidden behavior.

- [ ] **Step 4: Re-run the regression test**

Run: `python -m pytest tests/test_source_recovery.py -q`
Expected: `chat_service.py`-related failures disappear

### Task 5: Hand-Reconstruct `main_window_data.py`

**Files:**
- Modify: `app/ui/main_window_data.py`
- Reference: `.codex_recovery/recovered_src/disassembly/app/ui/main_window_data.dis.txt`
- Reference: `.codex_recovery/recovered_src/decompiled/app/ui/main_window.py`
- Reference: `app/services/chat_service.py`
- Reference: `app/models/chat.py`

- [ ] **Step 1: Restore the mixin shell and required method set**

Implement `MainWindowDataMixin` with the methods referenced by `MainWindow` and the realtime/blocking/action mixins.

- [ ] **Step 2: Rebuild the load pipeline around the restored `ChatLogService`**

Prioritize:
- initial state loading
- database/manual source selection
- load option construction
- worker pipeline result application
- chart data refresh hooks

- [ ] **Step 3: Re-run the regression test**

Run: `python -m pytest tests/test_source_recovery.py -q`
Expected: all source-recovery tests pass

### Task 6: Final Verification

**Files:**
- Verify: `app/**/*.py`
- Verify: `tests/test_source_recovery.py`

- [ ] **Step 1: Run the focused regression suite**

Run: `python -m pytest tests/test_source_recovery.py -q`
Expected: PASS

- [ ] **Step 2: Run a full compile sweep**

Run: `python -m compileall app`
Expected: no compile errors in `app/`

- [ ] **Step 3: Record remaining known limitations**

If any Chinese strings remain mojibake or any behavior remains inferred from bytecode, capture that honestly in the final report.
