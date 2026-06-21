# Main Window State And Refresh Design

**Date:** 2026-06-21

**Owner:** Codex with user confirmation

## Goal

Improve the main analysis window so it:

1. restores the previous window size and splitter position across launches
2. falls back to screen-adaptive sizing when no previous state exists
3. preserves visible-group check state across every refresh, including groups that temporarily disappear and later return
4. reduces UI stutter during the 5-second auto-refresh cycle

## Confirmed User Decisions

### Window startup behavior

Use this priority order:

1. restore the last saved window geometry and splitter state
2. if no saved state exists, size the window dynamically from the current screen's available geometry

### Group visibility persistence

Use durable per-group memory:

1. a group's checked state must survive ordinary refreshes
2. a group's checked state must survive list reordering
3. if a group disappears from the current group list and later returns, it must recover its last remembered checked state

## Current Problems

### Fixed window sizing

`app/ui/main_window.py` currently hard-codes:

- `self.resize(1400, 900)`

This ignores different screen sizes and user-adjusted layouts.

### Fixed splitter sizing

`app/ui/main_window_data.py` currently hard-codes:

- `self.main_splitter.setSizes([240, 1160])`

This does not adapt to screen width and does not remember the user's last layout.

### Group check state is only partially persistent

The current settings save:

- `selected_group_ids`
- `selected_group_mode`

That is enough for simple restore while the group list is stable, but it does not fully encode the user's per-group intent once the list contents change over time.

### Auto-refresh still causes UI churn

Message loading already runs in a worker thread, but the result application path still eagerly refreshes several UI surfaces:

- raw chat dialog data
- chart rows and chart activity
- accumulated stats rebuild
- summary-check rebuild and persistence

When this happens every 5 seconds, users can feel visible stutter.

## Design Principles

1. Keep the existing mixin structure.
2. Prefer additive state fields over replacing the current settings format.
3. Preserve compatibility with existing saved settings.
4. Improve perceived responsiveness by skipping unnecessary UI work, not by weakening business correctness.
5. Keep the auto-refresh data load authoritative; optimize the UI application path around it.

## Recommended Approach

Use additive persisted UI state plus refresh diffing.

This is preferred over a deep rewrite because:

1. it solves all four requested problems
2. it keeps changes local to `MainWindow`, `MainWindowDataMixin`, and `MainWindowActionsMixin`
3. it minimizes regression risk in the parsing and statistics pipeline

## Persisted UI State Model

Add the following settings fields:

- `window_geometry_b64`
- `window_state_b64`
- `main_splitter_sizes`
- `group_check_memory_by_id`

### Semantics

#### `window_geometry_b64`

Stores the serialized `QMainWindow.saveGeometry()` payload as base64 text.

#### `window_state_b64`

Stores the serialized `QMainWindow.saveState()` payload as base64 text.

This is optional but useful if the main window later gains dockable state or additional Qt-managed layout state.

#### `main_splitter_sizes`

Stores the current `QSplitter.sizes()` list.

This acts as:

1. a direct restore source for splitter position
2. a fallback if Qt geometry restore succeeds but splitter restore is not reliable enough on some machines

#### `group_check_memory_by_id`

Stores a mapping:

```json
{
  "207191791": true,
  "203483000": false
}
```

This is the durable source of truth for each known group's last user-selected visible state.

## Window Sizing Design

### Startup order

When the analysis window is first shown:

1. attempt to restore saved window geometry
2. if that fails or no geometry exists, compute a default size from the current screen's available geometry
3. enforce the existing minimum size
4. after the window size is stable, apply splitter restore logic

### Adaptive fallback sizing

Use the screen's available geometry, not total geometry, so taskbars and docked system UI are respected.

Recommended default:

1. width around `90%` of available width
2. height around `88%` to `90%` of available height
3. clamp to the existing minimum size

The exact percentages are implementation details; the requirement is that fallback sizing must feel large and natural on both small and large screens without forcing full-screen mode.

## Splitter Restore Design

### Restore order

When the main window first shows:

1. if saved splitter sizes exist and look valid, restore them
2. otherwise compute a proportional default from the actual current window width

### Default proportional layout

Replace the fixed `[240, 1160]` with a ratio-based calculation.

Recommended intent:

1. left pane roughly `22%` to `26%`
2. right pane uses the remainder

This keeps the left control panel usable while allowing the chart area to dominate the screen.

## Group Visibility Persistence Design

### Source of truth

Use `group_check_memory_by_id` as the durable restore source for each group's checkbox.

Retain:

- `selected_group_ids`
- `selected_group_mode`

But reinterpret them as summary state rather than the only restore mechanism.

### Refresh behavior

When `_load_groups_from_current_source()` rebuilds the group list:

