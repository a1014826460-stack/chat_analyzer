# Auto Bet Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an automated betting module to StarTrace that injects betting messages into the local Tencent Cloud IM SQLite database (DB injection approach) with trend-following strategy.

**Architecture:** New `auto_bet` models define data types and strategy protocol. `MessageInjector` constructs AES-ECB encrypted messages and inserts them into `msg_0.db`. `AutoBetService` runs the trend-following strategy on a background thread, triggered by draw countdown ticks. `AutoBetPanel` is a PySide6 widget added to the left sidebar for config and control. Historical lottery data is provided through a `DrawResultProvider` protocol — external script handles actual fetching.

**Tech Stack:** Python 3.x, PySide6 (Qt), SQLite3, pycryptodome (AES-ECB), existing StarTrace infrastructure (AccountResolver, SettingsService/JsonStore, fetch_date)

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `app/models/auto_bet.py` | Data models and strategy protocol |
| Create | `app/services/message_injector.py` | SQLite message construction + injection |
| Create | `app/services/auto_bet_service.py` | Strategy engine + background scheduler |
| Create | `app/ui/auto_bet_panel.py` | PySide6 GUI panel widget |
| Create | `tests/test_message_injector.py` | DB injection verification script |
| Modify | `app/services/settings_service.py:18` | Add `auto_bet` default key |
| Modify | `app/ui/main_window.py:1-179` | Import + instantiate AutoBetPanel, wire signals |
| Modify | `app/ui/main_window_layout.py:246-258` | Add auto_bet panel to left sidebar |
| Modify | `app/ui/main_window_data.py:1-80` | Connect DB resolution → panel enable/disable |

---

### Task 1: Data Models and Strategy Protocol

**Files:**
- Create: `app/models/auto_bet.py`

- [ ] **Step 1: Write the data models file**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass
class DrawResult:
    """Single draw result fed into the strategy engine.

    Historical data fetching is handled by an external script;
    the strategy engine receives results through DrawResultProvider.
    """
    period: str           # e.g. "20250628001"
    site: str             # "pc28" | "macao" | "australia" | "norway"
    result: str           # "大" | "小" | "单" | "双" | numeric string
    open_time: datetime | None = None


@dataclass
class BetDecision:
    """Output of strategy analysis — a single betting instruction."""
    should_bet: bool
    play_type: str        # "大" | "小" | "单" | "双" | "大单" | ...
    amount: float
    group_id: str         # target group/conversation identifier (sid)
    reason: str           # human-readable explanation for the run log


@runtime_checkable
class DrawResultProvider(Protocol):
    """Protocol for providing historical draw results.

    External scripts implement this to feed data to the strategy engine.
    The actual HTTP fetching / parsing lives outside this module.
    """

    def get_recent_results(self, site: str, count: int) -> list[DrawResult]: ...

    def get_result(self, site: str, period: str) -> DrawResult | None: ...


