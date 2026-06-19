# Robot Summary Source And Period Switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make robot summary reconciliation use only authoritative group-summary messages, keep zero-total mismatches outside the 20% tolerance, and preserve switchable summary-check results across periods.

**Architecture:** Keep the existing `ChatLogService` reconciliation pipeline and `SummaryCheckDialog` history/filter UI. Add narrow regression tests first, then tighten summary-source detection and zero-total tolerance handling without changing the surrounding data flow.

**Tech Stack:** Python, PySide6, pytest, SQLite-backed chat parsing

---

### Task 1: Lock Down Reconciliation Inputs

**Files:**
- Modify: `tests/test_source_recovery.py`
- Modify: `app/services/chat_service.py`

- [ ] Add a failing test showing that a full robot period summary and a later personal status summary for the same group/period must prefer the full summary totals.
- [ ] Run: `.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -k "prefers_authoritative_robot_summary" -v`
- [ ] Update summary-source detection so group-wide period summaries are accepted, while personal `当前积分/本期下注` snapshots are excluded from reconciliation-source selection.
- [ ] Re-run: `.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -k "prefers_authoritative_robot_summary" -v`

### Task 2: Lock Down Zero-Total Tolerance

**Files:**
- Modify: `tests/test_source_recovery.py`
- Modify: `app/services/chat_service.py`

- [ ] Add a failing test showing `software_total > 0` and `robot_total == 0` must be marked `within_tolerance == False`.
- [ ] Run: `.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -k "zero_robot_total_is_not_within_tolerance" -v`
- [ ] Adjust reconciliation ratio handling so only the `software == 0 and robot == 0` case passes automatically.
- [ ] Re-run: `.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -k "zero_robot_total_is_not_within_tolerance" -v`

### Task 3: Guard Period Switching In Summary Check UI

**Files:**
- Modify: `tests/test_source_recovery.py`
- Modify: `app/ui/summary_check_dialog.py` only if the new regression fails

- [ ] Add a failing UI regression test covering one group with two different periods and verify manual period switching updates the displayed record.
- [ ] Run: `.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -k "summary_check_dialog_switches_periods_within_same_group" -v`
- [ ] If needed, make the minimal dialog fix so the selected period controls the rendered reconciliation payload reliably.
- [ ] Re-run: `.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -k "summary_check_dialog_switches_periods_within_same_group" -v`

### Task 4: Verify End To End

**Files:**
- Modify: `app/services/chat_service.py`
- Modify: `tests/test_source_recovery.py`

- [ ] Run the focused regression set:
  `.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -k "authoritative_robot_summary or zero_robot_total_is_not_within_tolerance or summary_check_dialog_switches_periods_within_same_group or summary_check_dialog_supports_group_and_period_filters" -v`
- [ ] Re-run a fresh read-only live DB comparison script against `C:\Users\Administrator\Documents\TencentCloudChat\Config\20011216_783144754172596756\msg_0.db` and confirm current-period robot reconciliation records no longer use personal status snapshots as the authoritative source.
