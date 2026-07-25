# Task 3: DB Injection Verification Test

**Goal:** Create a standalone test script that verifies DB injection actually triggers message sync in the WuQuan client.

**File to create:** `tests/test_message_injector.py`

**Dependencies:** Task 1 (models) and Task 2 (message_injector) already committed.

## Requirements

1. Accept account name as CLI argument
2. Use `AccountResolver` to locate `msg_0.db`
3. Read current `message` table state (max client_time, max rand, total count)
4. Pick a target group (most active group from DB)
5. Inject a distinctive test message ("大 999") using `MessageInjector.inject_bet()`
6. Verify the inserted row by reading it back
7. Print manual verification instructions

## Exact Code

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

    # Pick a group to inject into — use the most active group
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

## Testing

Verify the script can be parsed and imports work:

```bash
.\.venv\Scripts\python.exe -c "import ast; ast.parse(open('tests/test_message_injector.py').read()); print('Syntax OK')"
```

Note: The script requires an actual account to run the full injection test. The syntax check above is sufficient for CI-like verification.
