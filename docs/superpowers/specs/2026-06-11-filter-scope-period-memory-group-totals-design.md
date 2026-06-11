# Filter Scope, Period Memory, And Group Totals Design

**Date:** 2026-06-11

**Owner:** Codex with user confirmation

## Goal

Repair three closely related behavior gaps without rewriting the existing architecture:

1. separate `全局屏蔽名单` from `群组屏蔽名单`
2. make `期号筛选` persist per site instead of as one global override
3. produce real per-group totals in addition to the existing global totals

The user explicitly chose the incremental path: keep the current UI/service structure, correct the scope semantics, and extend the result model rather than introducing a new statistics subsystem.

## Confirmed Domain Rules

The implementation must align to the glossary and mechanism decisions already confirmed in `CONTEXT.md` and `docs/chat_analysis_mechanisms.md`.

- `全局屏蔽名单` applies to every group and is intended for cross-group fixed identities such as robots.
- `群组屏蔽名单` applies only inside one specific group.
- `期号筛选` is part of the filtering system even though its input box is rendered on the right side of the window.
- `期号筛选` must remember the manual override per site.
- left-side group selection defines the statistics scope.
- right-side `可见群组` remains a display filter and must not redefine the underlying totals.
- the app should support “filter down to one group and view totals” and should also expose a real grouped totals structure for the selected scope.

## Current Problems

### 1. Block-list scope leakage

The current UI stores only `group_block_rules`, but `MainWindowBlockingMixin._blocked_names()` flattens all rule names into one list. That flattened list is passed into `ParseOptions.blocked_names`, then `ChatLogService.filter_blocked_messages()` uses it as a global exclusion set before applying group rules. The effect is that a name configured for one group can be removed from all groups.

### 2. Period override is global state

The current window state uses:

- `self._query_period_override`
- `self._manual_period_override`

Those values are restored from one settings entry and are reset on site switch. This contradicts the confirmed rule that manual period overrides belong to a specific site.

### 3. Totals are flattened too early

`ChatLogService.analyze_bets()` currently derives:

- `visual_rows`
- `StatsResult.totals`

`visual_rows` still preserve `group`, but `StatsResult` does not expose any grouped totals structure. This blocks downstream consumers from asking for grouped summaries without recomputing from raw rows.

## Design Principles

- Prefer narrow fixes over architectural replacement.
- Preserve current public behavior unless it is the thing being corrected.
- Keep compatibility with existing persisted settings where practical.
- Keep the left-side statistics scope and right-side display scope distinct.
- Make each semantic correction visible in tests before implementation.

## Proposed Changes

### 1. Separate global and group block settings

Introduce a dedicated global-name list alongside the existing group-rule map.

State model:

- retain `group_block_rules: dict[str, dict[str, object]]`
- add `global_block_names: list[str]`

Settings model:

- retain `blocked_names_by_group`
- add `global_block_names`
- continue reading legacy `blocked_names` as backward-compatible global defaults if present

Parsing model:

- `ParseOptions.blocked_names` should stop acting as an overloaded field for both scopes
- replace or reinterpret it as an explicit global block list
- `ParseOptions.blocked_names_by_group` remains the group-scoped rule map

Filtering model:

- global filtering uses only the global block-name list and blocked IDs
- group filtering uses only the active message/event group and the matching group rule
- group rules must never be flattened into the global exclusion set

UI model:

- keep the existing per-group editor for `群组屏蔽名单`
- add a separate editor for `全局屏蔽名单`
- summaries and status text should distinguish the two scopes clearly

### 2. Persist period overrides by site

Replace the single shared override with a map keyed by site code.

State model:

- remove the need for one global truth source made of `_query_period_override` plus `_manual_period_override`
- add `self._query_period_overrides_by_site: dict[str, str]`

Behavior model:

- current-site manual state is derived from whether the current site has a non-empty override
- when switching sites, load that site's saved override
- if there is no override for the selected site, the input follows the site's default next-period value
- editing the period input updates only the current site entry

Settings model:

- add `query_period_overrides_by_site`
- continue reading legacy `query_period_override` and `manual_period_override` as migration inputs for backward compatibility

