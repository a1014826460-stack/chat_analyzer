# Local Draw Clock Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make draw periods advance locally at countdown zero, clear active-period statistics immediately, then calibrate from external APIs after a 10 second delay with bounded retry.

**Architecture:** Keep the existing `DrawInfo` data model and `MainWindowRealtimeMixin` flow, but enrich `DrawInfo` with local schedule metadata and move “period transition” authority to the local clock. `fetch_date.py` remains responsible for API parsing and API-vs-inferred source tagging; `main_window_realtime.py` owns local advancement, delayed calibration scheduling, stale-response rejection, retry, and UI clearing.

**Tech Stack:** Python 3.11, PySide6 timers/signals, dataclasses, pytest.

---

## File Structure

- Modify `app/models/chat.py`
  - Extend `DrawInfo` with schedule metadata while preserving existing constructor compatibility.
- Modify `app/utils/fetch_date.py`
  - Normalize parsed API payloads into complete schedule-aware `DrawInfo`.
  - Mark fallback/inferred data distinctly from API-confirmed data.
  - Fix fallback inference so elapsed intervals advance period numbers, not only times.
- Modify `app/ui/main_window_realtime.py`
  - Advance local schedule immediately when countdown expires.
  - Schedule API calibration for 10 seconds after local transition.
  - Retry failed/stale calibration up to 3 times with 5 second spacing.
  - Reject older API periods and avoid UI rollback.
- Modify `tests/test_source_recovery.py`
  - Add focused regression tests for local transition, delayed calibration, stale rejection, retry behavior, and parser schedule defaults.
- Modify `docs/chat_analysis_mechanisms.md`
  - Update the draw refresh section after behavior is implemented.

## Task 1: Extend DrawInfo With Schedule Metadata

**Files:**
- Modify: `app/models/chat.py`
- Test: `tests/test_source_recovery.py`

- [ ] **Step 1: Write the failing model compatibility test**

Add this test near existing draw/parser tests in `tests/test_source_recovery.py`:

```python
def test_draw_info_exposes_local_schedule_metadata_defaults() -> None:
    from app.models import DrawInfo

    info = DrawInfo(current_period="1001")

    assert info.current_period == "1001"
    assert info.start_time is None
    assert info.interval_sec == 0
    assert info.source == "api"
    assert info.last_api_success_at is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py::test_draw_info_exposes_local_schedule_metadata_defaults -q
```

Expected: FAIL with `AttributeError: 'DrawInfo' object has no attribute 'start_time'`.

- [ ] **Step 3: Add fields to DrawInfo**

In `app/models/chat.py`, change `DrawInfo` to:

```python
@dataclass
class DrawInfo:
    current_period: str
    current_time: datetime | None = None
    next_countdown: int = 0
    next_period: str = ""
    next_time: datetime | None = None
    auto_period: str = ""
    start_time: datetime | None = None
    interval_sec: int = 0
    source: str = "api"
    last_api_success_at: datetime | None = None
```

Keep the existing fields first so existing positional construction keeps working.

- [ ] **Step 4: Run the model test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py::test_draw_info_exposes_local_schedule_metadata_defaults -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app\models\chat.py tests\test_source_recovery.py
git commit -m "feat: add draw schedule metadata"
```

## Task 2: Normalize API DrawInfo Schedules

**Files:**
- Modify: `app/utils/fetch_date.py`
- Test: `tests/test_source_recovery.py`

- [ ] **Step 1: Write failing parser schedule tests**

Add these tests near `test_fetch_date_parses_original_site_payload_shapes`:

```python
def test_fetch_date_pc28_sets_schedule_metadata_from_absolute_next_time() -> None:
    from datetime import datetime

    from app.utils.fetch_date import extract_draw_info

    info = extract_draw_info(
        "pc28",
        {"issue": [{"qishu": "1001", "time": "2026-06-10 12:00:00", "next": 1781107410}]},
    )

    assert info.current_period == "1001"
    assert info.next_period == "1002"
    assert info.start_time == datetime(2026, 6, 10, 12, 0, 0)
    assert info.current_time == datetime(2026, 6, 10, 12, 0, 0)
    assert info.next_time == datetime.fromtimestamp(1781107410)
    assert info.interval_sec == 210
    assert info.source == "api"
    assert info.last_api_success_at is not None


