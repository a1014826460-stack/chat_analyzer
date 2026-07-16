# Site Persistence and AI Frequency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the active site, enforce complete AI configuration before automatic betting starts, and encourage supported low-confidence recommendations.

**Architecture:** Persist `last_selected_site` through the existing settings service and restore it during main-window initialization. Put AI credential validation on `StrategyConfig` so both the UI and main-window start path share the same rule. Update the default threshold and prompt only; runtime confidence gating remains user-configurable.

**Tech Stack:** Python 3, PySide6, pytest.

---

### Task 1: Persist active site

**Files:**
- Modify: `tests/test_site_selection_ui.py`
- Modify: `app/services/settings_service.py`
- Modify: `app/ui/main_window.py`
- Modify: `app/ui/main_window_actions.py`
- Modify: `app/ui/main_window_realtime.py`

- [ ] **Step 1: Write failing tests**

```python
def test_select_site_saves_the_last_selected_site():
    MainWindowRealtimeMixin._select_site(window, "macao")
    assert window.settings["last_selected_site"] == "macao"
    assert saved == ["saved"]

def test_main_window_restores_only_a_known_last_selected_site(monkeypatch):
    monkeypatch.setattr("app.ui.main_window.site_list", lambda: ["pc28", "macao"])
    assert MainWindow._restore_last_selected_site({"last_selected_site": "macao"}) == "macao"
    assert MainWindow._restore_last_selected_site({"last_selected_site": "unknown"}) == ""
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `python -m pytest tests/test_site_selection_ui.py -q`

Expected: failure because site selection is not persisted or restored.

- [ ] **Step 3: Implement minimal persistence and restoration**

```python
def _restore_last_selected_site(self) -> str:
    value = str(self.settings.get("last_selected_site", "")).strip()
    return value if value in site_list() else ""

def _select_site(self, site: str) -> None:
    self._active_site = site
    self.settings["last_selected_site"] = site
    self._save_settings()
```

- [ ] **Step 4: Run the tests and verify pass**

Run: `python -m pytest tests/test_site_selection_ui.py -q`

Expected: PASS.

### Task 2: Enforce complete AI configuration

**Files:**
- Modify: `tests/test_ai_bet_client.py`
- Modify: `tests/test_auto_bet_panel_help.py`
- Modify: `tests/test_draw_result_provider.py`
- Modify: `app/models/auto_bet.py`
- Modify: `app/ui/auto_bet_panel.py`
- Modify: `app/ui/main_window_data.py`

- [ ] **Step 1: Write failing tests**

```python
def test_strategy_config_reports_each_missing_ai_field():
    assert StrategyConfig(ai_provider="", ai_base_url="", ai_model="", ai_api_key="").missing_ai_fields() == [
        "AI 类型", "Base URL", "模型", "API Key"
    ]

def test_auto_bet_start_rejects_incomplete_ai_configuration():
    window.auto_bet_service.config = StrategyConfig(ai_base_url="", ai_model="", ai_api_key="")
    window._on_auto_bet_start()
    assert window.auto_bet_service.started is False
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `python -m pytest tests/test_ai_bet_client.py tests/test_auto_bet_panel_help.py tests/test_draw_result_provider.py -q`

Expected: failure because validation is duplicated and can be bypassed by the integration start path.

- [ ] **Step 3: Implement shared validation**

```python
def missing_ai_fields(self) -> list[str]:
    fields = []
    if self.ai_provider not in {"openai_compatible", "anthropic"}:
        fields.append("AI 类型")
    if not self.ai_base_url.strip():
        fields.append("Base URL")
    if not self.ai_model.strip():
        fields.append("模型")
    if not self.ai_api_key.strip():
        fields.append("API Key")
    return fields
```

- [ ] **Step 4: Run the tests and verify pass**

Run: `python -m pytest tests/test_ai_bet_client.py tests/test_auto_bet_panel_help.py tests/test_draw_result_provider.py -q`

Expected: PASS.

### Task 3: Use the lower default gate and weak-evidence instruction

**Files:**
- Modify: `tests/test_ai_bet_client.py`
- Modify: `tests/test_auto_bet_panel_help.py`
- Modify: `app/models/auto_bet.py`
- Modify: `app/ui/auto_bet_panel.py`
- Modify: `app/services/ai_bet_client.py`

- [ ] **Step 1: Write failing tests**

```python
def test_ai_defaults_to_a_45_confidence_threshold():
    assert StrategyConfig().ai_confidence_threshold == 45
    assert StrategyConfig.from_dict({}).ai_confidence_threshold == 45

def test_ai_prompt_requests_low_confidence_bets_for_weak_supported_edges():
    request = AiBetClient._build_request(client, StrategyConfig(), [])
    assert "弱但具体的方向性证据" in request[2]["messages"][0]["content"]
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `python -m pytest tests/test_ai_bet_client.py tests/test_auto_bet_panel_help.py -q`

Expected: failure because the default remains 65 and the system prompt asks only to skip weak evidence.

- [ ] **Step 3: Implement minimal defaults and prompt change**

```python
ai_confidence_threshold: int = 45

"若存在弱但具体的方向性证据，输出低置信度 bet；"
"只有没有可验证方向依据时才 skip。"
```

- [ ] **Step 4: Run the tests and verify pass**

Run: `python -m pytest tests/test_ai_bet_client.py tests/test_auto_bet_panel_help.py -q`

Expected: PASS.

### Task 4: Verify

- [ ] Run `python -m pytest tests/test_site_selection_ui.py tests/test_ai_bet_client.py tests/test_auto_bet_panel_help.py tests/test_draw_result_provider.py tests/test_auto_bet_runtime.py -q`.
- [ ] Run `python -m py_compile app/models/auto_bet.py app/services/ai_bet_client.py app/ui/auto_bet_panel.py app/ui/main_window.py app/ui/main_window_actions.py app/ui/main_window_realtime.py app/ui/main_window_data.py`.
- [ ] Run `git diff --check`.
