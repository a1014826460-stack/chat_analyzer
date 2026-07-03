# Task 4 Review

**Status: NEEDS FIX (medium severity)**

## Requirements Coverage

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 1 | `AutoBetService` class with background scheduling support | PASS | |
| 2 | `apply_config(config)` | PASS | Thread-safe via lock |
| 3 | `set_injector(injector)` | PASS | Thread-safe via lock |
| 4 | `set_result_provider(provider)` | PASS | Thread-safe via lock |
| 5 | `set_log_callback(callback)` | PASS | |
| 6 | `start()` / `stop()` lifecycle | PASS | Thread-safe state mutation, adds log entries |
| 7 | `tick(site, countdown_sec, current_period)` | PASS | Gate checks present: running, site, lock threshold, injector, dedup |
| 8 | Trend-following: count consecutive same results | PASS | Correctly reverses and counts from tail, breaks on mismatch |
| 9 | Dedup via `_last_bet_period` | **FAIL** | See Finding 1 |
| 10 | Lock threshold skip | PASS | `countdown_sec <= lock_threshold_sec` |
| 11 | Log cap at 500 | PASS | Trimmed in `_add_log` under lock |
| 12 | `threading.Lock` for shared state | PARTIAL | See Findings 2-4 |

## Findings

### 1. [MEDIUM] Race condition on `_last_bet_period` — dedup is not thread-safe

`_last_bet_period` is written on line 154 **outside** `self._lock`, but the dedup check on line 145 is inside the lock. If two threads call `tick()` concurrently for the same period:
- T1 acquires lock, passes dedup check (`_last_bet_period != current_period`)
- T1 releases lock
- T2 acquires lock, passes dedup check (T1 hasn't written `_last_bet_period` yet)
- Both threads proceed to place bets for the same period

**Fix:** Move the `self._last_bet_period = current_period` assignment inside the `with self._lock:` block, immediately after the dedup check passes. The assignment on line 154 should be relocated to line 127 (after `cfg = self._config`) or the lock scope should be extended to cover the write-back.

```python
# Current (buggy):
with self._lock:
    ...
    if self._last_bet_period == current_period:
        return
    cfg = self._config
# lock released here
decision = self._analyze(cfg)
...
self._last_bet_period = current_period  # <-- race window

# Fixed:
with self._lock:
    ...
    if self._last_bet_period == current_period:
        return
    self._last_bet_period = current_period  # <-- write inside lock
    cfg = self._config
```

### 2. [LOW] `_analyze` reads `_result_provider` without holding the lock

Line 142: `if self._result_provider is None` reads the field without `self._lock`, while `set_result_provider` writes it under the lock. This is a data race. In practice, the GIL prevents crashes, but it violates the thread-safety guarantee required by the spec. The snapshot `cfg` is already captured under lock on line 127 — `_analyze` should receive the provider as a parameter, or the read should be inside the locked section.

### 3. [LOW] `_execute` reads `_injector` without holding the lock

Line 186: `injector = self._injector` reads the field without `self._lock`, while `set_injector` writes it under the lock. Same pattern as Finding 2.

### 4. [LOW] `_on_log_updated` read/write not protected by lock

`set_log_callback` (line 73-74) writes `_on_log_updated` without the lock. `_add_log` (line 247) reads `_on_log_updated` without the lock. If `set_log_callback` is called while `_add_log` is executing on another thread, the read could observe a torn or stale value. This is unlikely to cause more than a missed callback invocation, but it is technically a data race.

### 5. [LOW] Unused import: `DrawResult`

Line 5 imports `DrawResult` but the class is never referenced in the service body. The service interacts with draw results only through the `DrawResultProvider` protocol. This is a dead import.

### 6. [NOTE] `callable | None` type annotation

Lines 38 and 72 use `callable | None` where `Callable[[InjectRecord], None] | None` from `typing` or `collections.abc` would be more precise. `callable` (lowercase) is a built-in function, not a proper type. With `from __future__ import annotations`, this is not evaluated at runtime and causes no crash, but type checkers (mypy, pyright) will flag it. Not a spec violation since the spec itself uses `callable | None` in the brief code.

## Verdict

**Needs fix — medium.** The dedup race condition (Finding 1) allows double-betting under concurrent `tick()` calls, which subverts a core correctness guarantee of the strategy engine. The fix is a one-line relocation. Findings 2-4 are lower-severity thread-safety hygiene issues that should be addressed to fully satisfy requirement 12. The brief's test suite passes because it only exercises single-threaded usage and doesn't cover the race window.
