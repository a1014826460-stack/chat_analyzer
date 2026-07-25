## Task 7 Review
**Spec Compliance:** PASS (with minor note)
**Code Quality:** Approved
**Findings:**

1. **[Important] Signal double-connection on repeated DB resolution.**
   `_connect_auto_bet_panel()` calls `panel.config_changed.connect(...)`, `panel.start_clicked.connect(...)`, and `panel.stop_clicked.connect(...)` without `Qt.UniqueConnection`. This method is called from `_resolve_database()` every time DB resolution succeeds. If the user resolves a different database (e.g., switching accounts), signals accumulate duplicate connections. Consequences: `_on_auto_bet_start` / `_on_auto_bet_stop` fire N times (harmless because `service.start()` / `stop()` are idempotent), and `_on_auto_bet_config_changed` saves settings N times (wasteful but not corrupting). Still recommended to guard: set a `_auto_bet_panel_connected` flag and skip re-wiring if already connected, or use `Qt.UniqueConnection`.

2. **[Minor] Stale `_connect_auto_bet_panel()` call in `__init__`.**
   At `main_window.py` line 187, `self._connect_auto_bet_panel()` is called before `self._activate_and_launch()`. However, the auto bet panel is created inside `_build_analysis_page()` (called from `_activate_and_launch()`). Because `_connect_auto_bet_panel()` checks `getattr(self, "auto_bet_panel", None)` and returns early when the panel is `None`, this first call is always a no-op. The real wiring happens in `_resolve_database()` at `main_window_data.py` line 166, where the panel already exists. The brief's step 8 intended this as a post-layout call but the placement pre-dates layout construction. Not a bug, just dead code on the first pass.

3. **[Minor] No error handling around `MessageInjector` construction.**
   `_on_auto_bet_start()` at `main_window_data.py` line 778 constructs `MessageInjector(resolved_db.msg_db, resolved_db.accid)` without a try/except. If `resolved_db.msg_db` points to a non-existent file, or `resolved_db.accid` is an unexpected type, the error propagates uncaught. A bare `AttributeError` or `FileNotFoundError` would reach the Qt event loop and manifest as a silent failure or crash dialog. Wrapping in try/except with a log message and user-facing error (e.g., `QMessageBox.warning`) would be safer.

**Strengths:**
- All 8 spec steps are precisely matched: imports, service init, timer creation, panel insertion, handler methods, DB resolution hook, and `__init__` call.
- The implementer correctly identified and fixed a brief omission: adding `from app.ui.auto_bet_panel import AutoBetPanel` to `main_window_layout.py`, without which step 4 would be a `NameError`.
- Signal wiring is complete and correct: `config_changed` -> save, `start_clicked` -> service + timer start, `stop_clicked` -> service + timer stop, `timer.timeout` -> tick evaluation.
- Every handler method uses defensive `getattr()` with `None` defaults, making the integration resilient to partial initialization.
- Thread safety is sound. The service's `threading.Lock` protects `_running`, `_last_bet_period`, config, and injector references correctly. Heavy analysis runs outside the lock. All callbacks to Qt widgets (`panel.append_log`) execute on the main thread because `tick()` is only invoked from `QTimer.timeout` (main thread).
- Panel visibility lifecycle is well-managed: starts hidden, only revealed after DB resolution and group population.
- The `data(32)` fallback pattern in group iteration (`main_window_data.py` line 812) is consistent with the codebase convention (same pattern at `main_window_actions.py` lines 26/69, `main_window_data.py` line 32).

**Overall:** Approved
