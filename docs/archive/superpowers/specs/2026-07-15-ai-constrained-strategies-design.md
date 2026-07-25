# AI Constrained Strategies and Risk Limits Design

## Goal

Make AI the required decision maker for every automatic-bet strategy while
keeping the user-selected strategy and play types as explicit constraints and
preferences. Reuse the application's Help -> Proxy settings for history
requests, expose bounded profit/loss limits, and make all waiting, conflict,
timeout, and stop states observable.

## Shared Proxy

`history_records.py` will use the process-wide standard-library `urllib`
proxy configuration set by `fetch_date.set_proxy_settings()`. The main window
already applies that configuration at startup and whenever Help -> Proxy
settings changes. Therefore site-clock requests, history requests, and AI HTTP
requests use the same `proxy_enabled`, HTTP proxy, and HTTPS proxy settings.

When the history script is launched independently, it loads `settings.json`
from `user_data_dir()` and applies the same settings before issuing any request.
There is no second proxy UI or separate history proxy configuration.

## Strategy Model

The strategy selector contains only:

- `flat`: AI analyzes every eligible period and chooses a play; the amount is
  the fixed bet amount.
- `martingale`: AI analyzes every eligible period and chooses a play; the
  amount is the current position in the configured martingale sequence.
- `trend_following`: the engine first requires the configured consecutive
  result trigger, then AI receives that trigger as a quantitative constraint
  and decides whether to bet and which play to use.

The legacy `ai` type migrates to `flat` when a saved configuration is loaded.
All modes require valid AI configuration before they can start. There is no
manual-strategy fallback if AI is unavailable or fails.

## User Play Preferences and Conflicts

Selected plays are a recommendation supplied to the AI. A recommendation is
compatible if it exactly matches a selected play or every atomic component of
the AI play is selected: `大单` is compatible with selected `大` and `单`.
Selecting a composite play does not make a single component compatible.

If a valid AI recommendation conflicts and the persisted
`ai_prefer_recommendation_on_conflict` setting is false, the existing pending
recommendation panel is shown even if normal per-period confirmation is off.
It prominently displays the selected plays, the AI play, and the conflict.
The user may use the AI play or skip the period, and may opt into "do not ask
again; prefer the AI play". That choice is persisted. A pending conflict at the
bet cutoff is removed and marked skipped; it is never sent automatically.

Normal confirmation remains unchanged for compatible suggestions when
`ai_require_confirmation` is enabled.

## Risk Limits

`take_profit_limit` and `stop_loss_limit` are non-negative amounts; zero means
disabled. Runtime cumulative profit is reset at each manual start. After a
round is settled, reaching `total_profit >= take_profit_limit` or
`total_profit <= -stop_loss_limit` halts the engine, records the exact reason,
stops the GUI timer, and shuts down the sender. The visible statistics remain
available until the next manual start.

## AI Request States

The AI request timeout remains 20 seconds. Every period emits an "AI analyzing
(20 second timeout)" state immediately before the request. One site/period has
one request and no retry. A timeout is persisted as a failure and does not
result in a late bet.

## UI

The strategy selector displays Flat, Fixed Martingale, and Trend Reversal. The
play controls are labelled "recommended plays". The AI configuration dialog
contains provider settings, history count, confirmation, confidence threshold,
accuracy window, conflict-preference checkbox, and profit/loss limit inputs.
Flat displays the fixed amount. Fixed Martingale displays the sequence. Trend
Reversal displays its observation and trigger controls.

## Testing

Tests cover history proxy use, legacy migration, all three AI scheduling modes,
directional play compatibility, conflict confirmation/expiry/preference,
profit/loss halting, and AI request start/timeout behavior.
