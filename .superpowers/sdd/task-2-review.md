## Task 2 Review

**Spec Compliance:** ✅ PASS

All 10 requirements are met:
- R1: `__init__(msg_db: Path, sender_id: str)` — correct signature
- R2: `inject_bet` formats `"{play_type} {amount}"` using `_fmt_amount`
- R3: `inject_text` inserts arbitrary text via the same `_insert_message` path
- R4: Time unit detection thresholds match spec: >100T → microseconds, >10B → milliseconds, else seconds
- R5: `rand` is `random.randint(0, 0x7FFFFFFF)`, `client_time` computed with detected unit
- R6: `element_descriptions` is a JSON array with `elem_type: 0` and `text_elem_content`
- R7: `PRAGMA journal_mode=WAL` executed before each INSERT
- R8: `encrypt_content` static method — AES-ECB with key "666888", Base64, plaintext fallback
- R9: `_fmt_amount` — int amounts without decimals (10.0 → "10"), floats with 2 decimals (10.5 → "10.50")
- R10: INSERT column names (`client_time`, `rand`, `sid`, `sender`, `element_descriptions`, `content`) match `chat_service.py` reads exactly

**Code Quality:** Needs Fix

| Severity | Finding |
|----------|---------|
| **Critical** | **SQLite connection leak on error.** In `_insert_message`, when `con.execute("PRAGMA ...")`, `con.execute("INSERT ...")`, or `con.commit()` raises `sqlite3.DatabaseError`, the `except` block does not call `con.close()`. The connection object is left open. Over repeated failures (e.g., locked database, schema mismatch) this will leak file handles. Fix: use a `try`/`finally` or context-manager pattern to guarantee `con.close()`. |
| **Important** | **`encrypt_content` docstring is wrong.** It says "Returns empty string if pycryptodome unavailable", but the code returns `plain` (the unencrypted text). The docstring should say "Returns plaintext if pycryptodome unavailable." |
| **Minor** | **`_time_unit` sentinel conflates "not detected" with "detected as seconds".** `_time_unit` is initialized to `1` and the guard `if self._time_unit == 1` triggers re-detection. If the DB actually uses seconds, the re-detection guard fires on every call to `_now_in_db_units`. Functionally correct but wasteful — re-reads the DB on every injection. Use `None` as the sentinel instead. |
| **Minor** | **`_detect_time_unit` silently swallows errors.** When the connection or query fails, it returns `1` without any log. A `logger.debug(...)` would help diagnose why detection fell back. |

**Strengths:**
- Code matches the brief exactly with no deviations.
- `encrypt_content` fallback to plaintext is graceful; key-padding logic (null-pad to 16 bytes) handles the 6-char key correctly.
- Reuses `as_posix()` URI pattern consistent with `chat_service.py`, maintaining compatibility.
- Correctly omits the unused `datetime` import from the brief — no dead imports.
- Clean separation of public API (`inject_bet`, `inject_text`) from internal helpers.

**Overall:** Needs Fix (Critical connection leak must be resolved before merge)