def test_fetch_date_macao_without_next_time_derives_schedule_from_interval() -> None:
    from datetime import datetime, timedelta

    from app.utils.fetch_date import extract_draw_info

    info = extract_draw_info(
        "macao",
        {"data": {"drawList": [{"qihao": "2001", "opentime": "2026-06-10 12:03:00"}]}},
    )

    assert info.current_period == "2001"
    assert info.next_period == "2002"
    assert info.start_time == datetime(2026, 6, 10, 12, 3, 0)
    assert info.next_time == datetime(2026, 6, 10, 12, 6, 0)
    assert info.interval_sec == 180
    assert info.next_countdown >= 0


def test_fetch_date_australia_derives_next_time_from_countdown(monkeypatch) -> None:
    from datetime import datetime

    from app.utils import fetch_date

    class FixedDateTime(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 6, 10, 12, 0, 0)

    monkeypatch.setattr(fetch_date, "datetime", FixedDateTime)

    info = fetch_date.extract_draw_info(
        "australia",
        {"qi": "3001", "next": {"qi": "3002", "sec": 120}},
    )

    assert info.current_period == "3001"
    assert info.next_period == "3002"
    assert info.next_countdown == 120
    assert info.next_time == FixedDateTime(2026, 6, 10, 12, 2, 0)
    assert info.interval_sec == 180
```

- [ ] **Step 2: Run the parser schedule tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py -k "sets_schedule_metadata or derives_schedule_from_interval or derives_next_time_from_countdown" -q
```

Expected: FAIL because `DrawInfo.start_time`, `interval_sec`, or derived `next_time` values are missing.

- [ ] **Step 3: Add schedule normalization helper**

In `app/utils/fetch_date.py`, add this helper after `_parse_draw_info_payload`:

```python
def _normalize_draw_schedule(site: str, info: DrawInfo, *, source: str, now: datetime | None = None) -> DrawInfo:
    now = now or datetime.now()
    interval = _SITE_INTERVAL_SEC.get(site, 180)
    start_time = info.start_time or info.current_time
    next_time = info.next_time

    if next_time is None and info.next_countdown > 0:
        next_time = now + timedelta(seconds=int(info.next_countdown))
    if next_time is None and start_time is not None:
        next_time = start_time + timedelta(seconds=interval)
    if start_time is None and next_time is not None:
        start_time = next_time - timedelta(seconds=interval)

    if info.next_countdown <= 0 and next_time is not None:
        info.next_countdown = max(0, int((next_time - now).total_seconds()))
    if not info.next_period and info.current_period:
        info.next_period = _increment_period(info.current_period)
    if not info.auto_period:
        info.auto_period = info.current_period

    info.start_time = start_time
    info.current_time = info.current_time or start_time
    info.next_time = next_time
    info.interval_sec = interval
    info.source = source
    info.last_api_success_at = now if source == "api" and info.current_period else None
    return info
```

Then change `extract_draw_info()` so successful parsed values are normalized:

```python
info = _normalize_draw_schedule(site, _parse_draw_info_payload(site, payload), source="api")
```

Apply the same normalization in the retry-success branch before storing `_last_good_draw`.

- [ ] **Step 4: Update site parsers to provide raw timing only**

Keep existing parser behavior, but for Australia make `next_time` derivable from countdown by leaving it empty when no absolute time exists:

```python
return DrawInfo(
    current_period=current_period,
    current_time=_parse_ts(data.get("time") or data.get("current_time")),
    next_countdown=next_countdown,
    next_period=next_period,
    next_time=_parse_ts((nxt or {}).get("time") or data.get("next_time")),
    auto_period=current_period,
)
```

This may already match current code; the key is that `_normalize_draw_schedule()` fills missing schedule fields.

