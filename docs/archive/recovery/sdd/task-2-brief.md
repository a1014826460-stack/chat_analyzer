# Task 2: Message Injector

**Goal:** Create the message injection service that constructs and inserts betting messages into the Tencent Cloud IM local SQLite database.

**File to create:** `app/services/message_injector.py`

**Dependencies:** Task 1 (app/models/auto_bet.py) is already committed (8981f6a).

## Requirements (from spec)

1. `MessageInjector` class with constructor `__init__(msg_db: Path, sender_id: str)`
2. `inject_bet(group_id: str, play_type: str, amount: float) -> bool` — insert a betting message
3. `inject_text(group_id: str, text: str) -> bool` — insert arbitrary text message
4. Must detect the correct `client_time` unit (seconds/milliseconds/microseconds) by reading existing DB
5. Must generate appropriate `rand` value
6. Must build JSON `element_descriptions` in the SDK format: `[{"elem_type": 0, "text_elem_content": "..."}]`
7. Must use WAL journal mode for safe writes
8. `encrypt_content(plain: str) -> str` static method — AES-ECB with key "666888", Base64 encoded. Falls back to plaintext if pycryptodome unavailable.
9. `_fmt_amount(value: float) -> str` static helper — format numbers cleanly

## Database Schema

The `message` table in `msg_0.db`:
```sql
client_time          INTEGER  -- seconds, milliseconds, or microseconds (detect unit)
rand                INTEGER  -- random ordering value
sid                 TEXT     -- group/conversation identifier
sender              TEXT     -- sender user ID (accid)
element_descriptions TEXT    -- JSON array with message elements
content             TEXT     -- plaintext fallback
```

To detect time unit:
- If MAX(client_time) > 100_000_000_000_000 → microseconds (×1,000,000)
- If MAX(client_time) > 10_000_000_000 → milliseconds (×1,000)
- Otherwise → seconds (×1)

## Exact Code

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

## Testing

After writing the file, verify the module imports and basic functionality:

```bash
.\.venv\Scripts\python.exe -c "
from pathlib import Path
from app.services.message_injector import MessageInjector

# Test import and static methods
assert MessageInjector._fmt_amount(10.0) == '10'
assert MessageInjector._fmt_amount(10.5) == '10.50'
assert MessageInjector._fmt_amount(0) == '0'

# Test encrypt_content (should work with pycryptodome in venv)
encrypted = MessageInjector.encrypt_content('大 100')
print(f'Encrypt test: {encrypted[:40]}...')

# Test element description format
inj = MessageInjector.__new__(MessageInjector)
desc = inj._build_element_descriptions('test message')
import json
parsed = json.loads(desc)
assert isinstance(parsed, list)
assert parsed[0]['elem_type'] == 0
assert parsed[0]['text_elem_content'] == 'test message'

print('All injector tests passed!')
"
```
