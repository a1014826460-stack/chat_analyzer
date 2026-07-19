# Runtime Streaks And Dynamic Three Doors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show per-run maximum winning and losing streaks and make three-door betting exclude the least frequent composite result.

**Architecture:** Extend `AutoBetRuntimeState` with session-only streak counters updated at settlement. Keep the existing martingale peak state scoped to the martingale-only UI. Build three-door decisions from the result provider's historical composite results using a deterministic tie-break order.

**Tech Stack:** Python 3.11, PySide6, pytest.

---

### Task 1: Add Runtime Streak State

**Files:**
- Modify: `app/models/auto_bet.py:294-311`
- Modify: `app/services/auto_bet_service.py:1139-1160`
- Test: `tests/test_auto_bet_runtime.py`

- [ ] **Step 1: Write the failing settlement streak test**

```python
def test_runtime_state_tracks_current_and_maximum_win_loss_streaks():
    service = AutoBetService()
    service.apply_config(StrategyConfig(site="pc28", odds={"大": 2.0}))
    for period, result in [("1", "大单"), ("2", "大双"), ("3", "小单"), ("4", "小双")]:
        service._record_round("pc28", period, [BetDecision(True, "大", 10, "g1", "test")])
        service.settle_pending_rounds(Provider(by_period={period: DrawResult(period, "pc28", result)}))
    state = service.runtime_state
    assert (state.max_consecutive_wins, state.max_consecutive_losses) == (2, 2)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_auto_bet_runtime.py::test_runtime_state_tracks_current_and_maximum_win_loss_streaks -q`

- [ ] **Step 3: Add state fields and update them in `_settle_round`**

```python
if profit > 0:
    state.consecutive_wins += 1
    state.consecutive_losses = 0
    state.max_consecutive_wins = max(state.max_consecutive_wins, state.consecutive_wins)
else:
    state.consecutive_losses += 1
    state.consecutive_wins = 0
    state.max_consecutive_losses = max(state.max_consecutive_losses, state.consecutive_losses)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_auto_bet_runtime.py::test_runtime_state_tracks_current_and_maximum_win_loss_streaks -q`

### Task 2: Implement Dynamic Three Doors

**Files:**
- Modify: `app/services/auto_bet_service.py:304-379`
- Modify: `app/ui/auto_bet_panel.py:78-84`
- Test: `tests/test_auto_bet_runtime.py`
- Test: `tests/test_auto_bet_panel_help.py`

- [ ] **Step 1: Write the failing dynamic three-door test**

```python
def test_three_doors_excludes_the_least_frequent_composite_result():
    provider = Provider(recent=[
        DrawResult("1", "pc28", "大单"), DrawResult("2", "pc28", "大单"),
        DrawResult("3", "pc28", "大双"), DrawResult("4", "pc28", "小单"),
    ])
    config = StrategyConfig(site="pc28", bet_mode="three_doors", target_groups=["g1"])
    decisions = AutoBetService()._analyze_many(config, provider)
    assert [item.play_type for item in decisions] == ["小单", "大双", "大单"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_auto_bet_runtime.py::test_three_doors_excludes_the_least_frequent_composite_result -q`

- [ ] **Step 3: Add deterministic history ranking and reason text**

```python
counts = {door: sum(result.result == door for result in results) for door in THREE_DOOR_PLAYS}
excluded = min(THREE_DOOR_PLAYS, key=lambda door: (counts[door], THREE_DOOR_PLAYS.index(door)))
plays = [door for door in THREE_DOOR_PLAYS if door != excluded]
reason = f"三门历史频率排除{excluded}({counts[excluded]}次)"
```

- [ ] **Step 4: Make the quick preset select all four candidates and update help copy**

```python
"three_doors": ("小单", "大双", "小双", "大单"),
```

- [ ] **Step 5: Run targeted strategy and panel tests**

Run: `pytest tests/test_auto_bet_runtime.py tests/test_auto_bet_panel_help.py -q`

### Task 3: Polish Runtime Statistics UI

**Files:**
- Modify: `app/ui/auto_bet_panel.py:309-348`
- Modify: `app/ui/auto_bet_panel.py:719-758`
- Test: `tests/test_auto_bet_panel_help.py`

- [ ] **Step 1: Write the failing panel statistic test**

```python
def test_auto_bet_panel_displays_session_maximum_win_and_loss_streaks():
    panel = AutoBetPanel()
    panel.update_runtime_state(AutoBetRuntimeState(max_consecutive_wins=4, max_consecutive_losses=3))
    text = "\n".join(label.text() for label in panel._runtime_stat_labels)
    assert "最大连中" in text and "4" in text
    assert "最大连输" in text and "3" in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_auto_bet_panel_help.py::test_auto_bet_panel_displays_session_maximum_win_and_loss_streaks -q`

- [ ] **Step 3: Expand the card grid and detail row**

```python
values = (..., ("最大连中", str(state.max_consecutive_wins), "#198754"), ("最大连输", str(state.max_consecutive_losses), "#c0392b"))
self._stats_detail_label.setText(
    f"当前连中: {state.consecutive_wins} | 当前连输: {state.consecutive_losses} | 已结算: {state.total_rounds}"
)
```

- [ ] **Step 4: Keep the martingale peak card visible only for the martingale strategy**

Run: `pytest tests/test_auto_bet_panel_help.py -q`

### Task 4: Final Verification

**Files:**
- Test: `tests/test_auto_bet_runtime.py`
- Test: `tests/test_auto_bet_panel_help.py`

- [ ] **Step 1: Run focused tests**

Run: `pytest tests/test_auto_bet_runtime.py tests/test_auto_bet_panel_help.py -q`

- [ ] **Step 2: Compile modified modules and check diff whitespace**

Run: `python -m compileall -q app/models/auto_bet.py app/services/auto_bet_service.py app/ui/auto_bet_panel.py && git diff --check`