### 3. Add real grouped totals to the statistics result

Extend `StatsResult` rather than replacing it.

Result model:

- keep `StatsResult.totals: dict[str, float]`
- add `StatsResult.totals_by_group: dict[str, dict[str, float]]`

Aggregation model:

- `visual_rows` remain the canonical event-level statistics rows
- `analyze_bets()` accumulates both:
  - one global totals dictionary
  - one grouped totals dictionary keyed by group name

Semantics:

- grouped totals are computed only from rows already inside the selected statistics scope
- if left-side group filters select one group, `totals` becomes that group's total and `totals_by_group` contains only that group
- right-side `可见群组` does not mutate either totals structure

Compatibility:

- callers that only read `stats.totals` continue to work
- new UI or exports can opt into `stats.totals_by_group`

## File-Level Impact

Primary files expected to change:

- `app/models/chat.py`
  - extend `ParseOptions`
  - extend `StatsResult`
- `app/services/settings_service.py`
  - add defaults for new persisted keys
- `app/services/chat_service.py`
  - fix block-list scope handling
  - compute grouped totals
- `app/ui/main_window.py`
  - initialize new runtime state for global block names and site-keyed period overrides
- `app/ui/main_window_blocking.py`
  - manage separate global and group block editors
- `app/ui/main_window_layout.py`
  - add UI controls for the global block list
- `app/ui/main_window_data.py`
  - gather new parse options
  - stop feeding flattened group rules into global filtering
- `app/ui/main_window_realtime.py`
  - bind period-input behavior to current site
- `app/ui/main_window_actions.py`
  - persist and restore the new settings fields
- `tests/test_source_recovery.py`
  - add regression tests for each corrected behavior

Secondary documentation updates may be needed in:

- `CONTEXT.md`
- `docs/chat_analysis_mechanisms.md`

## Migration And Compatibility

The change should preserve existing user settings where possible.

Settings migration rules:

1. if `global_block_names` exists, use it
2. otherwise, if legacy `blocked_names` exists, treat it as the initial global block list
3. keep `blocked_names_by_group` unchanged
4. if `query_period_overrides_by_site` exists, use it
5. otherwise, if legacy `manual_period_override` is true and legacy `query_period_override` is non-empty, seed that value into the currently selected or last-active site when the window state is restored

This is intentionally conservative: the migration should preserve old user intent without inventing per-site values for sites the user never touched.

## Error Handling

- Empty global or group block editors should produce empty persisted lists, not placeholder values.
- Unknown or missing active site should not crash period-override reads or writes; the input should fall back to the current default display behavior.
- Missing group keys in `totals_by_group` should be treated as zero contribution, not as exceptional cases.
- Legacy settings files missing new keys must continue to load successfully.

## Testing Strategy

The work must follow TDD.

Required red-green coverage:

1. a failing test proving a group-specific blocked name no longer removes messages from another group
2. a failing test proving a global blocked name removes messages across groups
3. a failing test proving `_gather_parse_options()` carries separate global and group block data
4. a failing test proving per-site period overrides restore and switch correctly
5. a failing test proving `StatsResult` returns grouped totals alongside existing totals
6. regression coverage proving existing totals behavior remains unchanged for single-group and direct/receipt aggregation cases

Verification after implementation:

- targeted `pytest` runs for the new regression cases
- full `pytest -q`
- `python -m compileall app tests`

## Acceptance Criteria

- A name configured in one group's block list no longer filters messages in other groups.
- A name configured in the global block list filters matching messages in all groups.
- The app persists manual period overrides per site and restores them when switching back to a site.
- `StatsResult` exposes both `totals` and `totals_by_group`.
- Existing consumers that only read `stats.totals` continue to behave correctly.
- Left-side group filters continue to define the statistics scope.
- Right-side `可见群组` does not redefine the statistics scope.

## Out Of Scope

- do not redesign the whole chart panel around grouped totals in this pass
- do not replace the mixin-based main-window structure
- do not introduce new storage backends or a new settings format beyond additive keys
- do not change site-fetching logic, bet parsing semantics, or unrelated UI layout behavior except where required to wire the new controls