- [ ] **Step 5: Run parser schedule tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py -k "fetch_date_parses_original_site_payload_shapes or sets_schedule_metadata or derives_schedule_from_interval or derives_next_time_from_countdown" -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add app\utils\fetch_date.py tests\test_source_recovery.py
git commit -m "feat: normalize draw schedules from api data"
```

## Task 3: Fix Inferred Fallback To Advance Elapsed Periods

**Files:**
- Modify: `app/utils/fetch_date.py`
- Test: `tests/test_source_recovery.py`

- [ ] **Step 1: Write failing fallback advancement test**

Add this test near existing `_last_good_draw` fallback tests:

```python
def test_fetch_date_fallback_advances_period_for_elapsed_intervals(monkeypatch) -> None:
    from datetime import datetime, timedelta

    from app.models import DrawInfo
    from app.utils import fetch_date

    class FixedDateTime(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 6, 10, 12, 10, 0)

    monkeypatch.setattr(fetch_date, "datetime", FixedDateTime)
    fetch_date._last_good_draw.clear()
    fetch_date._last_good_draw["pc28"] = DrawInfo(
        current_period="1001",
        current_time=FixedDateTime(2026, 6, 10, 12, 0, 0),
        start_time=FixedDateTime(2026, 6, 10, 12, 0, 0),
        next_time=FixedDateTime(2026, 6, 10, 12, 3, 30),
        next_period="1002",
        interval_sec=210,
        source="api",
    )

    fallback = fetch_date.extract_draw_info("pc28", {"issue": []})

    assert fallback.current_period == "1003"
    assert fallback.next_period == "1004"
    assert fallback.start_time == FixedDateTime(2026, 6, 10, 12, 7, 0)
    assert fallback.next_time == FixedDateTime(2026, 6, 10, 12, 10, 30)
    assert fallback.source == "inferred"
```

- [ ] **Step 2: Run the fallback test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py::test_fetch_date_fallback_advances_period_for_elapsed_intervals -q
```

Expected: FAIL because fallback currently keeps `current_period="1001"`.

- [ ] **Step 3: Replace `_extrapolate_fallback()` period math**

In `app/utils/fetch_date.py`, replace `_extrapolate_fallback()` with:

```python
def _extrapolate_fallback(site: str) -> DrawInfo:
    previous = _last_good_draw.get(site)
    if previous is None or not previous.current_period:
        return DrawInfo(current_period="", source="inferred")

    interval = int(previous.interval_sec or _SITE_INTERVAL_SEC.get(site, 180))
    now = datetime.now()
    start_time = previous.start_time or previous.current_time or now
    next_time = previous.next_time or (start_time + timedelta(seconds=interval))
    periods_elapsed = 0

    while next_time <= now:
        start_time = next_time
        next_time = start_time + timedelta(seconds=interval)
        periods_elapsed += 1

    current_period = _increment_period(previous.current_period, periods_elapsed)
    fallback = DrawInfo(
        current_period=current_period,
        current_time=start_time,
        next_countdown=max(0, int((next_time - now).total_seconds())),
        next_period=_increment_period(current_period),
        next_time=next_time,
        auto_period=current_period,
        start_time=start_time,
        interval_sec=interval,
        source="inferred",
        last_api_success_at=previous.last_api_success_at,
    )
    return fallback
```

