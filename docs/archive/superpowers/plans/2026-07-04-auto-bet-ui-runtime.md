# Auto Bet UI and Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the basic practical auto-bet UI and runtime settlement flow with manual modes, martingale amounts, odds, and win/loss statistics.

**Architecture:** Extend `StrategyConfig` and add runtime state models. Update `AutoBetService` to return multiple decisions, record pending rounds, settle against historical draw results, and halt at final martingale loss. Extend `AutoBetPanel` with mode, martingale, odds, and statistics controls.

**Tech Stack:** Python dataclasses, PySide6 UI widgets, pytest, existing DrawResultProvider and MessageInjector integrations.

---

### Task 1: Runtime model and service behavior

**Files:**
- Modify: `app/models/auto_bet.py`
- Modify: `app/services/auto_bet_service.py`
- Test: `tests/test_auto_bet_runtime.py`

- [x] Write failing tests for config persistence, three-door decisions, martingale amount selection, settlement win/loss, and final-step halt.
- [x] Add `DEFAULT_ODDS`, `AutoBetRuntimeState`, `AutoBetRound`, and config fields.
- [x] Add `_analyze_many`, `_record_round`, `settle_pending_rounds`, runtime reset/state accessors, odds payout, and martingale halt logic.
- [x] Verify with `python -m pytest tests/test_auto_bet_runtime.py -q`.

### Task 2: UI controls and statistics

**Files:**
- Modify: `app/ui/auto_bet_panel.py`
- Modify: `app/ui/main_window_data.py`

- [x] Add bet mode selector.
- [x] Add martingale sequence input.
- [x] Add configurable odds inputs.
- [x] Add runtime statistics label and `update_runtime_state`.
- [x] Sync runtime state on start, stop, and tick.
- [x] Verify via compileall because PySide6 is unavailable in this environment.

### Task 3: Regression verification

**Files:**
- Existing tests.

- [x] Run `python -m pytest tests/test_auto_bet_runtime.py tests/test_draw_result_provider.py tests/test_history_records.py -q`.
- [x] Run compile checks for modified modules.
- [x] Run deterministic E2E settlement snippet for three-doors mode.
