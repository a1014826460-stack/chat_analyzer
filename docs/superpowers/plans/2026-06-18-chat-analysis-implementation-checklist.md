# Chat Analysis Implementation Checklist

**Goal:** Turn the confirmed chat-analysis business rules into an implementation-ready checklist mapped to the current codebase.

**Scope:** This checklist covers direct-group vs receipt-group semantics, robot detection, period-boundary handling, raw-chat semantic review, group-type persistence, and per-play reconciliation.

**Primary modules:**
- `app/services/chat_service.py`
- `app/services/settings_service.py`
- `app/models/chat.py`
- `app/ui/raw_chat_dialog.py`
- `app/ui/main_window.py`
- `app/ui/main_window_layout.py`
- `app/ui/main_window_actions.py`
- `app/ui/main_window_data.py`
- `tests/test_source_recovery.py`

---

## 1. Confirmed Domain Rules

### 1.1 Group semantics

- `直接群`:
  Main statistics source is user raw bet messages.
- `回执群`:
  Main statistics source is robot receipt/summary messages.
- Direct-group statistics must not silently switch to receipt-group semantics only because a few robot messages appear.
- Receipt-group statistics must not automatically downgrade back to direct-group semantics when receipt messages are temporarily absent.

### 1.2 Group type persistence

- `群类型` has only two values:
  `direct` and `receipt`.
- Group type persistence must use `群 ID`, not group name.
- System may suggest switching a direct group to receipt-group semantics.
- Final group-type switch must be confirmed manually.
- Suggested switch threshold:
  In the same group, within a 10-minute window, at least 3 consecutive robot messages that match standard receipt format.
- Standard receipt-format minimum rule:
  Message contains both `下注期数` and `下注内容`.
- After manual confirmation of a group-type switch, messages in the current statistics scope should be reinterpreted under the new group type.
- Manual switch records should keep:
  switch time and optional switch note.

### 1.3 Robot detection

- Primary rule:
  `nickname` contains `机器`.
- Fallback rule:
  If no such nickname exists in the group, choose the most talkative user in the last 20 minutes, but only if their message shape still matches robot-like patterns.
- Robot identity should be persisted locally by group to avoid repeated re-detection.

### 1.4 Direct-group boundary handling

- Boundary messages belong to robot messages only.
- Start marker usually contains:
  `开始下注` or `下注开始`.
- End marker usually contains:
  `截止线`, `封盘线`, or `已截止`.
- Same period should have only one start marker and one end marker.
- If duplicate same-kind boundary markers appear in one period:
  only the first one is effective;
  later duplicates are noise for review only, not for period slicing.
- In direct groups, boundary messages may omit explicit period.
- In that case, period ownership may be inferred from:
  line time window or latest available period context.
- In review UI, inferred-period boundary messages should be visually distinguishable from explicit-period boundary messages.

### 1.5 Robot message categories

- `下注归期边界消息`
- `机器人回执/汇总消息`
- `开奖结果播报消息`
- `机器人状态快照消息`

Rules:

- Result-broadcast messages do not participate in group-type switch suggestions.
- State-snapshot messages remain state snapshots even if they contain `本期下注`.
- State-snapshot messages should not be treated as standard receipt messages by default.

### 1.6 Reconciliation

- Reconciliation must compare per:
  period + group + play type.
- Tolerance rule:
  relative error `<= 10%` is acceptable.
- Review UI should explicitly show:
  `通过（容差内）`, not just raw diff values.

### 1.7 Raw chat review

- Raw chat view must support semantic coloring.
- Raw chat view must support semantic category filters, not color-only review.
- At minimum, review categories should cover:
  boundary, inferred boundary, receipt/summary, result broadcast, state snapshot, user bet, cancel/change, normal chat.

---

## 2. Current Code Conflicts

### 2.1 Group type is not persisted yet

Current behavior in `app/services/chat_service.py`:

- `_resolve_single_group_bet_events()` routes by `_is_zodiac_group(group_name)`.
- `_is_zodiac_group()` relies on `ZODIAC_GROUP_NAMES`.

Why this conflicts with confirmed rules:

- It is name-based, not group-ID-based.
- It is not persisted as explicit group type.
- It cannot support manual confirmation, switch time, or switch note.

### 2.2 Robot detection is still too weak

