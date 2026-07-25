# StarTrace Business Fidelity Recovery Design

**Date:** 2026-06-10

**Owner:** Codex with user confirmation

## Goal

Recover the damaged `app/` source from the current workspace plus `StarTrace-v1.96.exe` evidence so that the software is not only runnable, but behaves close to the original production build in the business paths the user cares about most.

The recovery target is business fidelity first, not decompilation purity. Where the original source cannot be reconstructed exactly, the implementation should prefer correct user-visible behavior over structural similarity.

## Priority Order

The user confirmed the following recovery order:

1. Priority 2: bet recognition, statistics, and period linkage
2. Priority 1: message loading and display
3. Priority 3: blocked names, group filters, and pagination
4. Priority 5: admin-specific business

Feature 4 is out of scope for this recovery pass.

## Recovery Principle

Use a mixed recovery strategy:

- Default to evidence from the extracted executable, recovered bytecode, decompiled source, and disassembly.
- Keep existing recovered code when it already matches surrounding evidence and does not hurt business behavior.
- Rebuild manually where decompilation is incomplete, syntactically damaged, or semantically flattened.
- If a decision would change statistical results, stop and ask the user before locking in the rule.

This means the project should converge toward the original product behavior, but not by inventing hidden rules without evidence.

## Evidence Hierarchy

When choosing among competing reconstructions, use this order:

1. Runtime-observable behavior required by the current UI and tests
2. `StarTrace-v1.96.exe` extracted artifacts
3. `.codex_recovery/recovered_src/disassembly/**/*.dis.txt`
4. `.codex_recovery/recovered_src/decompiled/**` and `.pyasm`
5. Current recovered `app/` code
6. Local simplifications that preserve the visible business outcome

If two sources disagree, prefer the one closer to executable evidence unless it would obviously break the current UI contract.

## Current Gap

The current project is in a partially recovered state:

- The application starts and the basic UI can load.
- `chat_service.py` and `main_window_data.py` are presently simplified recovery builds.
- Those files are good enough for startup, but not yet good enough for high-confidence business fidelity.
- The Git index is currently corrupted, so Git-based verification and commit-based checkpoints are not reliable until the index is repaired.

## Scope by Business Area

### 1. Bet Recognition, Statistics, and Period Linkage

This is the primary recovery target.

The restored service must recover the original-style behavior for:

- bet token recognition
- amount extraction
- ordering and grouping of multiple bet events inside one message
- direct and contextual period assignment
- cancellation, override, or exclusion signals when supported by evidence
- aggregation into visual rows and summary totals

Acceptance signal for this area:

- the same representative message set produces the same totals and period attribution as the executable evidence indicates
- no simplified fallback remains in the critical parsing path unless explicitly accepted by the user

### 2. Message Loading and Display

This is the second recovery target.

The restored data flow must support:

- account resolution and manual source selection
- group discovery from source data
- background loading without freezing the UI
- full-load and incremental-load behavior
- applying loaded messages, visual rows, and stats back into the UI state

Acceptance signal for this area:

- the main window can resolve or select a source, load messages, and refresh the table/chart path without blocking
- load sequencing, cursor handling, and displayed counts remain internally consistent

### 3. Blocked Names, Group Filters, and Pagination

This is the third recovery target.

The restored behavior must support:

- blocked usernames
- blocked user IDs where evidence exists
- group-scoped blocking rules
- selected-group filtering
- any message-window or paging behavior directly used by the UI

Acceptance signal for this area:

- changing these controls visibly changes the loaded/visualized result set in the same way the original build suggests
- filtering does not silently distort stats outside the selected rules

### 4. Admin-Specific Business

This is the fourth recovery target in this pass.

The restored admin behavior should include only business-relevant flows still referenced by the current app, especially:

- admin startup path
- license-gated or privileged UI branches still present in the recovered code
- admin-only state refreshes that affect the core data workflow

Acceptance signal for this area:

- admin mode launches and the remaining business-critical admin controls behave consistently with the recovered build

## Module Focus

The highest-risk modules for business fidelity are:

- `app/services/chat_service.py`
- `app/ui/main_window_data.py`

Secondary supporting modules may need aligned fixes:

- `app/ui/main_window.py`
- `app/ui/main_window_actions.py`
- `app/ui/main_window_realtime.py`
- `app/ui/main_window_blocking.py`
- `app/services/license_service.py`
- `app/models/chat.py`

The recovery should avoid broad refactors outside the modules needed to restore the four scoped business areas.

## Implementation Phases

### Phase A: Evidence Mapping

Build a clear mapping from executable evidence to today's simplified implementations.

Deliverables:

- identified method-level gaps in `chat_service.py`
- identified method-level gaps in `main_window_data.py`
- a list of ambiguity points that would affect totals, period assignment, or exclusion logic

### Phase B: Core Statistics Recovery

Reconstruct `ChatLogService` so the parsing and stats path matches executable evidence as closely as possible.

Deliverables:

- restored bet parsing structures
- restored stats/visual-row pipeline
- targeted tests using representative messages

Stop-and-ask gate:

- any unresolved ambiguity that would change amount, play type, period, or cancellation outcome

### Phase C: Data Loading Recovery

Reconstruct the main window data workflow around the restored chat service.

Deliverables:

- restored load-option construction
- restored worker pipeline and UI result application
- message/group refresh behavior aligned with current main window

### Phase D: Filtering and Admin Recovery

Restore the remaining business filters and admin-specific branches still needed by the app.

Deliverables:

- blocked/group filter behavior aligned with the recovered service
- admin-mode path sanity checked against the current UI

### Phase E: End-to-End Verification

Verify the recovered build at both source and behavior level.

Deliverables:

- focused regression tests for statistics-sensitive behavior
- compile verification
- startup verification
- explicit list of any remaining inferred behavior

## Ambiguity Escalation Rule

The user requested a mixed recovery approach with a hard pause whenever a choice would affect statistical results.

Therefore, the implementation may proceed without asking only when the choice does **not** change:

- recognized bet type
- parsed amount
- period assignment
- inclusion or exclusion of a betting event
- aggregate totals

If any of those outcomes could change, implementation must stop and present the exact ambiguity, the competing interpretations, and the likely statistical difference before continuing.

## Testing Strategy

Testing should be centered on business behavior, not only importability.

Required test layers:

- targeted parser/statistics tests for `ChatLogService`
- workflow tests for `MainWindowDataMixin` where practical
- existing compile and startup safety checks

The preferred evidence style is a small, explicit fixture set whose expected outputs are traceable back to executable evidence or unambiguous disassembly.

## Non-Goals

This recovery pass does not aim to:

- perfectly reproduce every original source line
- recover feature 4
- perform unrelated architecture cleanup
- silently guess missing business rules that would alter totals

## Done Definition

This recovery is complete for the current pass when:

- the priority order `2 > 1 > 3 > 5` has been addressed in sequence
- the core statistics path is no longer using obvious simplified fallback logic
- the main data-loading UI path works without freezing and stays consistent with recovered business rules
- remaining filter/admin behaviors needed by the app are restored
- tests and runtime verification pass
- every remaining known gap is explicitly documented