@dataclass
class StrategyConfig:
    """Persistable strategy configuration, saved via SettingsService under key 'auto_bet'."""
    strategy_type: str = "trend_following"
    enabled: bool = False
    site: str = "pc28"
    target_groups: list[str] = field(default_factory=list)
    # Trend-following parameters
    observation_window: int = 10
    trigger_threshold: int = 3
    bet_amount: float = 10.0
    play_types: list[str] = field(default_factory=lambda: ["大", "小"])
    lock_threshold_sec: int = 15  # stop betting N seconds before draw cutoff

    def to_dict(self) -> dict:
        return {
            "strategy_type": self.strategy_type,
            "enabled": self.enabled,
            "site": self.site,
            "target_groups": self.target_groups,
            "observation_window": self.observation_window,
            "trigger_threshold": self.trigger_threshold,
            "bet_amount": self.bet_amount,
            "play_types": self.play_types,
            "lock_threshold_sec": self.lock_threshold_sec,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StrategyConfig":
        if not isinstance(data, dict):
            return cls()
        return cls(
            strategy_type=str(data.get("strategy_type", "trend_following")),
            enabled=bool(data.get("enabled", False)),
            site=str(data.get("site", "pc28")),
            target_groups=_ensure_str_list(data.get("target_groups")),
            observation_window=int(data.get("observation_window", 10)),
            trigger_threshold=int(data.get("trigger_threshold", 3)),
            bet_amount=float(data.get("bet_amount", 10.0)),
            play_types=_ensure_str_list(data.get("play_types", ["大", "小"])),
            lock_threshold_sec=int(data.get("lock_threshold_sec", 15)),
        )


def _ensure_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


@dataclass
class InjectRecord:
    """Record of an injected message for the run log display."""
    ts: datetime
    group_name: str
    play_type: str
    amount: float
    content: str
    success: bool
    error: str = ""
```

- [ ] **Step 2: Commit**

```bash
git add app/models/auto_bet.py
git commit -m "feat: add auto bet data models and strategy protocol"
```

---

### Task 2: Message Injector

**Files:**
- Create: `app/services/message_injector.py`

- [ ] **Step 1: Write the message injector**

```python
from __future__ import annotations

import base64
import json
import logging
import random
import sqlite3
import time
from datetime import datetime
from pathlib import Path

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
except ImportError:
    AES = None
    pad = None

logger = logging.getLogger(__name__)

FRONTEND_AAS_KEY = "666888"


class MessageInjector:
    """Construct and insert betting messages into the Tencent Cloud IM local SQLite database."""

    def __init__(self, msg_db: Path, sender_id: str) -> None:
        self._msg_db = Path(msg_db)
        self._sender_id = sender_id
        self._time_unit = 1  # detected on first inject

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def inject_bet(self, group_id: str, play_type: str, amount: float) -> bool:
        """Insert a single betting message. Returns True on success."""
        content = f"{play_type} {self._fmt_amount(amount)}"
        return self._insert_message(group_id, content)

    def inject_text(self, group_id: str, text: str) -> bool:
        """Insert an arbitrary text message. Returns True on success."""
        return self._insert_message(group_id, text)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _insert_message(self, group_id: str, text: str) -> bool:
        if not self._msg_db.exists():
            logger.error("msg_db not found: %s", self._msg_db)
            return False

        client_time = self._now_in_db_units()
        rand_val = random.randint(0, 0x7FFFFFFF)
        element_descriptions = self._build_element_descriptions(text)

        try:
            con = sqlite3.connect(f"file:{self._msg_db.as_posix()}?mode=rw", uri=True)
            con.execute("PRAGMA journal_mode=WAL")
            con.execute(
                """INSERT INTO message (client_time, rand, sid, sender, element_descriptions, content)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (client_time, rand_val, group_id, self._sender_id, element_descriptions, text),
            )
            con.commit()
            con.close()
            logger.info("Injected message: group=%s content=%s time=%s rand=%s", group_id, text, client_time, rand_val)
            return True
        except sqlite3.DatabaseError as exc:
            logger.exception("Failed to inject message into %s: %s", self._msg_db, exc)
            return False

    def _detect_time_unit(self) -> int:
        """Detect whether client_time is in seconds, milliseconds, or microseconds."""
        try:
            con = sqlite3.connect(f"file:{self._msg_db.as_posix()}?mode=ro", uri=True)
            row = con.execute("SELECT MAX(client_time) FROM message").fetchone()
            con.close()
            value = int((row[0] if row else 0) or 0)
            if value > 100_000_000_000_000:
                return 1_000_000
            if value > 10_000_000_000:
                return 1000
            return 1
        except sqlite3.DatabaseError:
            return 1

    def _now_in_db_units(self) -> int:
        if self._time_unit == 1:
            self._time_unit = self._detect_time_unit()
        return int(time.time() * max(1, self._time_unit))

    def _build_element_descriptions(self, text: str) -> str:
        """Build the JSON element_descriptions field matching the SDK's format."""
        return json.dumps(
            [
                {
                    "elem_type": 0,
                    "text_elem_content": text,
                }
            ],
            ensure_ascii=False,
        )

    @staticmethod
    def _fmt_amount(value: float) -> str:
        if value == int(value):
            return str(int(value))
        return f"{value:.2f}"

    @staticmethod
    def encrypt_content(plain: str) -> str:
        """AES-ECB encrypt + Base64 encode. Returns empty string if pycryptodome unavailable."""
        if AES is None or pad is None:
            logger.warning("pycryptodome not available — storing plaintext")
            return plain
        try:
            key = FRONTEND_AAS_KEY.encode("utf-8")
            if len(key) < 16:
                key = key + (b"\x00" * (16 - len(key)))
            cipher = AES.new(key[:16], AES.MODE_ECB)
            padded = pad(plain.encode("utf-8"), AES.block_size)
            return base64.b64encode(cipher.encrypt(padded)).decode("ascii")
        except Exception:
            logger.exception("Encryption failed, falling back to plaintext")
            return plain
```

- [ ] **Step 2: Commit**

```bash
git add app/services/message_injector.py
git commit -m "feat: add message injector for SQLite DB injection"
```

---

### Task 3: DB Injection Verification Test

**Files:**
- Create: `tests/test_message_injector.py`

- [ ] **Step 1: Write the verification test script**

```python
"""DB injection verification script.

Usage:
    python tests/test_message_injector.py <account_name>

This script:
1. Resolves the account's msg_0.db via AccountResolver
2. Reads the current state of the message table
3. Injects a test message
4. Prints the injected row for manual verification in the WuQuan client
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# Ensure the project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.account_resolver import AccountResolver
from app.services.message_injector import MessageInjector


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python tests/test_message_injector.py <account_name>")
        sys.exit(1)

    account_name = sys.argv[1]
    print(f"[1/5] Resolving account: {account_name}")
    resolver = AccountResolver()
    resolved = resolver.resolve(account_name)

    if resolved is None:
        diag = resolver.get_diagnostic()
        if diag is not None:
            print(diag.format_message())
        print("ERROR: Could not resolve account database.")
        sys.exit(1)

    print(f"       Config dir:  {resolved.config_dir}")
    print(f"       msg_db:      {resolved.msg_db}")
    print(f"       accid:       {resolved.accid}")

    # ------------------------------------------------------------------
    # Read current state
    # ------------------------------------------------------------------
    print("\n[2/5] Reading current message table state...")
    try:
        con = sqlite3.connect(f"file:{resolved.msg_db.as_posix()}?mode=ro", uri=True)
        row = con.execute("SELECT MAX(client_time), MAX(rand) FROM message").fetchone()
        max_time = int((row[0] if row else 0) or 0)
        max_rand = int((row[1] if row else 0) or 0)
        count_row = con.execute("SELECT COUNT(*) FROM message").fetchone()
        total_count = int((count_row[0] if count_row else 0) or 0)
        con.close()
        print(f"       Total messages: {total_count}")
        print(f"       Max client_time: {max_time}")
        print(f"       Max rand:        {max_rand}")
    except sqlite3.DatabaseError as exc:
        print(f"ERROR reading database: {exc}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Inject test message
    # ------------------------------------------------------------------
    print("\n[3/5] Injecting test message...")
    injector = MessageInjector(resolved.msg_db, resolved.accid)

    # Pick a group to inject into — use the first group found
    try:
        con = sqlite3.connect(f"file:{resolved.msg_db.as_posix()}?mode=ro", uri=True)
        group_row = con.execute(
            "SELECT sid, COUNT(*) as cnt FROM message WHERE sid != 'Unknown' GROUP BY sid ORDER BY cnt DESC LIMIT 1"
        ).fetchone()
        con.close()
        test_group = str(group_row[0]) if group_row else "test_group"
    except sqlite3.DatabaseError:
        test_group = "test_group"

    print(f"       Target group: {test_group}")
    test_content = f"大 999"  # distinctive amount for easy identification

    success = injector.inject_bet(test_group, "大", 999.0)
    print(f"       Injection result: {'SUCCESS' if success else 'FAILED'}")

    if not success:
        print("ERROR: Injection failed.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Verify the inserted row
    # ------------------------------------------------------------------
    print("\n[4/5] Verifying inserted row...")
    try:
        con = sqlite3.connect(f"file:{resolved.msg_db.as_posix()}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM message WHERE content = ? ORDER BY client_time DESC LIMIT 1",
            (test_content,),
        ).fetchall()
        con.close()

        if rows:
            row = rows[0]
            print(f"       Found injected row:")
            print(f"         client_time:         {row['client_time']}")
            print(f"         rand:                {row['rand']}")
            print(f"         sid:                 {row['sid']}")
            print(f"         sender:              {row['sender']}")
            print(f"         element_descriptions:{row['element_descriptions'][:120]}")
            print(f"         content:             {row['content']}")
        else:
            print("WARNING: Injected row not found — check manually.")
    except sqlite3.DatabaseError as exc:
        print(f"ERROR verifying: {exc}")

    # ------------------------------------------------------------------
    # Manual verification instructions
    # ------------------------------------------------------------------
    print("\n[5/5] Manual verification:")
    print(f"       1. Open the WuQuan client (log in as: {resolved.account_name})")
    print(f"       2. Navigate to the group: {test_group}")
    print(f"       3. Look for a message: '{test_content}'")
    print(f"       4. If the message appears → DB injection WORKS ✓")
    print(f"       5. If it does NOT appear → DB injection does not trigger SDK sync ✗")
    print(f"          → Fall back to UI automation approach.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add tests/test_message_injector.py
git commit -m "test: add DB injection verification script"
```

---

### Task 4: Auto Bet Service (Strategy Engine + Scheduler)

**Files:**
- Create: `app/services/auto_bet_service.py`

- [ ] **Step 1: Write the auto bet service**

```python
from __future__ import annotations

import logging
import threading
from datetime import datetime

from app.models.auto_bet import BetDecision, DrawResult, DrawResultProvider, InjectRecord, StrategyConfig
from app.services.message_injector import MessageInjector


logger = logging.getLogger(__name__)


class AutoBetService:
    """Strategy engine and scheduler for automated betting.

    Runs on a background thread. The GUI calls tick() on each countdown
    update; the service decides whether to place a bet.

    Historical draw results come from an external DrawResultProvider
    (implemented by a separate script that fetches/parses lottery APIs).
    """

    def __init__(self) -> None:
        self._config = StrategyConfig()
        self._injector: MessageInjector | None = None
        self._result_provider: DrawResultProvider | None = None
        self._running = False
        self._lock = threading.Lock()
        self._log: list[InjectRecord] = []
        self._max_log_lines = 500
        self._on_log_updated: callable | None = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @property
    def config(self) -> StrategyConfig:
        with self._lock:
            return StrategyConfig(
                strategy_type=self._config.strategy_type,
                enabled=self._config.enabled,
                site=self._config.site,
                target_groups=list(self._config.target_groups),
                observation_window=self._config.observation_window,
                trigger_threshold=self._config.trigger_threshold,
                bet_amount=self._config.bet_amount,
                play_types=list(self._config.play_types),
                lock_threshold_sec=self._config.lock_threshold_sec,
            )

    def apply_config(self, config: StrategyConfig) -> None:
        with self._lock:
            self._config = config

    def set_injector(self, injector: MessageInjector | None) -> None:
        with self._lock:
            self._injector = injector

    def set_result_provider(self, provider: DrawResultProvider | None) -> None:
        with self._lock:
            self._result_provider = provider

    def set_log_callback(self, callback: callable | None) -> None:
        """Set callback(record: InjectRecord) for GUI log updates."""
        self._on_log_updated = callback

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            self._running = True
        self._add_log(InjectRecord(
            ts=datetime.now(),
            group_name="",
            play_type="",
            amount=0,
            content="策略引擎已启动",
            success=True,
        ))

    def stop(self) -> None:
        with self._lock:
            self._running = False
        self._add_log(InjectRecord(
            ts=datetime.now(),
            group_name="",
            play_type="",
            amount=0,
            content="策略引擎已停止",
            success=True,
        ))

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    # ------------------------------------------------------------------
    # Main tick — called by GUI on each countdown update
    # ------------------------------------------------------------------

    def tick(self, site: str, countdown_sec: int, current_period: str) -> None:
        """Evaluate strategy and place bets if conditions are met.

        Called from the GUI's countdown timer. Runs synchronously
        (the GUI should call this from a worker thread if needed).
        """
        with self._lock:
            if not self._running:
                return
            if site != self._config.site:
                return
            if countdown_sec <= self._config.lock_threshold_sec:
                return  # too close to cutoff
            if not self._injector:
                return
            cfg = self._config

        # Check if we already bet for this period
        # (simple dedup: track last bet period in memory)
        if getattr(self, "_last_bet_period", "") == current_period:
            return
        self._last_bet_period = current_period

        decision = self._analyze(cfg)
        if not decision.should_bet:
            return

        self._execute(decision)

    # ------------------------------------------------------------------
    # Strategy: Trend Following
    # ------------------------------------------------------------------

    def _analyze(self, cfg: StrategyConfig) -> BetDecision:
        """Run the trend-following strategy."""
        if self._result_provider is None:
            return BetDecision(should_bet=False, play_type="", amount=0, group_id="", reason="无历史数据提供者")

        results = self._result_provider.get_recent_results(cfg.site, cfg.observation_window)
        if len(results) < cfg.trigger_threshold:
            return BetDecision(should_bet=False, play_type="", amount=0, group_id="", reason="历史数据不足")

        # Get the most recent results, ordered by period
        sorted_results = sorted(results, key=lambda r: r.period)[-cfg.observation_window:]

        # Count consecutive identical results from the tail
        if not sorted_results:
            return BetDecision(should_bet=False, play_type="", amount=0, group_id="", reason="无数据")

        tail_result = sorted_results[-1].result
        consecutive = 0
        for r in reversed(sorted_results):
            if r.result == tail_result:
                consecutive += 1
            else:
                break

        if consecutive < cfg.trigger_threshold:
            return BetDecision(
                should_bet=False, play_type="", amount=0, group_id="",
                reason=f"连续{consecutive}期'{tail_result}'，未达阈值{cfg.trigger_threshold}",
            )

        # Reverse bet: bet on the opposite
        opposite = self._opposite_play(tail_result, cfg.play_types)
        if opposite is None:
            return BetDecision(should_bet=False, play_type="", amount=0, group_id="", reason="无可用反向玩法")

        # Pick first target group
        target_group = cfg.target_groups[0] if cfg.target_groups else ""

        return BetDecision(
            should_bet=True,
            play_type=opposite,
            amount=cfg.bet_amount,
            group_id=target_group,
            reason=f"连续{consecutive}期'{tail_result}'→反向'{opposite}'",
        )

    def _execute(self, decision: BetDecision) -> None:
        """Inject the bet into the database."""
        injector = self._injector
        if injector is None:
            self._add_log(InjectRecord(
                ts=datetime.now(), group_name=decision.group_id,
                play_type=decision.play_type, amount=decision.amount,
                content="", success=False, error="消息注入器未初始化",
            ))
            return

        success = injector.inject_bet(decision.group_id, decision.play_type, decision.amount)
        self._add_log(InjectRecord(
            ts=datetime.now(),
            group_name=decision.group_id,
            play_type=decision.play_type,
            amount=decision.amount,
            content=f"{decision.play_type} {decision.amount}",
            success=success,
            error="" if success else "DB 注入失败",
        ))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _opposite_play(result: str, play_types: list[str]) -> str | None:
        """Given a result like '大', return the opposite play from the allowed list."""
        opposites = {"大": "小", "小": "大", "单": "双", "双": "单"}
        opposite = opposites.get(result)
        if opposite and opposite in play_types:
            return opposite
        # If exact opposite not available, pick any other play type
        for pt in play_types:
            if pt != result:
                return pt
        return None

    def _add_log(self, record: InjectRecord) -> None:
        with self._lock:
            self._log.append(record)
            if len(self._log) > self._max_log_lines:
                self._log = self._log[-self._max_log_lines:]
        if self._on_log_updated:
            try:
                self._on_log_updated(record)
            except Exception:
                logger.exception("Log callback failed")

    def get_logs(self) -> list[InjectRecord]:
        with self._lock:
            return list(self._log)

    def clear_logs(self) -> None:
        with self._lock:
            self._log.clear()
```

- [ ] **Step 2: Commit**

```bash
git add app/services/auto_bet_service.py
git commit -m "feat: add auto bet service with trend-following strategy engine"
```

---

### Task 5: Auto Bet GUI Panel

**Files:**
- Create: `app/ui/auto_bet_panel.py`

- [ ] **Step 1: Write the GUI panel widget**

```python
from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.models.auto_bet import InjectRecord, StrategyConfig


logger = logging.getLogger(__name__)

PLAY_TYPE_OPTIONS = ["大", "小", "单", "双", "大单", "小单", "大双", "小双"]
SITE_OPTIONS = ["pc28", "macao", "australia", "norway"]


class AutoBetPanel(QGroupBox):
    """Auto-betting configuration and control panel.

    Signals:
        config_changed(StrategyConfig) — emitted when any parameter changes
        start_clicked() — start button pressed
        stop_clicked()  — stop button pressed
    """

    config_changed = Signal(object)
    start_clicked = Signal()
    stop_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("自动下注", parent)
        self._config = StrategyConfig()
        self._running = False
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_available_groups(self, groups: list[tuple[str, str]]) -> None:
        """Populate target group checklist. Each item is (group_id, group_name)."""
        self._target_group_list.clear()
        for group_id, group_name in groups:
            item = QListWidgetItem(group_name)
            item.setData(Qt.UserRole, group_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(
                Qt.Checked if group_id in self._config.target_groups else Qt.Unchecked
            )
            self._target_group_list.addItem(item)

    def set_running(self, running: bool) -> None:
        """Update UI for running/stopped state."""
        self._running = running
        self._start_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)
        self._status_label.setText("● 运行中" if running else "○ 已停止")
        self._status_label.setStyleSheet(
            "color: #4caf50; font-weight: bold;" if running else "color: #9e9e9e;"
        )

    def append_log(self, record: InjectRecord) -> None:
        """Append a line to the run log."""
        ts = record.ts.strftime("%H:%M:%S")
        icon = "✓" if record.success else "✗"
        if record.play_type:
            line = f"{ts} {icon} [{record.group_name}] → {record.play_type} {record.amount}"
        else:
            line = f"{ts} {icon} {record.content}"
        if record.error:
            line += f"  ({record.error})"
        self._log_edit.append(line)

    def get_config(self) -> StrategyConfig:
        """Build config from current UI state."""
        checked_groups: list[str] = []
        for i in range(self._target_group_list.count()):
            item = self._target_group_list.item(i)
            if item.checkState() == Qt.Checked:
                gid = str(item.data(Qt.UserRole) or "")
                if gid:
                    checked_groups.append(gid)

        checked_plays: list[str] = []
        for pt, cb in self._play_checkboxes.items():
            if cb.isChecked():
                checked_plays.append(pt)

        return StrategyConfig(
            strategy_type="trend_following",
            enabled=self._running,
            site=self._site_combo.currentText().strip(),
            target_groups=checked_groups,
            observation_window=self._obs_window_spin.value(),
            trigger_threshold=self._trigger_spin.value(),
            bet_amount=self._amount_spin.value(),
            play_types=checked_plays,
            lock_threshold_sec=self._lock_spin.value(),
        )

    def load_config(self, config: StrategyConfig) -> None:
        """Apply config to UI fields."""
        self._config = config
        idx = self._site_combo.findText(config.site)
        if idx >= 0:
            self._site_combo.setCurrentIndex(idx)
        self._obs_window_spin.setValue(config.observation_window)
        self._trigger_spin.setValue(config.trigger_threshold)
        self._amount_spin.setValue(config.bet_amount)
        self._lock_spin.setValue(config.lock_threshold_sec)
        for pt, cb in self._play_checkboxes.items():
            cb.setChecked(pt in config.play_types)

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # --- Row: strategy type ---
        strategy_row = QHBoxLayout()
        strategy_row.addWidget(QLabel("策略:"))
        self._strategy_combo = QComboBox()
        self._strategy_combo.addItem("趋势跟踪", "trend_following")
        self._strategy_combo.currentIndexChanged.connect(self._emit_config)
        strategy_row.addWidget(self._strategy_combo, 1)
        layout.addLayout(strategy_row)

        # --- Row: site ---
        site_row = QHBoxLayout()
        site_row.addWidget(QLabel("站点:"))
        self._site_combo = QComboBox()
        self._site_combo.addItems(SITE_OPTIONS)
        self._site_combo.currentTextChanged.connect(self._emit_config)
        site_row.addWidget(self._site_combo, 1)
        layout.addLayout(site_row)

        # --- Target groups ---
        layout.addWidget(QLabel("目标群组:"))
        self._target_group_list = QListWidget()
        self._target_group_list.setMaximumHeight(80)
        self._target_group_list.itemChanged.connect(self._emit_config)
        layout.addWidget(self._target_group_list)

        # --- Parameters grid ---
        grid = QHBoxLayout()
        grid.addWidget(QLabel("观察窗口:"))
        self._obs_window_spin = QSpinBox()
        self._obs_window_spin.setRange(3, 100)
        self._obs_window_spin.setValue(10)
        self._obs_window_spin.valueChanged.connect(self._emit_config)
        grid.addWidget(self._obs_window_spin)
        grid.addWidget(QLabel("期"))
        grid.addWidget(QLabel("触发阈值:"))
        self._trigger_spin = QSpinBox()
        self._trigger_spin.setRange(2, 50)
        self._trigger_spin.setValue(3)
        self._trigger_spin.valueChanged.connect(self._emit_config)
        grid.addWidget(self._trigger_spin)
        grid.addWidget(QLabel("次"))
        grid.addStretch(1)
        layout.addLayout(grid)

        # --- Amount ---
        amt_row = QHBoxLayout()
        amt_row.addWidget(QLabel("下注金额:"))
        self._amount_spin = QDoubleSpinBox()
        self._amount_spin.setRange(0.01, 999999.0)
        self._amount_spin.setDecimals(2)
        self._amount_spin.setValue(10.0)
        self._amount_spin.valueChanged.connect(self._emit_config)
        amt_row.addWidget(self._amount_spin)
        amt_row.addStretch(1)
        layout.addLayout(amt_row)

        # --- Play types ---
        play_row = QHBoxLayout()
        play_row.addWidget(QLabel("玩法:"))
        self._play_checkboxes: dict[str, QCheckBox] = {}
        for pt in PLAY_TYPE_OPTIONS:
            cb = QCheckBox(pt)
            cb.setChecked(pt in ("大", "小"))
            cb.toggled.connect(self._emit_config)
            self._play_checkboxes[pt] = cb
            play_row.addWidget(cb)
        play_row.addStretch(1)
        layout.addLayout(play_row)

        # --- Lock threshold ---
        lock_row = QHBoxLayout()
        lock_row.addWidget(QLabel("封盘提前:"))
        self._lock_spin = QSpinBox()
        self._lock_spin.setRange(5, 120)
        self._lock_spin.setValue(15)
        self._lock_spin.valueChanged.connect(self._emit_config)
        lock_row.addWidget(self._lock_spin)
        lock_row.addWidget(QLabel("秒"))
        lock_row.addStretch(1)
        layout.addLayout(lock_row)

        # --- Start/Stop buttons ---
        btn_row = QHBoxLayout()
        self._start_btn = QPushButton("▶ 启动")
        self._start_btn.clicked.connect(self._on_start)
        btn_row.addWidget(self._start_btn)
        self._stop_btn = QPushButton("■ 停止")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop)
        btn_row.addWidget(self._stop_btn)
        self._status_label = QLabel("○ 已停止")
        self._status_label.setStyleSheet("color: #9e9e9e;")
        btn_row.addWidget(self._status_label)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        # --- Run log ---
        layout.addWidget(QLabel("运行日志:"))
        self._log_edit = QTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setMaximumHeight(150)
        self._log_edit.setPlaceholderText("策略运行日志将显示在这里...")
        layout.addWidget(self._log_edit)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _emit_config(self) -> None:
        self.config_changed.emit(self.get_config())

    def _on_start(self) -> None:
        self.set_running(True)
        self.start_clicked.emit()

    def _on_stop(self) -> None:
        self.set_running(False)
        self.stop_clicked.emit()
```

- [ ] **Step 2: Commit**

```bash
git add app/ui/auto_bet_panel.py
git commit -m "feat: add auto bet GUI panel with strategy config and run log"
```

---

### Task 6: Update Settings Service

**Files:**
- Modify: `app/services/settings_service.py:18`

- [ ] **Step 1: Add `auto_bet` default key to settings**

In `app/services/settings_service.py`, locate the `load` method's default dict (line 18). Add `"auto_bet": {}` after line 46 (`"proxy_https": ""`):

```python
# Inside the load() method, add to the default dict:
                "proxy_https": "",
                "auto_bet": {},
```

The edit: find `"proxy_https": "",` and append `"auto_bet": {},` on the next line.

- [ ] **Step 2: Commit**

```bash
git add app/services/settings_service.py
git commit -m "feat: add auto_bet key to settings defaults"
```

---

### Task 7: Wire Auto Bet Panel into Main Window

**Files:**
- Modify: `app/ui/main_window.py`
- Modify: `app/ui/main_window_layout.py`
- Modify: `app/ui/main_window_data.py`

- [ ] **Step 1: Add import and initialization in main_window.py**

After the existing import block in `app/ui/main_window.py` (around line 16), add:

```python
from app.services.auto_bet_service import AutoBetService
from app.ui.auto_bet_panel import AutoBetPanel
```

Then in `__init__`, after `self.summary_check_report_service = ...` (around line 64), add:

```python
self.auto_bet_service = AutoBetService()
```

After the signal connections block (around line 128, after `self._update_download_ready.connect(...)`), add:

```python
self._auto_bet_timer = QTimer(self)
self._auto_bet_timer.setInterval(2000)
self._auto_bet_timer.timeout.connect(self._on_auto_bet_tick)
```

- [ ] **Step 2: Add auto_bet panel to layout in main_window_layout.py**

In `_build_analysis_page()`, after the `left.addWidget(block_box)` block (around line 246) and before the `action_box` block (around line 249), insert:

```python
        # --- Auto Bet Panel ---
        self.auto_bet_panel = AutoBetPanel()
        self.auto_bet_panel.setVisible(False)  # hidden until DB is resolved
        left.addWidget(self.auto_bet_panel)
        self._configure_left_section(self.auto_bet_panel)
```

- [ ] **Step 3: Add auto_bet tick handler to main_window_data.py**

In `app/ui/main_window_data.py`, add this method to `MainWindowDataMixin` (at the end of the class, before any trailing code):

```python
    def _on_auto_bet_tick(self) -> None:
        """Called by auto_bet timer to evaluate betting strategy."""
        service = getattr(self, "auto_bet_service", None)
        if service is None or not service.is_running:
            return
        active_site = getattr(self, "_active_site", "")
        draw_infos = getattr(self, "_draw_infos", {})
        info = draw_infos.get(active_site) if isinstance(draw_infos, dict) else None
        if info is None:
            return
        current_period = info.current_period or ""
        countdown = info.next_countdown or 0
        service.tick(active_site, countdown, current_period)
```

And in `_load_initial_state()` (or wherever the DB is resolved), after successfully loading data, connect the auto bet panel. Add at the end of `_resolve_database` success flow (in `main_window_actions.py` or the main window file):

In `main_window.py` `__init__`, after the panel is created, wire the signals. Add after the `self.auto_bet_panel = AutoBetPanel()` line (in the layout mixin context, wire from main_window.py side):

In `main_window.py` `__init__`, add signal wiring near other signal connections:

```python
# Wire auto bet panel signals (panel created in layout)
# Defer until panel exists
```

Actually — since the panel is created in `_build_analysis_page()` (layout mixin), and signal wiring happens in `__init__` after `_build_analysis_page()` is called, we need to wire after construction.

In `main_window.py` `__init__`, after the call that triggers layout building, or in `_load_initial_state()`, wire:

```python
        # Wire auto_bet panel
        if hasattr(self, "auto_bet_panel"):
            self.auto_bet_panel.config_changed.connect(self._on_auto_bet_config_changed)
            self.auto_bet_panel.start_clicked.connect(self._on_auto_bet_start)
            self.auto_bet_panel.stop_clicked.connect(self._on_auto_bet_stop)
            self.auto_bet_service.set_log_callback(self.auto_bet_panel.append_log)
```

Add these handler methods to `MainWindowDataMixin`:

```python
    def _on_auto_bet_config_changed(self, config: object) -> None:
        """Save auto bet config to settings."""
        service = getattr(self, "auto_bet_service", None)
        if service is None:
            return
        from app.models.auto_bet import StrategyConfig
        if isinstance(config, StrategyConfig):
            service.apply_config(config)
            self.settings["auto_bet"] = config.to_dict()
            self.settings_service.save(self.settings)

    def _on_auto_bet_start(self) -> None:
        """Start the auto bet engine."""
        service = getattr(self, "auto_bet_service", None)
        if service is None:
            return
        resolved_db = getattr(self, "resolved_db", None)
        if resolved_db is None:
            return
        from app.services.message_injector import MessageInjector
        injector = MessageInjector(resolved_db.msg_db, resolved_db.accid)
        service.set_injector(injector)
        service.start()
        timer = getattr(self, "_auto_bet_timer", None)
        if timer is not None:
            timer.start()

    def _on_auto_bet_stop(self) -> None:
        """Stop the auto bet engine."""
        service = getattr(self, "auto_bet_service", None)
        if service is not None:
            service.stop()
        timer = getattr(self, "_auto_bet_timer", None)
        if timer is not None:
            timer.stop()
```

- [ ] **Step 4: Enable panel when DB is resolved**

In `MainWindowDataMixin`, find the method that handles successful DB resolution (likely `_handle_load_result_ready` or `_resolve_database`). After the DB is successfully resolved, show the panel and populate groups:

```python
        # After successful DB resolution:
        if hasattr(self, "auto_bet_panel") and self.resolved_db is not None:
            self.auto_bet_panel.setVisible(True)
            # Populate groups from the group list
            groups = []
            if hasattr(self, "group_list"):
                for i in range(self.group_list.count()):
                    item = self.group_list.item(i)
                    gid = str(item.data(Qt.UserRole) or item.data(32) or "")
                    gname = item.text()
                    if gname:
                        groups.append((gid or gname, gname))
            self.auto_bet_panel.set_available_groups(groups)
```

Also load saved config:

```python
            # Load saved auto_bet config
            saved = self.settings.get("auto_bet", {})
            if saved:
                from app.models.auto_bet import StrategyConfig
                cfg = StrategyConfig.from_dict(saved)
                self.auto_bet_panel.load_config(cfg)
                self.auto_bet_service.apply_config(cfg)
```

- [ ] **Step 5: Commit**

```bash
git add app/ui/main_window.py app/ui/main_window_layout.py app/ui/main_window_data.py
git commit -m "feat: integrate auto bet panel into main window"
```

---

### Task 8: End-to-End Smoke Test

**Files:**
- Create: (manual verification, no new file)

- [ ] **Step 1: Run the injection verification test**

```bash
python tests/test_message_injector.py <your_account_name>
```

- [ ] **Step 2: Verify in WuQuan client**

Open WuQuan, check if the test message "大 999" appears in the target group.

- [ ] **Step 3: Launch StarTrace and verify GUI**

```bash
.\.venv\Scripts\python.exe app\main.py --admin --debug
```

Checklist:
- [ ] "自动下注" panel appears in left sidebar below "屏蔽名单"
- [ ] Panel is hidden when no DB is resolved
- [ ] After resolving DB, panel shows and groups are populated
- [ ] Config changes persist across restart
- [ ] Start/Stop buttons toggle correctly
- [ ] Run log displays messages

- [ ] **Step 4: Commit any final fixes**

```bash
git add -A
git commit -m "chore: final integration fixes for auto bet bot"
```
