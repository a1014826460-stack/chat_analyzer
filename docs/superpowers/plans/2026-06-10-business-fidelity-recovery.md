# Business Fidelity Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the StarTrace recovery build so that bet parsing, statistics, period linkage, message loading, and core filtering behave close to the original executable.

**Architecture:** Rebuild the critical business path from executable evidence outward. Start with failing parser/statistics tests for `ChatLogService`, implement only the minimal code needed to satisfy the recovered behavior, then restore `MainWindowDataMixin` around that stabilized service. Keep the UI contract stable while replacing simplified fallback logic with evidence-backed logic.

**Tech Stack:** Python 3.11, PySide6, pytest, decompiled/disassembly artifacts under `.codex_recovery/recovered_src`, `apply_patch`

---

### Task 1: Lock Down Statistics-Sensitive Parser Behavior

**Files:**
- Modify: `tests/test_source_recovery.py`
- Reference: `.codex_recovery/recovered_src/disassembly/app/services/chat_service.dis.txt`
- Reference: `app/models/chat.py`

- [ ] **Step 1: Write the failing tests**

Add these tests near the existing `ChatLogService` coverage:

```python
def test_chat_service_parses_compact_amount_first_and_play_first_tokens() -> None:
    from app.services.chat_service import ChatLogService

    service = ChatLogService()

    assert service._parse_compact_bets("100澶?  灏?20  30鍗?", "Alice") == [
        ("Alice", "澶?, 100.0),
        ("Alice", "灏?, 20.0),
        ("Alice", "鍗?, 30.0),
    ]


def test_chat_service_extracts_direct_group_start_and_end_markers() -> None:
    from datetime import datetime

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    service._is_group_member_robot = lambda group, sender_id, username: True
    service._decode_possible_frontend_ciphertext = lambda content: content
    service._extract_period = lambda content: "123456"

    start_msg = ChatMessage(
        ts=datetime(2026, 6, 10, 12, 0, 0),
        group="GroupA",
        username="Robot",
        sender_id="robot-1",
        content="涓嬫敞鏈熸暟 123456",
    )
    end_msg = ChatMessage(
        ts=datetime(2026, 6, 10, 12, 1, 0),
        group="GroupA",
        username="Robot",
        sender_id="robot-1",
        content="濡備笅璁㈠崟宸插彇娑? 123456",
    )

    assert service._extract_direct_group_marker(start_msg) == ("start", "123456")
    assert service._extract_direct_group_marker(end_msg) == ("end", "123456")


def test_chat_service_receipt_owner_prefers_recent_same_period_pending_record() -> None:
    from collections import defaultdict
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    from app.models import ChatMessage
    from app.services.chat_service import ChatLogService

    service = ChatLogService()
    now = datetime(2026, 6, 10, 12, 0, 30)
    event = SimpleNamespace(bettor="Alice")
    msg = ChatMessage(
        ts=now,
        group="GroupA",
        username="Robot",
        sender_id="robot-1",
        content="receipt",
    )
    pending_hit = SimpleNamespace(
        username="AliceUser",
        sender_id="alice-1",
        period="8888",
        ts=now - timedelta(seconds=10),
    )
    pending_miss = SimpleNamespace(
        username="OldUser",
        sender_id="old-1",
        period="7777",
        ts=now - timedelta(seconds=10),
    )

    owner = service._resolve_receipt_owner(
        event,
        msg,
        "8888",
        defaultdict(list, {"alice": [pending_miss, pending_hit]}),
        defaultdict(list),
    )

    assert owner == ("AliceUser", "alice-1")
```

