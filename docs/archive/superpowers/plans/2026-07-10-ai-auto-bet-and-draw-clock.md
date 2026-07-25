# AI Auto Bet and Draw Clock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize inferred draw periods during fetch failures and add configurable AI betting with optional per-period confirmation.

**Architecture:** Keep the existing in-process history cache and Web WSS sender. Add a standard-library AI client that normalizes OpenAI-compatible and Anthropic responses, then let `AutoBetService` request one asynchronous recommendation per site/period and expose a pending recommendation for the Qt layer to confirm or send.

**Tech Stack:** Python 3, PySide6, `urllib.request`, SQLite, pytest.

---

### Task 1: Stabilize Inferred Draw Schedules

**Files:**
- Modify: `app/utils/fetch_date.py`
- Modify: `app/ui/main_window_realtime.py`
- Modify: `tests/test_site_selection_ui.py`

- [ ] **Step 1: Write failing schedule tests**

```python
def test_countdown_tick_does_not_advance_a_site_without_a_reliable_schedule():
    info = DrawInfo(current_period="100", next_period="101", next_countdown=0)
    window._advance_site_countdown("pc28", info, datetime(2026, 7, 10, 12, 0))
    assert window._draw_infos["pc28"].current_period == "100"

def test_local_advance_catches_up_only_for_elapsed_intervals():
    info = DrawInfo(current_period="100", next_period="101", next_time=boundary, interval_sec=210)
    advanced = window._advance_site_locally("pc28", info, boundary + timedelta(seconds=420))
    assert advanced.current_period == "103"
    assert advanced.next_time == boundary + timedelta(seconds=630)
```

- [ ] **Step 2: Run the focused tests and verify expected failures**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_site_selection_ui.py -q`

Expected: the no-schedule test demonstrates an unwanted local advancement and the catch-up test demonstrates one-period-only advancement.

- [ ] **Step 3: Preserve the reliable time anchor in implementation**

```python
def _advance_site_countdown(self, site: str, info: DrawInfo, now: datetime) -> None:
    if info.next_time is not None:
        info.next_countdown = max(0, int((info.next_time - now).total_seconds()))
    elif info.next_countdown > 0:
        info.next_countdown -= 1
    else:
        return
    if info.next_countdown > 0:
        return
    ...
```

Calculate elapsed local periods from the previous `next_time`, rather than a countdown refresh count, and retain the original interval alignment.

- [ ] **Step 4: Run focused tests and related draw-provider tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_site_selection_ui.py tests/test_draw_result_provider.py -q`

Expected: PASS.

### Task 2: Add AI Configuration and HTTP Client

**Files:**
- Modify: `app/models/auto_bet.py`
- Create: `app/services/ai_bet_client.py`
- Create: `tests/test_ai_bet_client.py`

- [ ] **Step 1: Write failing client and configuration tests**

```python
def test_openai_client_posts_chat_completion_and_parses_strict_json():
    client = AiBetClient(opener=fake_opener)
    recommendation = client.recommend(config, [DrawResult("1", "pc28", "大单")])
    assert recommendation.play_type == "小双"

def test_anthropic_client_posts_messages_and_reads_text_content():
    ...

def test_ai_config_round_trip_preserves_provider_and_confirmation_fields():
    assert StrategyConfig.from_dict(config.to_dict()) == config
```

- [ ] **Step 2: Run the tests and verify expected failures**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_ai_bet_client.py -q`

Expected: FAIL because `AiBetClient` and AI configuration fields do not exist.

- [ ] **Step 3: Add strict recommendation parsing and provider-specific requests**

```python
@dataclass(frozen=True)
class AiRecommendation:
    play_type: str
    reason: str

class AiBetClient:
    def recommend(self, config: StrategyConfig, results: list[DrawResult]) -> AiRecommendation:
        payload, headers, url = self._build_request(config, results)
        response = self._post_json(url, payload, headers)
        return self._parse_recommendation(self._response_text(config.ai_provider, response))
```

Validate `play_type` against all eight supported plays; reject malformed or unexpected model output with `AiBetClientError`.

- [ ] **Step 4: Run client tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_ai_bet_client.py -q`

Expected: PASS.

### Task 3: Add Asynchronous AI Recommendation Lifecycle

**Files:**
- Modify: `app/models/auto_bet.py`
- Modify: `app/services/auto_bet_service.py`
- Modify: `tests/test_auto_bet_runtime.py`

- [ ] **Step 1: Write failing service tests**

