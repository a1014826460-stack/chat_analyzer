# Auto Bet UI and Runtime Design

## Goal
Implement the basic practical auto-bet UI and runtime settlement flow for manual strategy modes, martingale amounts, configurable odds, and live win/loss statistics.

## Scope
This phase implements non-AI auto betting only. AI recommendation, API key storage, and LLM prompt execution are intentionally deferred to a later phase after the runtime accounting foundation is stable.

## Requirements
- Users can choose bet mode: size, parity, small-odd/big-even, small-even/big-odd, or three-doors.
- Users can check allowed play types: 大, 小, 单, 双, 小单, 大双, 小双, 大单.
- Three-doors mode requires exactly three selections from 小单, 大双, 小双, 大单. The current martingale amount is applied per door.
- One-door modes place one strategy-recommended bet per period.
- Martingale sequence supports values such as 100-200-400-800. A win resets to the first step. A loss advances to the next step. Losing at the final step halts auto betting and waits for manual handling.
- Odds are configurable and default to: 大/小/单/双 = 1.98, 小单/大双 = 3.68, 小双/大单 = 4.28.
- Runtime statistics show total staked, payout, profit, settled rounds, win/lose rounds, current martingale step, consecutive losses, and halted status.

## Architecture
`StrategyConfig` stores bet mode, martingale sequence, odds, and selected play types. `AutoBetService` owns runtime state and pending rounds, makes one-or-many bet decisions, records placed rounds, settles them against `DrawResultProvider`, and updates martingale state. `AutoBetPanel` exposes the new controls and a stats label, while `MainWindowDataMixin` pushes runtime state to the panel on start/stop/tick.

## Files
- `app/models/auto_bet.py`: config/state dataclasses and default odds.
- `app/services/auto_bet_service.py`: strategy decisions, martingale accounting, settlement, halt/reset runtime state.
- `app/ui/auto_bet_panel.py`: mode selector, martingale input, odds inputs, play checkboxes, stats display.
- `app/ui/main_window_data.py`: sync runtime state to UI.
- `tests/test_auto_bet_runtime.py`: non-UI runtime behavior tests.

## Decisions
- When martingale reaches the final step and loses, auto betting halts until manual reset.
- Three-doors amount is per door, so 100 with three selected doors stakes 300 total.
- Size/parity/two-door modes place one recommended bet per period.
- Test group ID is `207191791`; test user ID `lin2225427` is documented for manual testing and not hardcoded into production logic.