- [ ] **Step 2: Run the targeted tests to verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py -k "compact_amount_first or direct_group_start or receipt_owner" -q
```

Expected:

```text
FAIL
```

At least one failure should be because the current simplified `chat_service.py` does not define or satisfy `_parse_compact_bets`, `_extract_direct_group_marker`, or `_resolve_receipt_owner` behavior.

- [ ] **Step 3: Keep the new tests as the parser regression gate**

Do not relax these assertions during implementation. If the executable evidence later shows different totals or period linkage, add a new failing test before changing production code.

### Task 2: Rebuild `ChatLogService` Parser and Period-Linkage Core

**Files:**
- Modify: `app/services/chat_service.py`
- Modify: `app/models/chat.py`
- Test: `tests/test_source_recovery.py`
- Reference: `.codex_recovery/recovered_src/disassembly/app/services/chat_service.dis.txt`

- [ ] **Step 1: Add the minimal internal structures required by the recovered service**

Implement lightweight dataclasses and constants directly in `app/services/chat_service.py`:

```python
@dataclass
class PendingUserMessage:
    username: str
    sender_id: str
    bettor: str
    period: str
    ts: datetime


@dataclass
class DirectPeriodContext:
    period: str
    start: datetime
    end: datetime
```

Also define evidence-backed timing constants:

```python
RECEIPT_MATCH_WINDOW = timedelta(minutes=2)
DIRECT_GROUP_PERIOD_WINDOW = timedelta(minutes=20)
```

- [ ] **Step 2: Implement compact-bet parsing before changing the summary pipeline**

Add helper methods shaped by the disassembly:

```python
def _parse_compact_bets(self, content: str, bettor: str) -> list[tuple[str, str, float]]:
    text = self._clean_text(content)
    matches: list[tuple[int, str, float]] = []
    i = 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        if text[i].isdigit():
            number_match = NUMBER_TOKEN_AT_PATTERN.match(text, i)
            if number_match:
                number_text = number_match.group(0)
                next_pos = number_match.end()
                play = self._match_play_token(text, next_pos)
                if play is not None:
                    matches.append((i, play, self._parse_amount_text(number_text)))
                    i = next_pos + len(play)
                    continue
        play = self._match_play_token(text, i)
        if play is not None:
            amount_match = NUMBER_TOKEN_AT_PATTERN.match(text, i + len(play))
            if amount_match:
                amount_text = amount_match.group(0)
                matches.append((i, play, self._parse_amount_text(amount_text)))
                i = amount_match.end()
                continue
        i += 1
    matches.sort(key=lambda item: item[0])
    return [(bettor, play, amount) for _pos, play, amount in matches]


def _match_play_token(self, text: str, start: int) -> str | None:
    for token in PLAY_TOKENS:
        if text.startswith(token, start):
            return token
    return None
```

Use the existing mojibake play tokens already present in the recovered tree unless better source evidence is found.

- [ ] **Step 3: Implement direct-group marker extraction and receipt ownership**

Add the robot/period helper path required by the disassembly:

```python
def _extract_direct_group_marker(self, msg: ChatMessage) -> tuple[str, str] | None:
    if not msg.sender_id:
        return None
    if not self._is_group_member_robot(msg.group, msg.sender_id, msg.username):
        return None
    content = self._decode_possible_frontend_ciphertext(self._clean_text(msg.content))
    period = self._extract_period(content)
    if not period:
        return None
    if DIRECT_CLOSE_HINT_PATTERN.search(content):
        return ("end", period)
    if "涓嬫敞鏈熸暟" in content or "鏈湡涓嬫敞" in content:
        return ("start", period)
    return None


def _resolve_receipt_owner(
    self,
    event,
    msg: ChatMessage,
    period: str,
    pending_by_bettor: dict[str, list[PendingUserMessage]],
    pending_by_user: dict[str, list[PendingUserMessage]],
) -> tuple[str, str]:
    bettor_key = self._normalize_text(event.bettor)
    candidates = list(pending_by_bettor.get(bettor_key, []))
    if not candidates and bettor_key:
        candidates = list(pending_by_user.get(bettor_key, []))
    candidates = [
        pending
        for pending in candidates
        if (
            (not period or not pending.period or pending.period == period)
            and msg.ts >= pending.ts
            and msg.ts - pending.ts <= RECEIPT_MATCH_WINDOW
        )
    ]
    if candidates:
        chosen = candidates[-1]
        return chosen.username, chosen.sender_id
    return msg.username, msg.sender_id
