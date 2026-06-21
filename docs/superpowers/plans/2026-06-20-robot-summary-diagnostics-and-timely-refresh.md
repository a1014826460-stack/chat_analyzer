# Robot Summary Diagnostics And Timely Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structured robot-summary diagnostics, keep `机器人汇总` out of `用户下注`, and refresh `summary_check_record` promptly for the current real database workflow.

**Architecture:** Extend the existing `ChatLogService` analysis pipeline so it emits both reconciliation records and per-`group + period` diagnostic records from the same message pass. Keep the current UI contract intact by threading additive diagnostics through `StatsResult` and the refresh mixins, then add a small offline diagnosis entry point for real-database verification.

**Tech Stack:** Python 3, dataclasses, PySide6 app state mixins, pytest

---

### Task 1: Add failing tests for service-level diagnostics

**Files:**
- Modify: `tests/test_source_recovery.py`
- Modify: `app/models/chat.py`
- Modify: `app/services/chat_service.py`

- [ ] **Step 1: Write the failing test**

```python
def test_chat_service_exposes_robot_summary_diagnostics_for_group_period() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 20, 10, 0, 0),
            group="A群",
            username="玩家A",
            sender_id="user-a",
            content="大单80 小单100",
            group_id="group-a",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 20, 10, 0, 8),
            group="A群",
            username="机器人A",
            sender_id="robot-a",
            content="--------[3448001]期-------\n玩家A 1000【大单100 小单100 】",
            group_id="group-a",
        ),
    ]

    _rows, stats = service.analyze_bets(
        messages,
        blocked_names=[],
        blocked_ids=[],
        period_filter="3448001",
        site="pc28",
        period_window_start=datetime(2026, 6, 20, 10, 0, 0),
        period_window_end=datetime(2026, 6, 20, 10, 1, 0),
        period_interval_sec=60,
        group_types_by_id={"group-a": "direct"},
    )

    diagnostics = getattr(stats, "summary_check_diagnostics", [])
    assert len(diagnostics) == 1
    record = diagnostics[0]
    assert record["group"] == "A群"
    assert record["period"] == "3448001"
    assert record["robot_summary_detected"] is True
    assert record["misclassified_as_user_bet"] is False
    assert record["software_rows_found"] is True
    assert record["summary_check_record_generated"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -k "robot_summary_diagnostics_for_group_period" -v`
Expected: FAIL because `StatsResult` does not yet expose `summary_check_diagnostics`

- [ ] **Step 3: Write minimal implementation**

```python
@dataclass
class StatsResult:
    totals: dict[str, float]
    matched_messages: int = 0
    exported_records: int = 0
    totals_by_group: dict[str, dict[str, float]] = field(default_factory=dict)
    summary_check_period: str = ""
    summary_check_totals: dict[str, float] = field(default_factory=dict)
    summary_check_by_play: dict[str, dict[str, float | bool]] = field(default_factory=dict)
    summary_check_records: list[dict[str, object]] = field(default_factory=list)
    summary_check_diagnostics: list[dict[str, object]] = field(default_factory=list)
    unresolved_receipts: list[dict[str, object]] = field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -k "robot_summary_diagnostics_for_group_period" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_source_recovery.py app/models/chat.py app/services/chat_service.py
git commit -m "test: add robot summary diagnostics coverage"
```

### Task 2: Add failing tests for missing software rows diagnostics

**Files:**
- Modify: `tests/test_source_recovery.py`
- Modify: `app/services/chat_service.py`

- [ ] **Step 1: Write the failing test**

```python
def test_chat_service_reports_missing_same_period_software_rows_in_diagnostics() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 20, 10, 0, 8),
            group="A群",
            username="机器人A",
            sender_id="robot-a",
            content="--------[3448002]期-------\n玩家A 1000【大单100 小单100 】",
            group_id="group-a",
        ),
    ]

    _rows, stats = service.analyze_bets(
        messages,
        blocked_names=[],
        blocked_ids=[],
        period_filter="3448002",
        site="pc28",
        period_window_start=datetime(2026, 6, 20, 10, 0, 0),
        period_window_end=datetime(2026, 6, 20, 10, 1, 0),
        period_interval_sec=60,
        group_types_by_id={"group-a": "direct"},
    )

    assert stats.summary_check_records == []
    diagnostics = stats.summary_check_diagnostics
    assert len(diagnostics) == 1
    record = diagnostics[0]
    assert record["robot_summary_detected"] is True
    assert record["software_rows_found"] is False
    assert record["summary_check_record_generated"] is False
    assert record["failure_reason"] == "识别到了机器人汇总，但没有同群同期软件侧 rows"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -k "missing_same_period_software_rows_in_diagnostics" -v`
