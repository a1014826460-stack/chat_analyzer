# Auto-Bet Configuration Guardrails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent automatic betting from starting with incomplete configuration and make the configuration and live statistics panel easier to use safely.

**Architecture:** `StrategyConfig` owns persisted defaults, cutoff normalization, and pure validation. `AutoBetService.start()` and `MainWindowDataMixin._on_auto_bet_start()` enforce that validation before execution resources exist. `AutoBetPanel` renders sectioned controls and delegates all configuration validity to the model.

**Tech Stack:** Python 3.11, PySide6, pytest.

---

### Task 1: Normalize defaults and validate configuration

**Files:**
- Modify: `app/models/auto_bet.py`
- Test: `tests/test_auto_bet_runtime.py`

- [ ] **Step 1: Write failing model tests**

```python
def test_strategy_config_defaults_to_deepseek_anthropic_and_clamps_cutoff():
    config = StrategyConfig.from_dict({"lock_threshold_sec": 5})
    assert config.ai_provider == "anthropic"
    assert config.ai_base_url == "https://api.deepseek.com/anthropic"
    assert config.ai_model == "deepseek-v4-pro"
    assert config.lock_threshold_sec == 20


def test_strategy_config_lists_all_start_validation_errors():
    config = StrategyConfig(
        target_groups=[], play_types=[], odds={"大": 0},
        ai_base_url="", ai_model="", ai_api_key="",
    )
    assert config.start_validation_errors() == [
        "请至少选择一个目标群组",
        "请至少选择一个推荐玩法",
        "请填写全部玩法的有效赔率",
        "Base URL", "模型", "API Key",
    ]
```

- [ ] **Step 2: Run the tests to verify RED**

Run: `python -m pytest tests/test_auto_bet_runtime.py -k "deepseek_anthropic or start_validation_errors" -q`

Expected: FAIL because defaults, clamping, or `start_validation_errors()` do not exist.

- [ ] **Step 3: Implement configuration normalization and validation**

```python
DEFAULT_AI_PROVIDER = "anthropic"
DEFAULT_AI_BASE_URL = "https://api.deepseek.com/anthropic"
DEFAULT_AI_MODEL = "deepseek-v4-pro"


def start_validation_errors(self) -> list[str]:
    errors = []
    if not self.target_groups:
        errors.append("请至少选择一个目标群组")
    if not self.play_types:
        errors.append("请至少选择一个推荐玩法")
    if not all(math.isfinite(float(self.odds.get(play, 0))) and float(self.odds[play]) > 0 for play in DEFAULT_ODDS):
        errors.append("请填写全部玩法的有效赔率")
    errors.extend(self.missing_ai_fields())
    if self.strategy_type == "martingale" and not self.martingale_sequence:
        errors.append("请填写有效的倍投序列")
    return errors
```

- [ ] **Step 4: Run the model tests to verify GREEN**

Run: `python -m pytest tests/test_auto_bet_runtime.py -k "deepseek_anthropic or start_validation_errors" -q`

Expected: PASS.

### Task 2: Add service-level start guard

**Files:**
- Modify: `app/services/auto_bet_service.py`
- Test: `tests/test_auto_bet_runtime.py`

- [ ] **Step 1: Write failing service test**

```python
def test_auto_bet_service_does_not_start_with_invalid_configuration():
    service = AutoBetService()
    service.apply_config(StrategyConfig(target_groups=[]))
    service.start()
    assert service.is_running is False
```

- [ ] **Step 2: Run the test to verify RED**

Run: `python -m pytest tests/test_auto_bet_runtime.py::test_auto_bet_service_does_not_start_with_invalid_configuration -q`

Expected: FAIL because `start()` currently sets `_running` to `True`.

- [ ] **Step 3: Implement the guard**

```python
def start(self) -> bool:
    with self._lock:
        errors = self._config.start_validation_errors()
        if errors:
            self._running = False
            return False
        self._running = True
        # reset runtime state
    return True
```

- [ ] **Step 4: Run the test to verify GREEN**

Run: `python -m pytest tests/test_auto_bet_runtime.py::test_auto_bet_service_does_not_start_with_invalid_configuration -q`

Expected: PASS.

### Task 3: Rebuild panel sections and validation behavior

**Files:**
- Modify: `app/ui/auto_bet_panel.py`
- Test: `tests/test_auto_bet_panel_help.py`

- [ ] **Step 1: Write failing UI tests**