```

Filter candidates to the same period when available and to the configured receipt window before selecting the newest match.

- [ ] **Step 4: Wire the restored helpers into the public analysis path**

Replace the current simplified `analyze_bets` / `extract_bet_visual_data` flow with logic that:

```python
def extract_bet_visual_data(
    self,
    messages: list[ChatMessage],
    blocked_names: list[str],
    blocked_ids: list[str] | None,
    period_filter: str,
    site: str,
    period_window_start: datetime | None,
    period_window_end: datetime | None,
    period_interval_sec: int,
) -> list[dict[str, object]]:
    filtered_messages = self.filter_blocked_messages(messages, blocked_names, blocked_ids)
    ranges = self._build_direct_group_period_ranges(filtered_messages, None)
    rows = []
    pending_by_bettor = defaultdict(list)
    pending_by_user = defaultdict(list)
    for msg in filtered_messages:
        for bettor, play, amount in self._parse_bets(msg.content):
            period = self._resolve_message_period(msg, period_filter, ranges)
            row_id = f"{msg.raw_client_time}-{msg.raw_rand}-{len(rows)}"
            rows.append(
                {
                    "time": msg.ts,
                    "group": msg.group,
                    "username": msg.username,
                    "bettor": bettor,
                    "play": play,
                    "amount": amount,
                    "kind": "bet",
                    "period": period,
                    "row_id": row_id,
                }
            )
            pending = PendingUserMessage(
                username=msg.username,
                sender_id=msg.sender_id,
                bettor=bettor,
                period=period,
                ts=msg.ts,
            )
            pending_by_bettor[self._normalize_text(bettor)].append(pending)
            pending_by_user[self._normalize_text(msg.username)].append(pending)
    return rows
```

Keep the row schema compatible with the current UI: `time`, `group`, `username`, `bettor`, `play`, `amount`, `kind`, `period`, `row_id`.

- [ ] **Step 5: Run the parser tests to verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py -k "compact_amount_first or direct_group_start or receipt_owner" -q
```

Expected:

```text
3 passed
```

- [ ] **Step 6: Run the broader recovery suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py -q
```

Expected:

```text
PASS
```

### Task 3: Lock Down `MainWindowDataMixin` Behavior That Affects Loading and Filtering

**Files:**
- Modify: `tests/test_source_recovery.py`
- Reference: `.codex_recovery/recovered_src/disassembly/app/ui/main_window_data.dis.txt`
- Reference: `app/ui/main_window.py`

- [ ] **Step 1: Write failing tests for load-option construction and initial-state behavior**

Add these tests:

```python
def test_main_window_data_gather_parse_options_includes_group_and_period_context() -> None:
    from app.ui.main_window_data import MainWindowDataMixin

    class DummyItem:
        def __init__(self, checked, group_id, group_name):
            self._checked = checked
            self._group_id = group_id
            self._group_name = group_name

        def checkState(self):
            return 2 if self._checked else 0

        def data(self, role):
            return {32: self._group_id, 33: self._group_name}.get(role)

        def text(self):
            return self._group_name

    class DummyList:
        def __init__(self):
            self.items = [DummyItem(True, "g1", "GroupA"), DummyItem(False, "g2", "GroupB")]

        def count(self):
            return len(self.items)

        def item(self, index):
            return self.items[index]

    class DummyCombo:
        def currentText(self):
            return "Alice"

    class DummyText:
        def text(self):
            return "9001"

    class DummyWindow(MainWindowDataMixin):
        def _blocked_names(self):
            return ["Blocked"]

    dummy = DummyWindow()
    dummy.group_list = DummyList()
    dummy.username_combo = DummyCombo()
    dummy.period_input = DummyText()
    dummy.group_block_rules = {"groupa": {"names": ["Blocked"]}}
    dummy._active_site = "pc28"

    options = dummy._gather_parse_options()

    assert options.username == "Alice"
    assert options.groups == ["GroupA"]
    assert options.group_ids == ["g1"]
    assert options.blocked_names == ["Blocked"]
    assert options.period_filter == "9001"
    assert options.site == "pc28"
    assert options.period_interval_sec > 0


