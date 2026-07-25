# Auto-Bet Configuration Guardrails Design

## Goal

Make the automatic-betting panel safe to configure before it can start. The
panel must prevent incomplete target, play, odds, AI, and strategy settings;
make strategy-specific controls obvious; and expose live financial state in a
compact, readable operational layout.

## Scope

This design updates the automatic-bet settings model, service start guard,
panel layout, and main-window integration. It preserves the existing 60-second
AI request timeout and the strict AI play constraint: an AI recommendation may
only be one of the user-selected plays.

## Persisted Defaults and Bounds

`StrategyConfig` provides these defaults for a newly created configuration:

- AI provider: `anthropic`
- Base URL: `https://api.deepseek.com/anthropic`
- Model: `deepseek-v4-pro`
- Lock threshold: 20 seconds

Deserialization clamps `lock_threshold_sec` into 20-60 seconds so an old saved
value cannot reopen an unsafe cutoff. The panel spin box uses the identical
20-60 range.

The existing `play_types`, all eight `odds`, and selected `target_groups` stay
in `auto_bet` settings. Reloading the source group list retains only saved
selected group IDs that still exist; removed groups are silently discarded and
the resulting configuration is emitted for persistence.

## Start Validation

A shared validation function on `StrategyConfig` returns all blocking messages
in this order:

1. `请至少选择一个目标群组`
2. `请至少选择一个推荐玩法`
3. `请填写全部玩法的有效赔率`
4. AI required fields, using the existing individual labels
5. For `martingale`, `请填写有效的倍投序列`

An odds value is valid only when every one of the eight named plays has a
finite numeric value greater than zero. Missing dictionary entries, blank UI
fields, non-numeric values, zero, negative values, NaN, and infinity are all
invalid. Validation runs when the panel start button is clicked and again in
the main-window start handler before any sender or network resource is
created. The panel shows a single warning with all errors, remains stopped,
and emits no start signal when validation fails.

## Panel Layout

Use the approved vertical section layout:

1. **Strategy and AI**: strategy combo, help, and AI configuration button.
2. **Target groups**: `全选` and `全不选` actions above a compact checklist.
3. **Strategy parameters**: fixed amount or martingale sequence. The
   observation-window and trigger-threshold row is visible only for
   `trend_following`.
4. **Plays and odds**: all eight play checkboxes in a two-row four-column
   grid. Each checkbox remains in its own grid cell so long composite labels
   never overlap. All eight odds remain editable in an aligned two-row grid.
5. **Execution and statistics**: the 20-60 second cutoff, start/stop status,
   a six-card operational summary, AI accuracy summary, and run log.

Changing betting mode never changes existing play check states. Running locks
all config controls, including target selection actions.

The conflict-preference controls are removed because strict play validation
makes an out-of-selection AI suggestion invalid rather than confirmable.

## Operational Statistics

The summary cards show:

- Pending stake
- Settled stake
- Settled payout
- Settled profit/loss
- Win rate with `wins / settled rounds`
- State: flat amount or martingale step, loss streak, and halt reason

Profit is green for positive, red for negative, and neutral otherwise. Pending
stake is explicitly not included in settled profit/loss.

## Additional Defenses

- Main-window validation occurs before sender creation, draw history refresh,
  or AI client creation.
- The service returns immediately when `start()` receives an invalid config,
  preserving a stopped state even if invoked outside the UI.
- No automatic AI connectivity test runs at start: external latency must not
  consume the current betting window. A separate connectivity action remains
  out of this change.
- Existing one-site/one-period/group de-duplication remains unchanged.

## Testing

Tests cover default migration and cutoff clamping, model/service start
validation, panel group selection actions and persistence, strategy-specific
visibility, grid layout, all-odds validation, and statistics card rendering.