Current behavior in `app/services/chat_service.py`:

- `_is_group_member_robot()` currently only checks whether the fallback username contains `机器`.

Why this conflicts with confirmed rules:

- No 20-minute talk-count fallback.
- No robot-format validation in fallback mode.
- No per-group persistence.

### 2.3 Direct-group boundary logic is incomplete

Current behavior in `app/services/chat_service.py`:

- `_extract_direct_group_marker()` still uses legacy text heuristics.
- The file currently contains duplicate `_extract_direct_group_marker()` definitions; later one wins.

Why this conflicts with confirmed rules:

- Start/end keywords are not normalized to the confirmed vocabulary.
- Duplicate-marker noise handling is not explicit.
- Explicit-period vs inferred-period boundary review is not modeled.

### 2.4 Raw chat review is still plain text

Current behavior in `app/ui/raw_chat_dialog.py`:

- `_message_html()` renders a bold header and escaped content only.
- There is no semantic classification, no color mapping, and no category filter UI.

### 2.5 Reconciliation capability is not complete

Current behavior in `app/services/chat_service.py` and UI:

- The project can parse receipt-style messages.
- The project does not yet present a dedicated per-play reconciliation result with tolerance-aware status labels.

---

## 3. Module-by-Module Implementation Checklist

### 3.1 Add persistent group-type storage

**Primary files:**
- Modify `app/services/settings_service.py`
- Modify `app/ui/main_window.py`
- Modify `app/ui/main_window_actions.py`
- Modify `app/models/chat.py`

**Checklist:**
- Add persisted settings payload for group-type memory keyed by group ID.
- Add persisted payload for:
  switch time, switch note, and suggestion state if needed.
- Ensure load/save round-trip is stable even when old settings files lack the new fields.
- Keep backward compatibility with current `settings.json`.

**Acceptance:**
- Restarting the app preserves confirmed group type by group ID.
- Group rename does not lose remembered type.

### 3.2 Replace name-based group routing with persisted group-type routing

**Primary files:**
- Modify `app/services/chat_service.py`
- Modify `app/ui/main_window_data.py`
- Modify `app/ui/main_window_actions.py`
- Test `tests/test_source_recovery.py`

**Checklist:**
- Remove group-type authority from `_is_zodiac_group()`.
- Route `direct` vs `receipt` by persisted group-type lookup.
- Preserve a fallback bootstrap rule only until explicit group type is known.
- Add manual switch workflow entry points in UI state/actions.

**Acceptance:**
- Same group ID always uses the remembered semantics.
- Manual switch to `receipt` causes current-scope recalculation.

### 3.3 Implement receipt-group suggestion detection

**Primary files:**
- Modify `app/services/chat_service.py`
- Modify `app/ui/main_window.py`
- Modify `app/ui/main_window_layout.py`
- Modify `app/ui/main_window_actions.py`
- Test `tests/test_source_recovery.py`

**Checklist:**
- Detect standard receipt messages using the minimum rule:
  both `下注期数` and `下注内容`.
- Restrict evidence to robot messages only.
- Track same-group consecutive receipt evidence in a 10-minute window.
- Suggest, but do not auto-switch.
- Add UI surface for:
  review suggestion, confirm switch, save switch note.

**Acceptance:**
- Fewer than 3 qualifying robot receipt messages do not trigger suggestion.
- 3 consecutive qualifying robot receipt messages in 10 minutes do trigger suggestion.
- Declining the suggestion does not mutate group type.

### 3.4 Implement robot-detection fallback and persistence

**Primary files:**
- Modify `app/services/chat_service.py`
- Modify `app/services/settings_service.py`
- Modify `app/ui/main_window_actions.py`
- Test `tests/test_source_recovery.py`

**Checklist:**
- Keep nickname-contains-`机器` as primary rule.
- Add fallback:
  most-talkative user in the last 20 minutes.
- Validate fallback candidate against robot-like message format before accepting.
- Persist resolved robot identity by group ID.

**Acceptance:**
- If no nickname contains `机器`, system can still resolve robot candidate only when message shape supports it.
- Repeated parses do not re-run expensive detection unnecessarily.

### 3.5 Normalize direct-group boundary classification

**Primary files:**
- Modify `app/services/chat_service.py`
- Test `tests/test_source_recovery.py`