- [ ] **Step 4: Run fallback and parser tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py -k "fallback_advances_period or falls_back_to_last_good_pc28 or retries_transient_empty_pc28_payload" -q
```

Expected: PASS. If the old fallback test still expects the previous period, update that assertion to match the new accepted behavior only when elapsed time has crossed an interval; keep non-elapsed fallback behavior covered separately.

- [ ] **Step 5: Commit**

```powershell
git add app\utils\fetch_date.py tests\test_source_recovery.py
git commit -m "fix: advance inferred draw fallback periods"
```

## Task 4: Add Local Transition And Delayed Calibration State

**Files:**
- Modify: `app/ui/main_window_realtime.py`
- Test: `tests/test_source_recovery.py`

- [ ] **Step 1: Write failing local transition delay test**

Add this test near existing countdown tests:

```python
def test_main_window_countdown_zero_advances_locally_and_delays_calibration(monkeypatch) -> None:
    from datetime import datetime
    from types import SimpleNamespace

    from app.models import DrawInfo, StatsResult
    from app.ui import main_window_realtime
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    submitted: list[str] = []

    class DummyWorker:
        def submit(self, func, site):
            submitted.append(site)
            return SimpleNamespace(add_done_callback=lambda callback: None)

    class DummyInput:
        def __init__(self) -> None:
            self.value = "1002"

        def hasFocus(self) -> bool:
            return False

        def blockSignals(self, _value: bool) -> None:
            return None

        def setText(self, value: str) -> None:
            self.value = value

    calls: list[object] = []
    dummy = SimpleNamespace(
        _active_site="pc28",
        _draw_infos={
            "pc28": DrawInfo(
                current_period="1001",
                next_period="1002",
                current_time=datetime(2026, 6, 10, 12, 0, 0),
                start_time=datetime(2026, 6, 10, 12, 0, 0),
                next_time=datetime(2026, 6, 10, 12, 3, 30),
                next_countdown=0,
                interval_sec=210,
            )
        },
        _worker=DummyWorker(),
        _refreshing_sites=set(),
        _draw_retry_counts={},
        _draw_calibration_due_at={},
        current_messages=[object()],
        current_visual_rows=[{"period": "1002", "play": "大", "amount": 100.0}],
        current_stats=StatsResult(totals={"大": 100.0}),
        chart_window=SimpleNamespace(replace_rows=lambda rows: calls.append(("replace", list(rows)))),
        period_input=DummyInput(),
        _update_site_card_widgets=lambda site, info: calls.append(("card", site, info.current_period)),
        _refresh_active_site_info=lambda: None,
        _sync_chart_status=lambda: None,
        _load_filtered_messages=lambda: calls.append("load"),
        active_site_label=SimpleNamespace(setText=lambda value: None),
        active_period_label=SimpleNamespace(setText=lambda value: None),
        next_period_label=SimpleNamespace(setText=lambda value: None),
        countdown_label=SimpleNamespace(setText=lambda value: None),
    )
    _bind_realtime_countdown_helpers(dummy)
    dummy._current_period_override = lambda: MainWindowRealtimeMixin._current_period_override(dummy)
    dummy._sync_period_input_from_site = lambda info: MainWindowRealtimeMixin._sync_period_input_from_site(dummy, info)
    dummy._format_countdown = lambda value: MainWindowRealtimeMixin._format_countdown(dummy, value)

    MainWindowRealtimeMixin._advance_site_countdown(dummy, "pc28", dummy._draw_infos["pc28"], datetime(2026, 6, 10, 12, 3, 30))

    info = dummy._draw_infos["pc28"]
    assert info.current_period == "1002"
    assert info.next_period == "1003"
    assert info.start_time == datetime(2026, 6, 10, 12, 3, 30)
    assert info.next_time == datetime(2026, 6, 10, 12, 7, 0)
    assert info.next_countdown == 210
    assert info.source == "inferred"
    assert dummy.current_messages == []
    assert dummy.current_visual_rows == []
    assert dummy.current_stats == StatsResult(totals={}, totals_by_group={})
    assert ("replace", []) in calls
    assert dummy._draw_calibration_due_at["pc28"] == datetime(2026, 6, 10, 12, 3, 40)
    assert submitted == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py::test_main_window_countdown_zero_advances_locally_and_delays_calibration -q
```

Expected: FAIL because `_advance_site_countdown()` currently submits an API refresh immediately.

- [ ] **Step 3: Add local transition helpers**

In `app/ui/main_window_realtime.py`, add constants near the imports:

```python
CALIBRATION_DELAY_SEC = 10
CALIBRATION_RETRY_DELAY_SEC = 5
CALIBRATION_MAX_RETRIES = 3
```

Add helpers inside `MainWindowRealtimeMixin` before `_advance_site_countdown()`:

```python
    def _calibration_due_map(self) -> dict[str, datetime]:
        due = getattr(self, "_draw_calibration_due_at", None)
        if isinstance(due, dict):
            return due
        self._draw_calibration_due_at = {}
        return self._draw_calibration_due_at

    def _advance_site_locally(self, site: str, info: DrawInfo, now: datetime) -> DrawInfo:
        interval = int(getattr(info, "interval_sec", 0) or _SITE_INTERVAL_SEC.get(site, 180))
        start_time = info.next_time or now
        current_period = info.next_period or self._increment_period_text(info.current_period, 1)
        next_period = self._increment_period_text(current_period, 1)
        next_time = start_time + timedelta(seconds=interval)
        return DrawInfo(
            current_period=current_period,
            current_time=start_time,
            next_countdown=max(0, int((next_time - now).total_seconds())),
            next_period=next_period,
            next_time=next_time,
            auto_period=current_period,
            start_time=start_time,
            interval_sec=interval,
            source="inferred",
            last_api_success_at=getattr(info, "last_api_success_at", None),
        )

    def _schedule_draw_calibration(self, site: str, due_at: datetime) -> None:
        self._calibration_due_map()[site] = due_at