Expected: FAIL because diagnostics do not yet include missing-software-rows reasons

- [ ] **Step 3: Write minimal implementation**

```python
diagnostic = {
    "group": snapshot.group,
    "period": snapshot.period,
    "robot_summary_detected": True,
    "software_rows_found": bool(group_software_totals),
    "summary_check_record_generated": bool(group_software_totals),
    "failure_reason": "" if group_software_totals else "识别到了机器人汇总，但没有同群同期软件侧 rows",
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -k "missing_same_period_software_rows_in_diagnostics" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_source_recovery.py app/services/chat_service.py
git commit -m "test: cover missing software rows diagnostics"
```

### Task 3: Add failing tests for timely refresh from accumulated rows

**Files:**
- Modify: `tests/test_source_recovery.py`
- Modify: `app/ui/main_window_data.py`
- Modify: `app/models/chat.py`

- [ ] **Step 1: Write the failing test**

```python
def test_main_window_sync_stats_rebuilds_summary_check_diagnostics_from_accumulated_rows() -> None:
    from datetime import datetime
    from types import SimpleNamespace

    from app.models import StatsResult
    from app.ui.main_window_data import MainWindowDataMixin

    class DummyService:
        def _software_totals_until_snapshot(self, rows, snapshot_time):
            totals = {}
            for row in rows:
                totals[row["play"]] = totals.get(row["play"], 0.0) + float(row["amount"])
            return totals

        def _format_robot_summary_reconciliation(self, snapshot, software_totals):
            return {
                "group": snapshot.group,
                "period": snapshot.period,
                "summary_time": snapshot.ts,
                "robot_totals": dict(snapshot.totals),
                "software_totals": dict(software_totals),
                "by_play": {},
            }

        def build_summary_check_diagnostics(self, messages, software_rows_by_group_period, period_filter, summary_check_records):
            return [{
                "group": "A群",
                "period": "3448003",
                "robot_summary_detected": True,
                "misclassified_as_user_bet": False,
                "software_rows_found": True,
                "summary_check_record_generated": True,
                "failure_reason": "",
            }]

    dummy = SimpleNamespace(
        current_stats=StatsResult(
            totals={"大单": 100.0},
            summary_check_records=[{
                "group": "A群",
                "period": "3448003",
                "summary_time": datetime(2026, 6, 20, 10, 0, 8),
                "robot_totals": {"大单": 100.0},
                "software_totals": {"大单": 100.0},
                "by_play": {},
            }],
        ),
        current_visual_rows=[
            {"group": "A群", "period": "3448003", "play": "大单", "amount": 100.0, "time": datetime(2026, 6, 20, 10, 0, 0), "source_kind": "direct"},
        ],
        chart_window=None,
        chat_service=DummyService(),
    )

    MainWindowDataMixin._sync_stats_from_accumulated_visual_rows(dummy)

    assert dummy.current_stats.summary_check_diagnostics == [{
        "group": "A群",
        "period": "3448003",
        "robot_summary_detected": True,
        "misclassified_as_user_bet": False,
        "software_rows_found": True,
        "summary_check_record_generated": True,
        "failure_reason": "",
    }]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -k "sync_stats_rebuilds_summary_check_diagnostics_from_accumulated_rows" -v`
Expected: FAIL because `_sync_stats_from_accumulated_visual_rows()` does not yet populate `summary_check_diagnostics`

- [ ] **Step 3: Write minimal implementation**