def test_main_window_data_load_initial_state_restores_period_and_activation_gate() -> None:
    from app.ui.main_window_data import MainWindowDataMixin

    class DummyCombo:
        def __init__(self):
            self.items = []
            self.current = ""

        def clear(self):
            self.items = []

        def addItems(self, values):
            self.items.extend(values)

        def setCurrentText(self, value):
            self.current = value

    class DummyEdit:
        def __init__(self):
            self.value = ""

        def setText(self, value):
            self.value = value

    class DummyDateTimeEdit:
        def __init__(self):
            self.value = None

        def setDateTime(self, value):
            self.value = value

    class DummyTabs:
        def __init__(self):
            self.current = None

        def setCurrentWidget(self, widget):
            self.current = widget

    class DummyLicenseService:
        def is_activated(self):
            return False

    class DummyWindow(MainWindowDataMixin):
        def _refresh_block_rule_summary(self):
            self.block_summary_called = True

        def _refresh_block_rule_group_selector(self):
            self.block_group_called = True

        def _resolve_database(self, silent=False):
            self.resolve_called = silent

    dummy = DummyWindow()
    dummy.analysis_page = object()
    dummy.settings = {
        "recent_usernames": ["Alice", "Bob"],
        "username": "Alice",
        "fallback_db_path": "D:/db.sqlite",
    }
    dummy.username_combo = DummyCombo()
    dummy.manual_db_edit = DummyEdit()
    dummy.period_input = DummyEdit()
    dummy.start_edit = DummyDateTimeEdit()
    dummy.end_edit = DummyDateTimeEdit()
    dummy.tabs = DummyTabs()
    dummy.license_page = object()
    dummy._manual_period_override = True
    dummy._query_period_override = "7788"
    dummy._require_activation = True
    dummy.license_service = DummyLicenseService()

    dummy._load_initial_state()

    assert dummy.username_combo.items == ["Alice", "Bob"]
    assert dummy.username_combo.current == "Alice"
    assert dummy.manual_db_edit.value == "D:/db.sqlite"
    assert dummy.period_input.value == "7788"
    assert dummy.tabs.current is dummy.license_page
```

- [ ] **Step 2: Run the targeted UI-data tests to verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py -k "gather_parse_options_includes_group_and_period_context or load_initial_state_restores_period_and_activation_gate" -q
```

Expected:

```text
FAIL
```

At least one failure should show that `main_window_data.py` is still missing original-state restoration behavior.

### Task 4: Restore `MainWindowDataMixin` Around the Recovered Service

**Files:**
- Modify: `app/ui/main_window_data.py`
- Test: `tests/test_source_recovery.py`
- Reference: `.codex_recovery/recovered_src/disassembly/app/ui/main_window_data.dis.txt`
- Reference: `app/ui/main_window.py`

- [ ] **Step 1: Rebuild `_load_initial_state` to match recovered behavior**

Bring back the recovered fields visible in the disassembly:

```python
def _load_initial_state(self) -> None:
    if self.analysis_page is None:
        return
    recent_usernames = self.settings.get("recent_usernames", [])
    self.username_combo.clear()
    self.username_combo.addItems(recent_usernames)
    current_username = str(self.settings.get("username", "")).strip()
    if current_username:
        self.username_combo.setCurrentText(current_username)
    self.manual_db_edit.setText(self.settings.get("fallback_db_path", ""))
    self.period_input.setText(self._query_period_override if self._manual_period_override else "")
    now = QDateTime.currentDateTime()
    self.end_edit.setDateTime(now)
    self.start_edit.setDateTime(now.addDays(-1))
    self._refresh_block_rule_summary()
    if self._require_activation and not self.license_service.is_activated():
        self.tabs.setCurrentWidget(self.license_page)
        return
    if current_username:
        self._resolve_database(silent=True)
        return
    self._refresh_block_rule_group_selector()
```