```

Also import `timedelta`:

```python
from datetime import datetime, timedelta
```

- [ ] **Step 4: Change `_advance_site_countdown()` to transition locally**

Replace the final `self._submit_site_draw_refresh(site, info)` branch with:

```python
        local_info = self._advance_site_locally(site, info, now)
        self._apply_single_draw_info((site, local_info, None))
        self._schedule_draw_calibration(site, now + timedelta(seconds=CALIBRATION_DELAY_SEC))
```

- [ ] **Step 5: Run the local transition test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py::test_main_window_countdown_zero_advances_locally_and_delays_calibration -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add app\ui\main_window_realtime.py tests\test_source_recovery.py
git commit -m "feat: advance draw locally at countdown zero"
```

## Task 5: Submit Delayed Calibration Requests

**Files:**
- Modify: `app/ui/main_window_realtime.py`
- Test: `tests/test_source_recovery.py`

- [ ] **Step 1: Write failing delayed submission test**

Add this test near the local transition test:

```python
def test_main_window_submits_calibration_only_after_due_time(monkeypatch) -> None:
    from datetime import datetime
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui import main_window_realtime
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    submitted: list[str] = []

    class DummyWorker:
        def submit(self, func, site):
            submitted.append(site)
            return SimpleNamespace(add_done_callback=lambda callback: None)

    dummy = SimpleNamespace(
        _active_site="pc28",
        _draw_infos={"pc28": DrawInfo(current_period="1002", next_period="1003", next_countdown=200)},
        _draw_calibration_due_at={"pc28": datetime(2026, 6, 10, 12, 3, 40)},
        _refreshing_sites=set(),
        _worker=DummyWorker(),
    )
    _bind_realtime_countdown_helpers(dummy)

    MainWindowRealtimeMixin._submit_due_draw_calibrations(dummy, datetime(2026, 6, 10, 12, 3, 39))
    assert submitted == []
    assert dummy._draw_calibration_due_at == {"pc28": datetime(2026, 6, 10, 12, 3, 40)}

    MainWindowRealtimeMixin._submit_due_draw_calibrations(dummy, datetime(2026, 6, 10, 12, 3, 40))
    assert submitted == ["pc28"]
    assert dummy._refreshing_sites == {"pc28"}
    assert dummy._draw_calibration_due_at == {}
```

- [ ] **Step 2: Run delayed submission test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py::test_main_window_submits_calibration_only_after_due_time -q
```

Expected: FAIL because `_submit_due_draw_calibrations()` does not exist.

- [ ] **Step 3: Add delayed calibration submitter**

In `MainWindowRealtimeMixin`, add:

```python
    def _submit_due_draw_calibrations(self, now: datetime) -> None:
        due_map = self._calibration_due_map()
        for site, due_at in list(due_map.items()):
            if due_at > now:
                continue
            due_map.pop(site, None)
            self._submit_site_draw_refresh(site, self._draw_infos.get(site, DrawInfo(current_period="")))
```

Then update `_on_countdown_tick()` after the site loop:

```python
        self._submit_due_draw_calibrations(now)
```

- [ ] **Step 4: Ensure `_submit_site_draw_refresh()` no longer creates local fallback**

Change `_submit_site_draw_refresh()` so it only submits API calibration and no longer computes local transition fallback at submit time:

```python
    def _submit_site_draw_refresh(self, site: str, info: DrawInfo) -> None:
        refreshing_sites = self._refreshing_site_set()
        if site in refreshing_sites:
            return
        refreshing_sites.add(site)
        worker = getattr(self, "_worker", None)
        if worker is None:
            self._schedule_draw_calibration(site, datetime.now() + timedelta(seconds=CALIBRATION_RETRY_DELAY_SEC))
            refreshing_sites.discard(site)
            return
        try:
            future = worker.submit(extract_draw_info, site)
        except Exception:
            logger.warning("[%s] 提交线路刷新失败，稍后重试", site_label(site), exc_info=True)
            refreshing_sites.discard(site)
            self._schedule_draw_calibration(site, datetime.now() + timedelta(seconds=CALIBRATION_RETRY_DELAY_SEC))
            return
        future.add_done_callback(lambda finished, value=site: self._handle_single_draw_info_loaded(value, None, finished))
