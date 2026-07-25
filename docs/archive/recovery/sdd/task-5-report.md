# Task 5 Report: Auto Bet GUI Panel

**Status:** Completed
**Commit:** 75bc049

## What was done

Created `app/ui/auto_bet_panel.py` -- a PySide6 QGroupBox widget for auto-bet configuration and control.

## Created file

- `app/ui/auto_bet_panel.py` (255 lines)

## Widget: AutoBetPanel(QGroupBox)

- Title: "自动下注"
- Signals: `config_changed(StrategyConfig)`, `start_clicked()`, `stop_clicked()`
- Strategy dropdown (趋势跟踪 / trend_following)
- Site dropdown (pc28, macao, australia, norway)
- Target group checklist populated via `set_available_groups()`
- Parameter inputs: observation window (3-100, default 10), trigger threshold (2-50, default 3), bet amount (0.01-999999, default 10.0)
- Play type checkboxes (大, 小, 单, 双, 大单, 小单, 大双, 小双) -- defaults: 大, 小 checked
- Lock threshold spin (5-120, default 15 seconds)
- Start/Stop buttons with status label (green "running" / grey "stopped")
- Read-only run log QTextEdit (max height 150)
- `get_config()` / `load_config()` for bidirectional UI-config sync
- `append_log(InjectRecord)` for run log entries
- `set_running(bool)` to toggle UI state

## Test results

All assertions passed:
- Default config values correct (strategy_type, site, observation_window, trigger_threshold, bet_amount)
- `load_config()` correctly applies site, bet_amount, and play_types
- `append_log()` accepts InjectRecord without error
- Panel instantiation succeeds with PySide6 QApplication