Also restore the activation gate path that switches to `license_page` when `_require_activation` is true and `license_service.is_activated()` is false.

- [ ] **Step 2: Rebuild `_resolve_database` and `_load_groups_from_current_source` conservatively**

Restore the behavior the current UI depends on:

```python
def _resolve_database(self, silent: bool = False) -> None:
    username = self.username_combo.currentText().strip()
    if not username:
        if not silent:
            QMessageBox.information(self, "Missing username", "Please enter a username first.")
        return
    resolved = self.account_resolver.resolve(username)
    if resolved is None:
        self.resolved_db = None
        self.resolved_path_edit.clear()
        self.group_list.clear()
        self._refresh_block_rule_group_selector()
        self.fallback_box.setVisible(True)
        diagnostic = self.account_resolver.get_diagnostic()
        self.db_status_label.setText(diagnostic.format_message() if diagnostic else "Database not found.")
        self.status_label.setText("Automatic database resolution failed.")
        return
    self.resolved_db = resolved
    self.resolved_path_edit.setText(str(resolved.msg_db))
    self.db_status_label.setText(f"Resolved {resolved.account_name} -> {resolved.msg_db}")
    self.status_label.setText("Database resolved. Ready to load messages.")
    self.fallback_box.setVisible(False)
    self._remember_username(username)
    self._load_groups_from_current_source()
    self._save_settings()
```

Preserve the non-blocking current UI contract and keep group list item roles `32` and `33`.

- [ ] **Step 3: Rebuild load-option construction and result application**

Update `_build_load_options`, `_run_load_pipeline`, `_apply_load_result`, and `_handle_load_result_ready` so they preserve the recovered behavior:

```python
def _build_load_options(self, incremental: bool) -> tuple[Path, ParseOptions, tuple, bool]:
    source = self._current_source_path()
    if source is None:
        raise FileNotFoundError("No data source selected")
    options = self._gather_parse_options()
    if getattr(self, "advanced_time_check", None) and self.advanced_time_check.isChecked():
        options.start_time = self.start_edit.dateTime().toPython()
        options.end_time = self.end_edit.dateTime().toPython()
    if incremental:
        cursor = self._last_message_cursor.get(self._active_site or "")
        if cursor:
            options.incremental_cursor_value = int(cursor[0])
            options.incremental_cursor_rand = int(cursor[1])
    return source, options, self._compute_load_signature(incremental), incremental
```

Apply result payloads only when the sequence matches the newest request.

- [ ] **Step 4: Run the UI-data tests to verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py -k "gather_parse_options_includes_group_and_period_context or load_initial_state_restores_period_and_activation_gate or load_filtered_messages_uses_background_worker" -q
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Run the full recovery suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_recovery.py -q
```

Expected:

```text
PASS
```

### Task 5: Verify, Record Remaining Gaps, and Prepare the Next Recovery Slice

**Files:**
- Verify: `app/services/chat_service.py`
- Verify: `app/ui/main_window_data.py`
- Verify: `tests/test_source_recovery.py`

- [ ] **Step 1: Run compile verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m compileall app tools
```

Expected:

```text
Listing 'app'...
Listing 'tools'...
```

- [ ] **Step 2: Run startup verification**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; .\.venv\Scripts\python.exe - <<'PY'
from app.main import run_app
print("startup-ok")
PY
```

Expected:

```text
startup-ok
```

- [ ] **Step 3: Record unresolved fidelity gaps explicitly**

If any rule still depends on inference rather than executable evidence, note it in the final handoff with three labels:

```text
confirmed-by-evidence
implemented-by-inference
blocked-pending-user-decision
```

- [ ] **Step 4: Do not create a Git commit until the index is repaired**

Run:

```powershell
git status --short
```

Expected:

```text
fatal: index file corrupt
```

Treat this as a known environment issue, not a code failure.