```

Keep the `fallback` argument on `_handle_single_draw_info_loaded()` for compatibility with existing tests, but allow it to be `None`.

- [ ] **Step 5: Run delayed submission and existing countdown tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py -k "delays_calibration or submits_calibration_only_after_due_time or countdown_tick_updates_all_sites" -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add app\ui\main_window_realtime.py tests\test_source_recovery.py
git commit -m "feat: delay draw api calibration"
```

## Task 6: Reject Stale API Responses And Retry Three Times

**Files:**
- Modify: `app/ui/main_window_realtime.py`
- Test: `tests/test_source_recovery.py`

- [ ] **Step 1: Write failing stale-response retry test**

Add this test near calibration tests:

```python
def test_main_window_stale_calibration_response_retries_without_rollback() -> None:
    from datetime import datetime
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    dummy = SimpleNamespace(
        _active_site="pc28",
        _draw_infos={
            "pc28": DrawInfo(
                current_period="1002",
                next_period="1003",
                next_countdown=200,
                source="inferred",
            )
        },
        _refreshing_sites={"pc28"},
        _draw_retry_counts={},
        _draw_calibration_due_at={},
        _update_site_card_widgets=lambda site, info: None,
        _refresh_active_site_info=lambda: None,
        _sync_chart_status=lambda: None,
    )
    _bind_realtime_countdown_helpers(dummy)

    stale_future = SimpleNamespace(
        result=lambda: DrawInfo(current_period="1001", next_period="1002", next_countdown=5, source="api")
    )

    MainWindowRealtimeMixin._handle_single_draw_info_loaded(dummy, "pc28", None, stale_future)

    assert dummy._draw_infos["pc28"].current_period == "1002"
    assert dummy._draw_retry_counts == {"pc28": 1}
    assert dummy._draw_calibration_due_at["pc28"] > datetime.now()
    assert dummy._refreshing_sites == set()
```

- [ ] **Step 2: Write failing max-retry keep-inferred test**

Add:

```python
def test_main_window_stale_calibration_after_three_retries_keeps_inferred_issue() -> None:
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    dummy = SimpleNamespace(
        _active_site="pc28",
        _draw_infos={"pc28": DrawInfo(current_period="1002", next_period="1003", next_countdown=200, source="inferred")},
        _refreshing_sites={"pc28"},
        _draw_retry_counts={"pc28": 3},
        _draw_calibration_due_at={},
        _update_site_card_widgets=lambda site, info: None,
        _refresh_active_site_info=lambda: None,
        _sync_chart_status=lambda: None,
    )
    _bind_realtime_countdown_helpers(dummy)

    stale_future = SimpleNamespace(result=lambda: DrawInfo(current_period="1001", next_period="1002", source="api"))

    MainWindowRealtimeMixin._handle_single_draw_info_loaded(dummy, "pc28", None, stale_future)

    assert dummy._draw_infos["pc28"].current_period == "1002"
    assert dummy._draw_retry_counts == {}
    assert dummy._draw_calibration_due_at == {}
    assert dummy._refreshing_sites == set()
```

- [ ] **Step 3: Run stale tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py -k "stale_calibration" -q
```

Expected: FAIL because stale API data is not rejected.

- [ ] **Step 4: Add period comparison and retry helpers**

In `MainWindowRealtimeMixin`, add:

```python
    def _compare_period_text(self, left: str, right: str) -> int:
        left_text = str(left or "").strip()
        right_text = str(right or "").strip()
        if left_text.isdigit() and right_text.isdigit():
            left_int = int(left_text)
            right_int = int(right_text)
            return (left_int > right_int) - (left_int < right_int)
        return (left_text > right_text) - (left_text < right_text)

    def _is_stale_draw_info(self, site: str, info: DrawInfo) -> bool:
        current = self._draw_infos.get(site)
        if current is None or not current.current_period or not info.current_period:
            return False
        return self._compare_period_text(info.current_period, current.current_period) < 0

    def _schedule_calibration_retry(self, site: str) -> bool:
        retry_count = self._draw_retry_count(site) + 1
        if retry_count > CALIBRATION_MAX_RETRIES:
            self._clear_draw_retry_count(site)
            return False
        self._set_draw_retry_count(site, retry_count)
        self._schedule_draw_calibration(site, datetime.now() + timedelta(seconds=CALIBRATION_RETRY_DELAY_SEC))
        return True