1. read the latest `group_check_memory_by_id`
2. for each current group ID:
   - if the group exists in memory, restore that exact checked state
   - otherwise fall back to the legacy mode logic for first-seen groups
3. do not erase memory for groups that are not present in the current refresh

### User interaction behavior

Whenever a user changes:

- a single group checkbox
- all-select
- invert
- clear

Update both:

- the current live list state
- `group_check_memory_by_id`

This guarantees that a later list rebuild reproduces the user's last intent.

### Backward compatibility

If old settings have no `group_check_memory_by_id`:

1. seed it from the current live list or from `selected_group_ids`
2. continue saving both legacy and new fields

This prevents existing users from losing their current filter behavior.

## Auto-Refresh Performance Design

### Root cause

The main refresh cost is not only data retrieval. It is repeated UI application work after each refresh cycle, especially when the effective visible result has not changed enough to justify repainting everything.

### Optimization strategy

Use cheap change detection before expensive UI updates.

#### 1. Track UI-facing result signatures

Build lightweight signatures for:

- current message cursor / count
- visible chart rows
- stats totals
- summary-check payload

If a refresh result matches the currently displayed signature, skip the corresponding UI update path.

#### 2. Avoid unconditional raw chat dialog refresh

Only call `_refresh_message_view()` when:

1. the raw chat dialog is open
2. the visible message set actually changed

#### 3. Avoid unconditional chart refresh

Only call:

- `chart_window.replace_rows(...)`
- `chart_window.update_activity(...)`

when row content or accumulated activity actually changed.

#### 4. Avoid repeated summary-check rebuild on no-op refreshes

Only rebuild and persist summary-check output when:

1. visual rows changed
2. relevant messages changed
3. summary-check diagnostics changed

#### 5. Reduce settings write pressure

Saving settings on every user interaction is acceptable, but auto-refresh paths should not trigger repeated settings writes.

Group persistence updates should still save promptly on user changes, while periodic data refresh should remain read-only from a settings perspective.

## File-Level Impact

### `app/ui/main_window.py`

Responsibilities:

1. remove fixed initial `resize(1400, 900)` behavior as the primary startup strategy
2. add startup restore hooks for geometry/state
3. save geometry/state on close
4. keep first-show initialization order correct

### `app/ui/main_window_data.py`

Responsibilities:

1. replace fixed splitter sizes with restore-or-ratio logic
2. rebuild group list using durable per-group check memory
3. add result signature checks in the refresh apply path
4. skip no-op UI refresh work

### `app/ui/main_window_actions.py`

Responsibilities:

1. maintain `group_check_memory_by_id`
2. persist it whenever group selection changes
3. expose helpers that compute and update durable group state cleanly

### `app/services/settings_service.py`

Responsibilities:

1. include defaults for the new UI state fields
2. keep backward compatibility with old settings files

### `tests/test_source_recovery.py`

Responsibilities:

1. add regression coverage for geometry/splitter persistence helpers
2. add coverage for group memory restore behavior
3. add coverage for no-op refresh short-circuiting

## Testing Strategy

### Window state tests

Add tests that prove:

1. when saved geometry/splitter data exists, restore helpers prefer it
2. when no saved state exists, fallback sizing uses screen-aware logic
3. invalid saved splitter data falls back safely instead of breaking the UI

### Group memory tests

Add tests that prove:

1. checked groups remain checked after `_load_groups_from_current_source()`
2. unchecked groups remain unchecked after refresh
3. a previously known group that disappears and later returns restores its last remembered state
4. all-select, invert, and clear correctly update durable memory

### Refresh performance tests

Add tests that prove:

1. `_apply_load_result()` skips expensive UI refresh calls when signatures are unchanged
2. raw chat refresh is skipped when no visible messages changed
3. chart update is skipped when rows are unchanged
4. summary-check persistence is skipped when the summary payload is unchanged

These tests should focus on call/no-call behavior with small doubles or `SimpleNamespace` fixtures, not on timing benchmarks.

## Acceptance Criteria

1. On close and reopen, the main window restores its last size and position.
2. On close and reopen, the splitter restores its last position.
3. If there is no saved window state, the initial window size adapts to the current screen.
4. If there is no saved splitter state, the splitter uses a proportional default rather than a hard-coded width pair.
5. Group check state remains stable across every 5-second refresh.
6. A group that temporarily disappears from the list and later returns restores its last remembered visible state.
7. The auto-refresh path avoids unnecessary UI refresh work when the displayed data is effectively unchanged.
8. The user perceives less stutter during normal 5-second refresh cycles, without weakening statistics correctness.

## Out Of Scope

1. rewriting the chart window architecture
2. changing business parsing logic for bets
3. redesigning the main visual layout
4. introducing asynchronous partial rendering frameworks
5. changing the 5-second refresh cadence itself