```python
def test_auto_bet_panel_shows_trend_controls_only_for_trend_strategy(qapp):
    panel = AutoBetPanel()
    panel._strategy_combo.setCurrentIndex(panel._strategy_combo.findData("flat"))
    assert not panel._trend_parameters_widget.isVisibleTo(panel)
    panel._strategy_combo.setCurrentIndex(panel._strategy_combo.findData("trend_following"))
    assert panel._trend_parameters_widget.isVisibleTo(panel)


def test_auto_bet_panel_target_select_all_and_clear_preserve_checked_ids(qapp):
    panel = AutoBetPanel()
    panel.set_available_groups([("g1", "群一"), ("g2", "群二")])
    panel._select_all_target_groups()
    assert panel.get_config().target_groups == ["g1", "g2"]
    panel._clear_target_groups()
    assert panel.get_config().target_groups == []


def test_auto_bet_panel_play_controls_use_two_rows_of_four_columns(qapp):
    panel = AutoBetPanel()
    assert panel._play_grid.rowCount() == 2
    assert panel._play_grid.columnCount() == 4
```

- [ ] **Step 2: Run the tests to verify RED**

Run: `python -m pytest tests/test_auto_bet_panel_help.py -k "trend_controls or target_select_all or two_rows" -q`

Expected: FAIL because the named widgets and actions do not exist.

- [ ] **Step 3: Implement controls and layout**

```python
self._trend_parameters_widget = QWidget()
self._play_grid = QGridLayout(self._play_row_widget)
for index, play in enumerate(PLAY_TYPE_OPTIONS):
    self._play_grid.addWidget(QCheckBox(play), index // 4, index % 4)

self._select_all_groups_button.clicked.connect(self._select_all_target_groups)
self._clear_groups_button.clicked.connect(self._clear_target_groups)
```

Add panel validation before `set_running(True)`, use a warning showing all
errors, lock selection buttons while running, and render the six runtime
statistic cards without changing settlement accounting.

- [ ] **Step 4: Run panel tests to verify GREEN**

Run: `python -m pytest tests/test_auto_bet_panel_help.py -q`

Expected: PASS.

### Task 4: Enforce validation before resources and persist valid groups

**Files:**
- Modify: `app/ui/main_window_data.py`
- Test: `tests/test_draw_result_provider.py`

- [ ] **Step 1: Write failing integration tests**

```python
def test_main_window_does_not_create_sender_for_missing_target_group(monkeypatch):
    window = build_window_with_config(StrategyConfig(target_groups=[]))
    window._on_auto_bet_start()
    assert window.auto_bet_service.started is False


def test_refresh_auto_bet_groups_removes_missing_saved_target_groups():
    window = build_window_with_saved_auto_bet({"target_groups": ["gone", "g1"]})
    window._refresh_auto_bet_groups()
    assert window.auto_bet_panel.get_config().target_groups == ["g1"]
```

- [ ] **Step 2: Run integration tests to verify RED**

Run: `python -m pytest tests/test_draw_result_provider.py -k "missing_target_group or removes_missing_saved" -q`

Expected: FAIL because main-window start checks only AI fields and refresh does not persist filtered groups.

- [ ] **Step 3: Implement start and refresh enforcement**

```python
errors = service.config.start_validation_errors()
if errors:
    panel.set_running(False)
    QMessageBox.warning(self, "无法启动自动下注", "\n".join(errors))
    return
```

After target groups reload, compare panel-selected IDs with available IDs and
save the filtered `StrategyConfig` through `_on_auto_bet_config_changed`.

- [ ] **Step 4: Run integration tests to verify GREEN**

Run: `python -m pytest tests/test_draw_result_provider.py -k "missing_target_group or removes_missing_saved" -q`

Expected: PASS.

### Task 5: Verify

**Files:**
- Test: `tests/test_auto_bet_runtime.py`
- Test: `tests/test_ai_bet_client.py`
- Test: `tests/test_auto_bet_panel_help.py`
- Test: `tests/test_draw_result_provider.py`

- [ ] **Step 1: Run focused tests**

Run: `python -m pytest tests/test_auto_bet_runtime.py tests/test_ai_bet_client.py tests/test_auto_bet_panel_help.py tests/test_draw_result_provider.py -q`

Expected: PASS.

- [ ] **Step 2: Compile and check diff whitespace**

Run: `python -m py_compile app/models/auto_bet.py app/services/auto_bet_service.py app/ui/auto_bet_panel.py app/ui/main_window_data.py && git diff --check`

Expected: exit code 0.