```

- [ ] **Step 5: Update `_handle_single_draw_info_loaded()`**

Replace the method body with:

```python
    def _handle_single_draw_info_loaded(self, site: str, fallback: DrawInfo | None, future) -> None:
        error = None
        try:
            info = future.result()
        except Exception as exc:
            error = exc
            info = None

        self._refreshing_site_set().discard(site)

        if info is None or getattr(info, "source", "api") != "api" or self._is_stale_draw_info(site, info):
            if self._schedule_calibration_retry(site):
                logger.warning("[%s] 线路校准失败或返回旧期，稍后重试: %s", site_label(site), error or info)
            else:
                logger.warning("[%s] 线路校准重试3次仍失败，保留本地推导期号: %s", site_label(site), error or info)
            return

        self._clear_draw_retry_count(site)
        self._apply_single_draw_info((site, info, None))
```

- [ ] **Step 6: Run stale tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py -k "stale_calibration" -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add app\ui\main_window_realtime.py tests\test_source_recovery.py
git commit -m "fix: reject stale draw calibration responses"
```

## Task 7: Calibrate Same Or Newer API Responses

**Files:**
- Modify: `app/ui/main_window_realtime.py`
- Test: `tests/test_source_recovery.py`

- [ ] **Step 1: Write failing same-period calibration test**

Add:

```python
def test_main_window_same_period_calibration_updates_timing_without_clearing_again() -> None:
    from datetime import datetime
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    calls: list[object] = []
    dummy = SimpleNamespace(
        _active_site="pc28",
        _draw_infos={"pc28": DrawInfo(current_period="1002", next_period="1003", next_countdown=180, source="inferred")},
        _refreshing_sites={"pc28"},
        _draw_retry_counts={"pc28": 1},
        _query_period_overrides_by_site={},
        _update_site_card_widgets=lambda site, info: calls.append(("card", info.next_countdown)),
        _refresh_active_site_info=lambda: calls.append("refresh"),
        _sync_chart_status=lambda: None,
    )
    _bind_realtime_countdown_helpers(dummy)

    future = SimpleNamespace(
        result=lambda: DrawInfo(
            current_period="1002",
            next_period="1003",
            next_countdown=150,
            next_time=datetime(2026, 6, 10, 12, 7, 0),
            source="api",
        )
    )

    MainWindowRealtimeMixin._handle_single_draw_info_loaded(dummy, "pc28", None, future)

    assert dummy._draw_infos["pc28"].current_period == "1002"
    assert dummy._draw_infos["pc28"].next_countdown == 150
    assert dummy._draw_infos["pc28"].source == "api"
    assert dummy._draw_retry_counts == {}
    assert "refresh" in calls
```

- [ ] **Step 2: Write failing newer-period calibration test**

Add:

