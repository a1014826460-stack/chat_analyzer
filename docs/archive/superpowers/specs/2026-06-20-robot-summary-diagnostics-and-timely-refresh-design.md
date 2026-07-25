# Robot Summary Diagnostics And Timely Refresh Design

**Date:** 2026-06-20

**Owner:** Codex with user confirmation

## Goal

Verify and repair the `机器人汇总校验结果` flow against the current real database's 12 groups, while adding regression coverage so `机器人汇总` messages are never treated as `用户下注`.

The acceptance target is twofold:

1. the current real database's 12 groups can be diagnosed and corrected
2. the failure modes found during that diagnosis are captured in automated tests

## Problem

The user needs every real group in the current database to produce correct robot-summary reconciliation behavior. The current code already separates some robot-summary cases from user bets, but real group formats can still fail at different layers:

1. a robot-summary message may not be recognized
2. a robot-summary message may be parsed by the ordinary user-bet path
3. software-side rows may not be matched to the same group and period
4. a valid `summary_check_record` may not be generated or refreshed when the period ends

When a group fails today, the UI only exposes the absence or presence of a result. That is not enough to tell whether the failure is classification, period matching, robot identity, software rows, or refresh timing.

## Confirmed Requirements

### Functional

1. Produce a structured diagnostic result for each relevant `group + period`.
2. Each diagnostic record must report whether a robot-summary message was detected.
3. Each diagnostic record must report whether that robot-summary message was incorrectly routed through the user-bet path.
4. Each diagnostic record must report whether same-group same-period software-side rows were available.
5. Each diagnostic record must report whether a `summary_check_record` was generated.
6. At the end of each period, update the corresponding `summary_check_record` promptly.
7. Preserve the rule that `机器人汇总` must not be classified as `用户下注`.
8. Preserve the existing `SummaryCheckDialog` display contract unless a small additive change is needed for diagnostics.

### Non-Functional

1. Diagnose root cause before changing parsing behavior.
2. Prefer narrow changes to `ChatLogService` and the existing refresh chain over a new statistics subsystem.
3. Do not store the full real database in tests.
4. Convert real failure patterns into minimal, desensitized fixtures.
5. Keep existing group type and robot identity memory mechanisms intact.

## Recommended Approach

Use the incremental diagnostic-first path:

1. run the current real database through an offline diagnosis pass for the 12 groups
2. classify each failure by layer
3. apply the smallest core logic fix for the root cause
4. add regression tests for every observed failure mode
5. verify both real database behavior and automated tests

This is preferred over directly patching the UI result, because the same visible symptom can come from multiple causes.

## Diagnostic Record Model

Add a structured diagnostic record for one `group + period`.

Expected fields:

- `group_id`
- `group_name`
- `period`
- `group_type`
- `robot_sender_id`
- `robot_summary_detected`
- `robot_summary_message_count`
- `robot_summary_messages`
- `misclassified_as_user_bet`
- `software_rows_found`
- `software_row_count`
- `software_rows`
- `summary_check_record_generated`
- `summary_check_record`
- `failure_reason`

The important semantic split is:

- `robot_summary_detected` answers whether the robot-side summary was recognized
- `misclassified_as_user_bet` answers whether any recognized robot-summary text incorrectly entered the ordinary user-bet path

The `failure_reason` should be explicit when no reconciliation record is produced. Examples:

- `未识别到机器人汇总`
- `识别到了机器人汇总，但没有同群同期软件侧 rows`
- `机器人汇总被误判进用户下注链路`
- `期号未对齐`

## Timely Refresh Design

`summary_check_record` should be rebuilt during message refresh, not only when the user opens the result dialog.

Refresh triggers:

1. a new robot-summary message is observed
2. new same-group same-period software-side rows are observed
3. a period-ending boundary message is observed
4. a boundary message already contains valid summary details

Behavior:

1. Recompute the affected `group + period` record whenever either side changes.
2. If the robot summary arrives after software rows, create or refresh the record immediately.
3. If software rows arrive after the robot summary, create or refresh the record immediately.
4. When a group advances to the next period, preserve the old period's record and create a separate record for the new period.
5. Keep the per-group recent-history behavior, including the existing recent-20-period retention rule.

## Classification Guardrails

Robot-summary formats that must stay out of `用户下注`:

- plain `3447069期下注核对`
- `第3447069期下注核对`
- bracket headers such as `---[H3447069-005]---`
- boundary summaries containing `封盘线` plus `以下投注全部有效` plus summary detail rows
- periodless `本期下注列表`

Related non-summary formats:

- personal status snapshots should remain `机器人状态快照`, not official group summaries
- odds announcements should remain ordinary chat or non-bet content, not user bets

## File-Level Impact

Expected primary files:

- `app/models/chat.py`
  - add an additive diagnostics field to `StatsResult`, likely `summary_check_diagnostics: list[dict[str, object]]`
- `app/services/chat_service.py`
  - build diagnostics
  - guard robot summaries from ordinary user-bet parsing
  - rebuild summary reconciliation records by `group + period`
  - expose the affected records during analysis
- `app/ui/main_window_data.py`
  - keep current refresh flow but carry the newest diagnostics and records into current state
- `tests/test_source_recovery.py`
  - add regression coverage for the real failure patterns

Possible secondary files:

- `app/ui/summary_check_dialog.py`
  - only if diagnostics need a small additive display path
- `docs/bet-statistics-core-logic.md`
  - update after behavior is implemented and verified

## Testing Strategy

Use test-first changes for behavior fixes.

### Classification Tests

Add direct tests that prove:

1. robot-summary samples are recognized as robot summaries
2. robot-summary samples are not classified as `用户下注`
3. personal status snapshots are not official group summaries
4. odds announcements are not user bets

### Service Tests

Add `ChatLogService` tests that assert:

1. diagnostics say whether robot summary was detected
2. diagnostics say whether software rows were found
3. diagnostics say whether a reconciliation record was generated
4. missing software rows produce diagnostics but no `summary_check_record`
5. valid same-group same-period rows produce a `summary_check_record`

### Refresh Tests

Add ordering tests:

1. software rows first, robot summary later
2. robot summary first, software rows later
3. old period is preserved when the next period starts
4. same group can switch periods without records leaking across periods

## Real Database Verification

Create or use an offline diagnosis entry point for the current real database. It should output one structured result per relevant `group + period` and summarize the 12 groups.

For each group, verify:

1. robot summary detection status
2. user-bet misclassification status
3. same-group same-period software rows status
4. generated reconciliation status
5. clear failure reason if no reconciliation is expected

This diagnostic output is the working evidence for the real database side of acceptance.

## Acceptance Criteria

1. The current real database's 12 groups have structured diagnostic output.
2. Every group either generates a correct `summary_check_record` or has a correct, explicit diagnostic reason why no record should be generated.
3. `机器人汇总` messages are not classified as `用户下注`.
4. `summary_check_record` is updated promptly when a period ends or when either reconciliation side arrives.
5. Regression tests cover every real failure pattern found during diagnosis.
6. Existing summary-check UI behavior remains compatible.
7. Existing group type and robot identity memory behavior remains compatible.

## Out Of Scope

- do not rewrite the group type system
- do not replace `SummaryCheckDialog`
- do not redesign the chart or statistics UI
- do not commit real database contents or large raw private samples
- do not change unrelated bet parsing behavior
- do not refactor unrelated main-window mixin structure
