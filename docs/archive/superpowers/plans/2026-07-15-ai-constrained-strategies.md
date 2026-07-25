# AI Constrained Strategies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AI mandatory for flat, martingale, and trend-reversal modes while adding shared history proxy support, play-conflict handling, and session profit/loss limits.

**Architecture:** Extend persisted configuration and the strategy scheduler. `AutoBetService` determines when an AI request is eligible and the amount constraint, while the AI response remains the only play decision. `AutoBetPanel` captures the new configuration and presents conflict confirmation through the existing pending panel.

**Tech Stack:** Python 3, PySide6, urllib, SQLite, pytest.

---

### Task 1: Reuse application proxy settings for history

**Files:** `app/utils/history_records.py`, `tests/test_history_records.py`

- [ ] Add a failing test proving history requests use a `urllib` opener configured from persisted proxy settings.
- [ ] Implement startup settings loading and proxy application without adding a second proxy configuration.
- [ ] Run `python -m pytest tests/test_history_records.py -q`.

### Task 2: Persist modes, conflict preference, and risk limits

**Files:** `app/models/auto_bet.py`, `tests/test_auto_bet_runtime.py`

- [ ] Add failing tests for `ai -> flat` migration, non-negative limits, and conflict preference serialization.
- [ ] Implement configuration fields and migration.
- [ ] Run the targeted model tests.

### Task 3: Make all strategies AI-scheduled

**Files:** `app/services/auto_bet_service.py`, `tests/test_auto_bet_runtime.py`, `app/services/ai_bet_client.py`

- [ ] Add failing tests for flat/fixed-martingale/trend AI scheduling and 20-second analysis status.
- [ ] Implement the schedule gate, amount selection, prompt constraints, and remove manual fallback decisions.
- [ ] Run `python -m pytest tests/test_auto_bet_runtime.py tests/test_ai_bet_client.py -q`.

### Task 4: Resolve play preference conflicts

**Files:** `app/services/auto_bet_service.py`, `app/models/auto_bet.py`, `tests/test_auto_bet_runtime.py`

- [ ] Add failing tests for direction-compatible labels, forced confirmation, expiry skip, and saved preference.
- [ ] Implement compatibility checking and pending conflict metadata.
- [ ] Run target runtime tests.

### Task 5: Add take-profit and stop-loss enforcement

**Files:** `app/services/auto_bet_service.py`, `app/ui/main_window_data.py`, `tests/test_auto_bet_runtime.py`

- [ ] Add failing tests for profit/loss boundaries and one-shot halt callback.
- [ ] Implement settlement enforcement and GUI shutdown callback.
- [ ] Run target tests.

### Task 6: Update panel and integration

**Files:** `app/ui/auto_bet_panel.py`, `app/ui/main_window_data.py`, `tests/test_auto_bet_panel_help.py`, `tests/test_draw_result_provider.py`

- [ ] Add failing UI tests for modes, configuration fields, and conflict presentation.
- [ ] Implement controls, labels, migration display, and timer/sender stop integration.
- [ ] Run relevant UI/draw-provider tests.

### Task 7: Verify

- [ ] Run the AI, history, runtime, panel, provider, WSS, proxy, and site-selection regression suite.
- [ ] Run `git diff --check` and Python compilation.