```python
def test_main_window_newer_period_calibration_adopts_api_issue() -> None:
    from types import SimpleNamespace

    from app.models import DrawInfo, StatsResult
    from app.ui.main_window_realtime import MainWindowRealtimeMixin

    calls: list[object] = []
    dummy = SimpleNamespace(
        _active_site="pc28",
        _draw_infos={"pc28": DrawInfo(current_period="1002", next_period="1003", next_countdown=1, source="inferred")},
        _last_message_cursor={"pc28": (1, 2)},
        _refreshing_sites={"pc28"},
        _draw_retry_counts={},
        _query_period_overrides_by_site={},
        current_messages=[object()],
        current_visual_rows=[{"period": "1003", "play": "大", "amount": 50.0}],
        current_stats=StatsResult(totals={"大": 50.0}),
        chart_window=SimpleNamespace(replace_rows=lambda rows: calls.append(("replace", list(rows)))),
        period_input=SimpleNamespace(hasFocus=lambda: False, blockSignals=lambda value: None, setText=lambda value: calls.append(("period", value))),
        _update_site_card_widgets=lambda site, info: calls.append(("card", info.current_period)),
        _refresh_active_site_info=lambda: MainWindowRealtimeMixin._refresh_active_site_info(dummy),
        _sync_chart_status=lambda: calls.append("status"),
        _load_filtered_messages=lambda: calls.append("load"),
        active_site_label=SimpleNamespace(setText=lambda value: None),
        active_period_label=SimpleNamespace(setText=lambda value: None),
        next_period_label=SimpleNamespace(setText=lambda value: None),
        countdown_label=SimpleNamespace(setText=lambda value: None),
    )
    _bind_realtime_countdown_helpers(dummy)
    dummy._current_period_override = lambda: MainWindowRealtimeMixin._current_period_override(dummy)
    dummy._sync_period_input_from_site = lambda info: MainWindowRealtimeMixin._sync_period_input_from_site(dummy, info)
    dummy._format_countdown = lambda value: MainWindowRealtimeMixin._format_countdown(dummy, value)

    future = SimpleNamespace(result=lambda: DrawInfo(current_period="1003", next_period="1004", next_countdown=200, source="api"))

    MainWindowRealtimeMixin._handle_single_draw_info_loaded(dummy, "pc28", None, future)

    assert dummy._draw_infos["pc28"].current_period == "1003"
    assert dummy.current_messages == []
    assert dummy.current_visual_rows == []
    assert ("replace", []) in calls
    assert "load" in calls
```

- [ ] **Step 3: Run calibration adoption tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py -k "same_period_calibration or newer_period_calibration" -q
```

Expected: PASS if Task 6 apply logic is correct. If same-period response incorrectly clears active rows, fix `_apply_single_draw_info()` by keeping its existing period-change guard and only clearing when `active_period_changed or active_query_period_changed`.

- [ ] **Step 4: Commit**

```powershell
git add app\ui\main_window_realtime.py tests\test_source_recovery.py
git commit -m "feat: calibrate local draw clock from api"
```

## Task 8: Update Docs And Run Full Verification

**Files:**
- Modify: `docs/chat_analysis_mechanisms.md`
- Test: full suite

- [ ] **Step 1: Update draw refresh documentation**

In `docs/chat_analysis_mechanisms.md`, replace the failure-handling bullets in section `1. 站点数据获取` with:

```markdown
失败处理分三层：

- 倒计时归零：本地先按线路周期推进到下一期，立即清空右侧当期统计、图表层和实时下注文本。
- 延迟校准：本地换期 10 秒后再请求外部接口，避免站点正在开奖时返回旧期或空数据。
- 有界重试：接口失败、解析失败或返回旧期号时，每 5 秒重试一次，最多 3 次；仍失败则保留本地推导期号，后续周期继续校准。

API 恢复后，如果返回当前或更新期号，系统会用接口数据校准倒计时和期号；如果返回旧期号，系统不会回滚 UI。
```

- [ ] **Step 2: Run targeted behavior tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py -k "draw_info_exposes or fetch_date_ or countdown_zero_advances_locally or calibration or stale_calibration" -q
```

Expected: all selected tests PASS.

- [ ] **Step 3: Run the full suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py -q
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```powershell
git add docs\chat_analysis_mechanisms.md tests\test_source_recovery.py app\models\chat.py app\utils\fetch_date.py app\ui\main_window_realtime.py
git commit -m "docs: explain local draw clock calibration"
```

## Self-Review

- Spec coverage:
  - Site intervals are covered by Task 2 parser tests and schedule metadata.
  - Immediate local transition and stats clearing are covered by Task 4.
  - 10 second delayed calibration is covered by Task 5.
  - Failed/stale retry and 3 retry cap are covered by Task 6.
  - Same/newer API calibration and no rollback are covered by Tasks 6 and 7.
  - Drift control is covered by API recalibration and stale-response rejection.
- Placeholder scan: no TBD/TODO placeholders; all tasks include concrete tests, code snippets, commands, and expected results.
- Type consistency: all new fields are on `DrawInfo`; all timing helpers use `datetime`; retry/due state lives on `MainWindowRealtimeMixin` instance dictionaries.
