# UI Button Logging Stability Design

## Context

The desktop app currently starts from `app/main.py` and builds the main PySide6 window through `app/ui/main_window.py` plus focused mixins. The current UI code has recovered-source artifacts: user-visible Chinese text is mojibake in several files, the left panel relies on fixed widths and dense grid layouts, and button handlers do not provide consistent feedback or logging. `python -m compileall app tests` passes, so the immediate issue is usability and runtime behavior rather than syntax failure.

The user chose the wider repair path: fix adaptive UI layout and button/debug usability together.

## Goals

- Restore readable Chinese labels, placeholders, status text, and message boxes in the main window and chart panel.
- Make the left-side panel adapt better to window resizing by removing avoidable fixed maximum widths, using expanding columns, and preserving scroll behavior.
- Add consistent button-click feedback for all main user actions: status text before/after work, short button text feedback where useful, and visible error messages on failure.
- Improve debug logging so button entry points, important parameters, success paths, and exceptions are traceable in the rotating log file and debug console.
- Verify every button path that can be tested without manual OS file dialogs, and verify file-dialog buttons at least for signal wiring and method existence.

## Non-Goals

- Do not redesign the full product workflow.
- Do not change chat parsing, betting analysis, license generation, protection, proxy behavior, or build packaging semantics unless required to keep UI actions functional.
- Do not overwrite unrelated uncommitted user changes.

## Proposed Approach

Use a structured repair instead of a full rewrite.

1. Clean user-visible UI text in:
   - `app/ui/main_window.py`
   - `app/ui/main_window_layout.py`
   - `app/ui/main_window_data.py`
   - `app/ui/main_window_realtime.py`
   - `app/ui/main_window_blocking.py`
   - `app/ui/chart_window.py`
   - `app/utils/logging_config.py`

2. Improve left panel layout:
   - Keep `QScrollArea` for overflow.
   - Set practical minimum width and let the splitter allocate the rest.
   - Remove narrow `setMaximumWidth` constraints from path fields.
   - Use stretch columns in account/manual/time filter grids.
   - Ensure long labels wrap.

3. Add UI action feedback:
   - Introduce small helper methods on `MainWindow` for status updates and guarded action execution.
   - Log button clicks at debug/info level.
   - For operations that can fail, catch exceptions at the button boundary, log `logger.exception`, update `status_label`, and show a warning dialog.
   - Preserve existing worker-thread behavior for data loading.

4. Improve logging:
   - Keep the existing rotating file handler.
   - Make `configure(debug=True)` set the root logger to `DEBUG`; otherwise keep console quiet and file debug-capable.
   - Log the final log path and debug mode in readable text.
   - Avoid mojibake in log messages.

5. Verify:
   - Run `python -m compileall app tests`.
   - Run existing tests.
   - Add or use a lightweight offscreen PySide smoke test that instantiates `MainWindow`, finds push buttons, and invokes safe non-dialog actions.
   - Manually inspect or programmatically list button texts and connected handlers where possible.

## Risks And Mitigations

- Some buttons open native dialogs and cannot be fully automated in a headless run. Mitigate by validating method wiring and keeping dialog buttons out of automatic click execution.
- Some current files contain unrecovered mojibake strings. Mitigate by replacing only user-visible strings and preserving business logic.
- The worktree is dirty. Mitigate by inspecting diffs before edits and not reverting unrelated changes.

## Acceptance Criteria

- The app compiles without syntax errors.
- The main window can be instantiated in an offscreen Qt environment.
- Left panel fields and buttons no longer depend on hard-coded narrow maximum widths.
- Main user-visible labels and statuses in the primary window/chart are readable Chinese or clear English.
- Button clicks produce visible UI feedback and useful debug/error logs.
- Automated smoke checks cover safe buttons; remaining file-dialog buttons are documented as manually gated.
