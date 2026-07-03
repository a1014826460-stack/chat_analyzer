## Task 7 Report
**Status:** DONE
**Commits:** aaf7e57
**Tests:** Import test passed: `from app.services.auto_bet_service import AutoBetService; from app.ui.auto_bet_panel import AutoBetPanel` -- OK. Full main_window module import test also passed.
**Self-Review:** All 7 edits applied per the brief to three files. Also added a necessary import of `AutoBetPanel` to `main_window_layout.py` (the brief's step 4 code references the class in that module but omits the import -- added it to match the module's existing import pattern).
**Concerns:** None.

## Task 7 Fix: Duplicate Auto Bet Panel Signal Connections
**Status:** DONE
**Commit:** 8096a4e
**File:** `app/ui/main_window_data.py` -- `_connect_auto_bet_panel()`
**Problem:** `_connect_auto_bet_panel()` is called from `_resolve_database()` (line 166), which can fire multiple times (repeated DB resolution). Each call connected signals anew, causing duplicate handler invocations.
**Fix:** Added a guard flag `_auto_bet_panel_connected` at the top of the method. On first call the flag is set to `True` after the guard check; subsequent calls return immediately.
**Test:** `from app.ui.main_window import MainWindow; print('Import OK')` -- passed.
