# Project Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the approved low-risk repository hygiene design while retaining the `app/` package and current user installer.

**Architecture:** Operational code stays at its existing supported entry points. Historical diagnostics move into `tools/diagnostics/`, closed plans and evidence move into `docs/archive/`, and all imports/tests are redirected to the new diagnostic package. Generated output is removed locally and blocked by precise ignore rules.

**Tech Stack:** Python 3.11, pytest, PySide6, Git, PowerShell 7.

---

### Task 1: Establish Diagnostic Package and Preserve Imports

**Files:**
- Create: `tools/__init__.py`
- Create: `tools/diagnostics/__init__.py`
- Move: `tools/inspect_wuquan_ui.py` -> `tools/diagnostics/inspect_wuquan_ui.py`
- Move: `tools/diagnose_robot_summary.py` -> `tools/diagnostics/diagnose_robot_summary.py`
- Modify: `app/services/uia_wuquan_sender.py`
- Modify: `tests/test_inspect_wuquan_ui.py`
- Modify: `tests/test_uia_wuquan_sender.py`
- Modify: `tests/test_source_recovery.py`

- [ ] **Step 1: Write a failing import-path test**

Update the tool-path assertions so they require
`tools/diagnostics/inspect_wuquan_ui.py` and imports from
`tools.diagnostics.inspect_wuquan_ui`.

- [ ] **Step 2: Run the focused test and verify it fails because the package is absent**

Run: `python -m pytest tests/test_inspect_wuquan_ui.py tests/test_uia_wuquan_sender.py -q`

Expected: a failing path/import assertion referencing the absent diagnostic
package.

- [ ] **Step 3: Move the utilities and redirect imports**

Create package markers, move the two files with `git mv`, update their root
path calculation from `parents[1]` to `parents[2]`, then update application
and test imports to `tools.diagnostics.*`.

- [ ] **Step 4: Run focused diagnostic tests**

Run: `python -m pytest tests/test_inspect_wuquan_ui.py tests/test_uia_wuquan_sender.py -q`

Expected: PASS.

### Task 2: Move Manual Probes and Recovery Utilities

**Files:**
- Move: manual `tools/test_*.py`, reverse-engineering/recovery `tools/*.py`
  -> `tools/diagnostics/`
- Move: `tests/tests_*_history_records.py`, `tests/tests_wss.py`
  -> snake-case `tools/diagnostics/probe_*.py`
- Delete: `tests/tests_PC28_crawler.py`
- Modify: moved diagnostic scripts and direct test imports

- [ ] **Step 1: Identify application imports before moving scripts**

Run:

```powershell
rg -n 'from tools\.|import tools\.' app tests tools --glob '*.py'
```

Expected: only the known production and test imports are candidates for
redirection; `tools/build.py` and release scripts stay in `tools/`.

- [ ] **Step 2: Move historical utilities with Git and rename manual probes**

Use `git mv` for tracked diagnostic files. Rename the historical probes to
`probe_aust_history_records.py`, `probe_macao_history_records.py`,
`probe_norway_history_records.py`, `probe_pc28_history_records.py`, and
`probe_wss.py`. Delete only the untracked crawler draft.

- [ ] **Step 3: Redirect helper imports and path-dependent tests**

Update `from tools._unrecovered_tool import main` to the diagnostic package,
and redirect test imports/path checks for `diagnose_robot_summary` and
`test_web_wss_c2c_message`. Change embedded usage/help paths to the new
location.

- [ ] **Step 4: Run import and protocol tests**

Run:

```powershell
python -m pytest tests/test_source_recovery.py -q
python -m pytest tests/test_wuquan_account_mapping.py tests/test_wss_protocol.py -q
```

Expected: no import or path failure attributable to the migration. Existing
unrelated baseline failures are recorded separately.

### Task 3: Archive Historical Documentation and Recovery Evidence

**Files:**
- Move: `docs/2026-07-10-session-handoff.md` -> `docs/archive/handoffs/`
- Move: `docs/2026-07-18-runtime-streaks-three-doors-design.md` ->
  `docs/archive/designs/`
- Move: historical `docs/superpowers/{plans,specs}/` ->
  `docs/archive/superpowers/`
- Move: `data/*` -> `docs/archive/recovery/data/`
- Move: reusable `.superpowers/sdd/*.{py,md,diff}` -> diagnostic/recovery
  archive locations
- Move: `archive/main.dart.js` -> `docs/archive/recovery/samples/`
- Delete: old `archive/` temporary output and tracked credential

- [ ] **Step 1: Move tracked historical records with `git mv`**

Create archive directories and move history rather than copying it. Retain the
active hygiene specification and its plan under `docs/superpowers/` while this
work is active.

- [ ] **Step 2: Move reusable recovery scripts and archive reports**

Move `.superpowers/sdd/*.py` to `tools/diagnostics/recovery/`; move reports
and diffs to `docs/archive/recovery/sdd/`. Remove
`.superpowers/sdd/wuquan_web_creds.json` from Git and delete its local copy.

- [ ] **Step 3: Remove only temporary recovery outputs**

Remove old `archive/` request captures, logs, temporary directories, and
generated cache outputs after the retained sample has been moved.

- [ ] **Step 4: Verify archive structure**

Run: `Get-ChildItem docs/archive -Recurse -File | Measure-Object`

Expected: historical documentation and recovery evidence are present under the
archive, while no legacy `archive/` or `.superpowers/` content remains.

### Task 4: Update Documentation and Ignore Policy

**Files:**
- Modify: `.gitignore`
- Modify: `README.md`
- Create: `docs/README.md`
- Modify: `docs/release-packaging.md`

- [ ] **Step 1: Write a failing documentation smoke check**

Use a temporary PowerShell assertion that requires README headings for setup,
run, test, user build, directory layout, and a `docs/README.md` index. Run it
before writing the documentation and verify the missing index fails.

- [ ] **Step 2: Write current, structured documentation**

Rewrite README around supported command paths and current version discovery,
add the documentation index, and replace stale release examples with a
literal `<version>` placeholder.

- [ ] **Step 3: Replace `.gitignore` with targeted rules**

Cover Python caches, environments, logs, local application data, credentials,
OS files, notebook checkpoints, packaging artifacts, and project temporary
directories. Keep `latest.json` and source JSON files eligible for tracking.

- [ ] **Step 4: Run documentation/ignore smoke checks**

Run PowerShell assertions for required README/index text and:

```powershell
git check-ignore -v build dist .pytest_cache .venv secrets/wuquan_web_creds.json
```

Expected: every generated/local target is matched by an intentional ignore
rule; `latest.json` remains unignored.

### Task 5: Remove Generated Outputs and Verify Repository Health

**Files:**
- Delete local generated directories: `.codex_recovery/`, `build/`,
  `summary_check/`, `.pytest_cache/`, repository `__pycache__/`
- Delete old `dist/` artifacts; retain `dist/StarTrace-1.99.8.exe`

- [ ] **Step 1: Confirm retained installer before cleanup**

Run: `Get-Item dist/StarTrace-1.99.8.exe`

Expected: the current user installer exists.

- [ ] **Step 2: Remove only approved generated artifacts**

Use PowerShell `Remove-Item -LiteralPath` against verified literal paths,
remove stale installer files individually, and remove empty directories.

- [ ] **Step 3: Compile and run checks**

Run:

```powershell
python -m compileall -q app tools
python -m pytest tests -q
git diff --check
git status --short --ignored
```

Expected: compilation is clean, only the known pre-existing test failures
remain, no whitespace errors exist, and generated paths are ignored.