**Checklist:**
- Consolidate duplicated `_extract_direct_group_marker()` logic into one authoritative implementation.
- Detect start markers from:
  `开始下注`, `下注开始`.
- Detect end markers from:
  `截止线`, `封盘线`, `已截止`.
- Keep only the first same-kind marker per period as effective.
- Treat later same-kind markers in the same period as review-only noise.
- Distinguish:
  explicit-period boundary vs inferred-period boundary.

**Acceptance:**
- Duplicate start markers do not create duplicate active windows.
- Direct-group period slicing stays stable when explicit period is missing but inference context exists.

### 3.6 Introduce message semantic classification primitives

**Primary files:**
- Modify `app/services/chat_service.py`
- Modify `app/models/chat.py`
- Test `tests/test_source_recovery.py`

**Checklist:**
- Add a structured semantic-classification result for raw-chat review.
- At minimum classify:
  robot boundary,
  inferred robot boundary,
  robot receipt/summary,
  robot result broadcast,
  robot state snapshot,
  user bet,
  cancel/change,
  normal chat.
- Keep sender role and message semantic category as separate concepts.

**Acceptance:**
- Same raw message can be reviewed with:
  sender role + semantic class,
  without polluting main statistics semantics.

### 3.7 Upgrade raw-chat dialog into a semantic review tool

**Primary files:**
- Modify `app/ui/raw_chat_dialog.py`
- Modify `app/ui/main_window_layout.py`
- Modify `app/ui/main_window_actions.py`
- Test `tests/test_source_recovery.py`

**Checklist:**
- Add semantic category filters to the dialog.
- Add color mapping for each category.
- Give inferred-period boundary a distinct style from explicit-period boundary.
- Preserve current paging and scroll-position behavior.
- Keep group filter working alongside semantic filters.

**Acceptance:**
- User can review only selected semantic categories.
- Raw chat remains readable on long histories.

### 3.8 Add per-play reconciliation output

**Primary files:**
- Modify `app/services/chat_service.py`
- Modify `app/ui/main_window_data.py`
- Modify `app/ui/chart_window.py`
- Possibly create a focused review widget or extend existing right-side panel
- Test `tests/test_source_recovery.py`

**Checklist:**
- Compare statistics per:
  period, group, play type.
- Surface:
  software value,
  robot value,
  absolute diff,
  relative diff,
  status.
- Map `<= 10%` relative error to:
  `通过（容差内）`.
- Keep receipt-group vs direct-group source semantics separate during comparison.

**Acceptance:**
- Reconciliation view does not collapse all plays into one total-only result.
- Tolerance-aware pass state is explicit.

---

## 4. Suggested Implementation Order

1. Persist group type by group ID.
2. Replace `_is_zodiac_group()` routing authority.
3. Implement receipt-suggestion detection + manual switch workflow.
4. Implement robot-detection fallback + persistence.
5. Consolidate direct-group boundary logic.
6. Add semantic message classification primitives.
7. Upgrade raw-chat dialog with category filters and colors.
8. Add per-play reconciliation UI and tolerance-aware statuses.

Reason:

- Steps 1-5 stabilize main statistics semantics first.
- Steps 6-7 improve human review tooling on top of stable semantics.
- Step 8 depends on both stable semantics and accessible classification outputs.

---

## 5. Test Focus

**Primary test file:**
- `tests/test_source_recovery.py`

**Add or extend tests for:**
- group type persisted by group ID
- manual switch causes recalculation
- no auto-downgrade from receipt to direct
- receipt-group suggestion threshold:
  3 qualifying robot receipts in 10 minutes
- robot detection fallback:
  most-talkative candidate + robot-shape validation
- direct-group duplicate boundary noise handling
- explicit-period vs inferred-period boundary review metadata
- raw-chat semantic filtering and coloring
- per-play reconciliation statuses with tolerance handling

---

## 6. First Files To Touch

If implementation starts immediately, begin here:

1. `app/services/settings_service.py`
2. `app/models/chat.py`
3. `app/services/chat_service.py`
4. `app/ui/main_window_actions.py`
5. `app/ui/main_window_data.py`
6. `app/ui/raw_chat_dialog.py`
7. `tests/test_source_recovery.py`

These files cover:

- persistence
- parsing/routing
- recalculation entry points
- review UI
- regression protection