```python
def test_ai_strategy_generates_one_pending_suggestion_per_site_period():
    service.tick("pc28", 100, "1001")
    wait_for(lambda: service.pending_ai_recommendation("pc28", "1001") is not None)
    service.tick("pc28", 99, "1001")
    assert fake_client.calls == 1

def test_confirming_ai_suggestion_sends_same_text_to_every_target_group():
    assert service.confirm_ai_bet("pc28", "1001")
    assert sender.texts == [("a", "大100"), ("b", "大100")]

def test_ai_confirmation_timeout_skips_without_sending():
    service.tick("pc28", 10, "1001")
    assert sender.texts == []
```

- [ ] **Step 2: Run the focused service tests and verify expected failures**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_auto_bet_runtime.py -q`

Expected: FAIL because AI strategy and confirmation lifecycle do not exist.

- [ ] **Step 3: Implement bounded asynchronous recommendation generation**

```python
if cfg.strategy_type == "ai":
    self._process_ai_period(site, current_period, cfg, injector, result_provider, window)
    return
```

Track attempted, in-flight, pending, skipped, and sent `(site, period)` keys. Request history from `DrawResultProvider`, apply the current amount, and generate equivalent decisions for every target group only after the recommendation is valid.

- [ ] **Step 4: Implement confirm, skip, expiry, and event callback APIs**

```python
def pending_ai_recommendation(self, site: str, period: str) -> PendingAiBet | None: ...
def confirm_ai_bet(self, site: str, period: str, *, within_bet_window: bool) -> bool: ...
def skip_ai_bet(self, site: str, period: str, reason: str = "用户跳过本期") -> bool: ...
```

Ensure only actual sends are added to `_bet_keys` and `_rounds`; generation, skipping, expiry, and model errors only write logs.

- [ ] **Step 5: Run focused service tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_auto_bet_runtime.py tests/test_ai_bet_client.py -q`

Expected: PASS.

### Task 4: Add AI Controls and Qt Integration

**Files:**
- Modify: `app/ui/auto_bet_panel.py`
- Modify: `app/ui/main_window.py`
- Modify: `app/ui/main_window_data.py`
- Modify: `tests/test_auto_bet_panel_help.py`

- [ ] **Step 1: Write failing panel and mixin tests**

```python
def test_ai_strategy_config_exposes_provider_history_and_confirmation():
    panel._strategy_combo.setCurrentIndex(panel._strategy_combo.findData("ai"))
    config = panel.get_config()
    assert config.ai_history_count == 50
    assert config.ai_require_confirmation is False

def test_ai_pending_confirmation_is_forwarded_with_current_window_state():
    window._on_confirm_ai_bet()
    assert service.confirm_calls == [("pc28", "1001", True)]
```

- [ ] **Step 2: Run the focused UI tests and verify expected failures**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_auto_bet_panel_help.py tests/test_draw_result_provider.py -q`

Expected: FAIL because AI controls and confirmation slots do not exist.

- [ ] **Step 3: Implement AI settings and pending-decision panel**

```python
self._ai_api_key_edit.setEchoMode(QLineEdit.Password)
self._ai_history_spin.setRange(20, 200)
self._ai_history_spin.setValue(50)
self._ai_confirm_check = QCheckBox("每期下注前需确认")
```

When AI is selected, hide mode/play constraints, show provider configuration, and render pending play, amount, reason, confirmation, and skip controls.

- [ ] **Step 4: Bridge service worker events through a Qt signal and process user actions**

Add an object signal to `MainWindow`, connect it to a data-mixin handler, then register the service callback when wiring the panel. The handler refreshes the pending suggestion and appends worker-produced logs on the UI thread.

- [ ] **Step 5: Run the UI tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_auto_bet_panel_help.py tests/test_draw_result_provider.py -q`

Expected: PASS.

### Task 5: Run Targeted Regression Verification

**Files:**
- Modify: `docs/superpowers/specs/2026-07-10-ai-auto-bet-and-draw-clock-design.md`
- Modify: `docs/superpowers/plans/2026-07-10-ai-auto-bet-and-draw-clock.md`

- [ ] **Step 1: Mark completed plan steps and document test evidence**

Update the test section of the design document with the exact command and observed result.

- [ ] **Step 2: Run the full related suite**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_site_selection_ui.py tests/test_draw_result_provider.py tests/test_auto_bet_runtime.py tests/test_auto_bet_panel_help.py tests/test_ws_message_sender.py tests/test_wss_protocol.py -q`

Expected: PASS.

- [ ] **Step 3: Inspect the final diff**

Run: `git diff --check; git diff -- app/models/auto_bet.py app/services/ai_bet_client.py app/services/auto_bet_service.py app/ui/auto_bet_panel.py app/ui/main_window.py app/ui/main_window_data.py app/ui/main_window_realtime.py app/utils/fetch_date.py tests`

Expected: no whitespace errors and only intended files changed.