```python
diagnostics = []
builder = getattr(self.chat_service, "build_summary_check_diagnostics", None)
if callable(builder):
    diagnostics = builder(
        getattr(self, "current_messages", []) or [],
        {key: list(value) for key, value in software_rows_by_group_period.items()},
        str(summary_check.get("period", "") or ""),
        records,
    )

self.current_stats = StatsResult(
    totals=dict(totals),
    matched_messages=int(getattr(stats, "matched_messages", 0) or 0),
    exported_records=int(getattr(stats, "exported_records", 0) or 0),
    totals_by_group={group: dict(group_totals) for group, group_totals in totals_by_group.items()},
    summary_check_period=str(summary_check.get("period", "") or ""),
    summary_check_totals=dict(summary_check.get("robot_totals", {}) or {}),
    summary_check_by_play=dict(summary_check.get("by_play", {}) or {}),
    summary_check_records=records,
    summary_check_diagnostics=[dict(item) for item in diagnostics if isinstance(item, dict)],
    unresolved_receipts=[dict(row) for row in getattr(stats, "unresolved_receipts", []) or []],
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -k "sync_stats_rebuilds_summary_check_diagnostics_from_accumulated_rows" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_source_recovery.py app/ui/main_window_data.py app/models/chat.py
git commit -m "test: cover timely summary diagnostics refresh"
```

### Task 4: Implement robot-summary diagnostics builder and keep summary messages out of user-bet flow

**Files:**
- Modify: `app/services/chat_service.py`
- Modify: `app/models/chat.py`
- Test: `tests/test_source_recovery.py`

- [ ] **Step 1: Write the failing test**

```python
def test_chat_service_diagnostics_marks_robot_summary_as_not_misclassified() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 20, 11, 0, 8),
            group="A群",
            username="机器人A",
            sender_id="robot-a",
            content="-----本期下注列表-----\n\n加拿大PC蛋蛋\n【谢伟-50405】小单600|大双1600",
            group_id="group-a",
        ),
    ]

    _rows, stats = service.analyze_bets(
        messages,
        blocked_names=[],
        blocked_ids=[],
        period_filter="",
        site="pc28",
        period_window_start=None,
        period_window_end=None,
        period_interval_sec=60,
        group_types_by_id={"group-a": "direct"},
    )

    diagnostics = stats.summary_check_diagnostics
    assert len(diagnostics) == 1
    assert diagnostics[0]["misclassified_as_user_bet"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -k "robot_summary_as_not_misclassified" -v`
Expected: FAIL because no diagnostics builder currently reports misclassification status

- [ ] **Step 3: Write minimal implementation**

```python
def build_summary_check_diagnostics(
    self,
    messages: list[ChatMessage],
    software_rows_by_group_period: dict[object, object],
    period_filter: str,
    summary_check_records: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    normalized_software_rows = self._normalize_software_rows_by_group_period(
        software_rows_by_group_period,
        period_filter,
    )
    generated_record_keys = {
        (str(record.get("group", "") or ""), str(record.get("period", "") or "").strip())
        for record in (summary_check_records or [])
        if isinstance(record, dict) and str(record.get("period", "") or "").strip()
    }
    diagnostics: list[dict[str, object]] = []
    latest_by_group_period: dict[tuple[str, str], ChatMessage] = {}
    for msg in messages:
        snapshot = self._extract_robot_summary_snapshot(msg)
        if snapshot is None or not self._is_robot_summary_stats_source(msg.content):
            continue
        key = (snapshot.group, snapshot.period)
        previous = latest_by_group_period.get(key)
        if previous is None or msg.ts >= previous.ts:
            latest_by_group_period[key] = msg
    for (group, period), msg in sorted(latest_by_group_period.items()):
        software_rows = normalized_software_rows.get((group, period)) or normalized_software_rows.get(("", period)) or []
        parsed_content, parsed_events = self._parse_bet_events_from_message(msg)
        diagnostics.append(
            {
                "group": group,
                "period": period,
                "group_id": str(getattr(msg, "group_id", "") or ""),
                "group_type": self._group_type_for_messages([msg], {}),
                "robot_sender_id": str(getattr(msg, "sender_id", "") or ""),
                "robot_summary_detected": True,
                "robot_summary_message_count": 1,
                "robot_summary_messages": [msg.content],
                "misclassified_as_user_bet": bool(parsed_events) and not self._looks_like_period_summary_billboard(parsed_content),
                "software_rows_found": bool(software_rows),
                "software_row_count": len(software_rows),
                "software_rows": [dict(row) for row in software_rows],
                "summary_check_record_generated": (group, period) in generated_record_keys,
                "summary_check_record": {},
                "failure_reason": "" if (group, period) in generated_record_keys else "识别到了机器人汇总，但没有同群同期软件侧 rows",
            }
        )
    return diagnostics
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -k "robot_summary_as_not_misclassified" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_source_recovery.py app/services/chat_service.py app/models/chat.py
git commit -m "feat: build robot summary diagnostics"
```

