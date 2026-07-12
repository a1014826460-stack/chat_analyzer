# Quantitative AI Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh draw history per AI period, persist and settle AI predictions, calculate quantitative features and accuracy, and gate low-confidence recommendations.

**Architecture:** Add a focused quantitative analyzer and SQLite prediction store. `AutoBetService` refreshes draw history, settles old predictions, builds quantitative context, calls the AI client, persists every outcome, and applies confidence gating before the existing sender path.

**Tech Stack:** Python 3, SQLite, standard-library statistics/math/JSON, PySide6, pytest.

---

### Task 1: Configuration and response contract

**Files:** `app/models/auto_bet.py`, `app/services/ai_bet_client.py`, `tests/test_ai_bet_client.py`

- [ ] Add `ai_confidence_threshold=65` and `ai_accuracy_window=20` with validation.
- [ ] Expand `AiRecommendation` to action, confidence, quantitative rationale, and reason.
- [ ] Test and implement strict `bet`/`skip` JSON parsing.

### Task 2: Quantitative feature analyzer

**Files:** `app/services/ai_quant_analysis.py`, `tests/test_ai_quant_analysis.py`

- [ ] Test 20/50-window frequencies, tail streak, transition probabilities, entropy and concentration.
- [ ] Implement a deterministic JSON-serializable quantitative context.

### Task 3: Prediction persistence and accuracy

**Files:** `app/models/auto_bet.py`, `app/services/ai_prediction_store.py`, `tests/test_ai_prediction_store.py`

- [ ] Test insert/update, settlement, overall/short-window dual accuracy and recent records.
- [ ] Persist all recommendations and settle sent predictions against actual results.

### Task 4: Fresh draw cache

**Files:** `app/services/draw_result_store.py`, `tests/test_draw_result_provider.py`

- [ ] Reproduce stale cache behavior.
- [ ] Add explicit `refresh_recent_results()` that always fetches and upserts current history.

### Task 5: AI service feedback loop

**Files:** `app/services/auto_bet_service.py`, `tests/test_auto_bet_runtime.py`

- [ ] Test refresh-before-recommend, settle-before-new-prediction, confidence/skip gating and persistence.
- [ ] Pass quantitative and accuracy feedback to AI and preserve existing site/period/group deduplication.

### Task 6: UI statistics and settings

**Files:** `app/ui/auto_bet_panel.py`, `app/ui/main_window_data.py`, `tests/test_auto_bet_panel_help.py`, `tests/test_draw_result_provider.py`

- [ ] Add threshold and short-window controls to AI config.
- [ ] Display overall/short direction and exact accuracy, settled count and streaks.
- [ ] Add a recent-record dialog and wire prediction store at startup.

### Task 7: Verification

- [ ] Run all AI, draw-provider, UI, WSS and proxy regression tests.
- [ ] Run `git diff --check` and inspect changed files.