### Task 5: Add offline diagnosis entry point for real database verification

**Files:**
- Create: `tools/diagnose_robot_summary.py`
- Modify: `app/services/chat_service.py`
- Test: `tests/test_source_recovery.py`

- [ ] **Step 1: Write the failing test**

```python
def test_chat_service_can_build_offline_robot_summary_diagnostics_for_real_messages() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    messages = [
        ChatMessage(
            ts=datetime(2026, 6, 20, 12, 0, 0),
            group="A群",
            username="玩家A",
            sender_id="user-a",
            content="大单80",
            group_id="group-a",
        ),
        ChatMessage(
            ts=datetime(2026, 6, 20, 12, 0, 5),
            group="A群",
            username="机器人A",
            sender_id="robot-a",
            content="--------[3448004]期-------\n玩家A 1000【大单100 】",
            group_id="group-a",
        ),
    ]

    report = service.build_offline_robot_summary_diagnostics(
        messages,
        blocked_names=[],
        blocked_ids=[],
        period_filter="3448004",
        site="pc28",
        period_window_start=datetime(2026, 6, 20, 12, 0, 0),
        period_window_end=datetime(2026, 6, 20, 12, 1, 0),
        period_interval_sec=60,
        group_types_by_id={"group-a": "direct"},
    )

    assert len(report) == 1
    assert report[0]["group"] == "A群"
    assert report[0]["summary_check_record_generated"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -k "offline_robot_summary_diagnostics_for_real_messages" -v`
Expected: FAIL because `build_offline_robot_summary_diagnostics()` does not yet exist

- [ ] **Step 3: Write minimal implementation**

```python
def build_offline_robot_summary_diagnostics(
    self,
    messages: list[ChatMessage],
    blocked_names: list[str],
    blocked_ids: list[str] | None,
    period_filter: str,
    site: str,
    period_window_start: datetime | None,
    period_window_end: datetime | None,
    period_interval_sec: int,
    lock_threshold_sec: int = 0,
    group_types_by_id: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    _rows, stats = self.analyze_bets(
        messages,
        blocked_names,
        blocked_ids,
        period_filter,
        site,
        period_window_start,
        period_window_end,
        period_interval_sec,
        lock_threshold_sec,
        group_types_by_id,
    )
    return [dict(item) for item in getattr(stats, "summary_check_diagnostics", []) or [] if isinstance(item, dict)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -k "offline_robot_summary_diagnostics_for_real_messages" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_source_recovery.py app/services/chat_service.py tools/diagnose_robot_summary.py
git commit -m "feat: add offline robot summary diagnosis entry point"
```

### Task 6: Verify targeted behavior and broad regression safety

**Files:**
- Modify: `docs/bet-statistics-core-logic.md`
- Modify: `app/services/chat_service.py`
- Modify: `app/ui/main_window_data.py`
- Modify: `tests/test_source_recovery.py`

- [ ] **Step 1: Run targeted diagnostics and regression tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -k "robot_summary_diagnostics_for_group_period or missing_same_period_software_rows_in_diagnostics or sync_stats_rebuilds_summary_check_diagnostics_from_accumulated_rows or robot_summary_as_not_misclassified or offline_robot_summary_diagnostics_for_real_messages" -v`
Expected: PASS

- [ ] **Step 2: Run broader summary-check regression suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -k "summary_check or robot_summary or 本期下注列表 or personal_status_snapshot" -v`
Expected: PASS

- [ ] **Step 3: Run compile verification**

Run: `.\.venv\Scripts\python.exe -m compileall app tests tools`
Expected: exit code 0

- [ ] **Step 4: Update behavior doc**

```markdown
## 6.3 结构化机器人汇总诊断

系统现在会按 `群组 + 期号` 生成结构化诊断记录，至少包含：

- 是否识别到机器人汇总消息
- 是否错误走到了用户下注链路
- 是否拿到了同群同期的软件侧 rows
- 是否生成了 `summary_check_record`
- 如果没有生成，明确失败原因

这些诊断会随消息刷新及时更新，并与 `机器人汇总校验结果` 使用同一批底层数据。
```

- [ ] **Step 5: Commit**

```bash
git add docs/bet-statistics-core-logic.md app/services/chat_service.py app/ui/main_window_data.py tests/test_source_recovery.py tools/diagnose_robot_summary.py
git commit -m "feat: add robot summary diagnostics and timely refresh"
```
