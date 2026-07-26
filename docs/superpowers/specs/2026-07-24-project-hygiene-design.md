# Project Hygiene Design

## Goal

Reorganize the repository without changing application behavior: retain the
existing `app/` package and supported build entry points, separate historical
diagnostics and documentation from current work, remove only confirmed
generated artifacts, and make ignored local state explicit.

## Scope and Constraints

- Keep `app/` as the production source package. `app/main.py`, the tests, and
  `tools/build.py` already depend on this layout; a `src/` migration is out of
  scope.
- Keep active automated tests in `tests/`.
- Preserve diagnostic/recovery utilities under `tools/diagnostics/`.
- Preserve historical plans, specifications, handoffs, reports, diffs, and
  recovery samples under `docs/archive/`.
- Delete only build caches, superseded installers, temporary outputs, and the
  untracked `tests/tests_PC28_crawler.py` draft. No application source or
  active automated test is deleted.
- Never retain a credential in a tracked file. The existing local credential
  sample will be moved to an ignored `secrets/` location and removed from Git
  tracking without displaying its contents.

## Target Layout

```text
app/                         # Production application package (unchanged)
assets/                      # Runtime assets
docs/
  README.md                  # Documentation index
  archive/
    handoffs/                # Closed-session notes
    designs/                 # Superseded standalone designs
    superpowers/             # Historical plans and specifications
    recovery/                # Recovery reports, samples, and evidence
  *.md                       # Current operational and product documentation
tests/                       # Automated tests only
tools/
  diagnostics/               # Manual probes, reverse-engineering, recovery tools
  build.py, release_*.py, ...# Supported build and release tooling
```

The root retains only source/documentation directories plus the supported
runtime, build, and release metadata files. Existing root batch and PowerShell
wrappers stay in place because documented workflows and tests invoke them
directly.

## Migration Rules

### Diagnostics and Manual Probes

Move `tools/_unrecovered_tool.py`, the `decode_*`, `extract_*`, `find_*`,
`generate_keys.py`, `hook_imsdk_message_flow.py`, `inspect_*`,
`diagnose_robot_summary.py`, and manual `test_*` communication probes into
`tools/diagnostics/`. Add package markers and update imports, command help,
production imports, and tests to use `tools.diagnostics.*`.

Move these manual site probes out of `tests/` and rename them in snake case:

- `tests_Aust_history_records.py` -> `probe_aust_history_records.py`
- `tests_Macao_history_records.py` -> `probe_macao_history_records.py`
- `tests_Norway_history_records.py` -> `probe_norway_history_records.py`
- `tests_PC28_history_records.py` -> `probe_pc28_history_records.py`
- `tests_wss.py` -> `probe_wss.py`

Delete only the untracked `tests/tests_PC28_crawler.py` draft.

### Historical Documentation and Recovery Evidence

- Move current `docs/superpowers/plans/` and `docs/superpowers/specs/` history
  into `docs/archive/superpowers/` after retaining this active hygiene design
  until the work is complete.
- Move `docs/2026-07-10-session-handoff.md` to `docs/archive/handoffs/` and
  `docs/2026-07-18-runtime-streaks-three-doors-design.md` to
  `docs/archive/designs/`.
- Move the tracked recovery data from `data/` and reusable recovery source
  samples from `archive/` into `docs/archive/recovery/` with descriptive
  subdirectories.
- Move `.superpowers/sdd/` reports and patch artifacts into the recovery
  archive and its reusable scripts into `tools/diagnostics/recovery/`.

Temporary capture directories and files inside the old `archive/` directory
(`tmp_*`, `.playwright-mcp`, logs, and one-off request/result dumps) are
deleted rather than archived. The old `archive/` directory is removed once it
is empty.

### Generated Outputs

Delete `.codex_recovery/`, `build/`, `summary_check/`, `.pytest_cache/`, and
all repository `__pycache__/` directories. In `dist/`, retain only the latest
user installer (`StarTrace-1.99.8.exe`) and remove earlier installers and all
generated archives. These paths remain ignored for future builds.

### Documentation and Ignore Policy

- Rewrite `README.md` for the current application purpose, Windows/Python
  environment, installation, user/admin runs, tests, user build, release flow,
  directory map, and key module roles.
- Add `docs/README.md` as an index to current documents and the historical
  archive. Update `docs/release-packaging.md` to use `<version>` placeholders
  rather than obsolete `1.97.0` examples.
- Replace `.gitignore` with concise, explicit rules for Python caches, virtual
  environments, logs, local data/configuration/secrets, OS files, notebook
  checkpoints, packaging outputs, and project-specific temporary artifacts.
  Do not globally ignore `*.json`, because `latest.json` and legitimate
  tracked JSON inputs are repository files.

## Safety and Error Handling

- Every move uses `git mv` for tracked files, preserving history where Git can
  detect it.
- Repoint imports before removing the old tool paths, then run the focused
  tests that import them.
- If a directory still contains a non-temporary file after migration, stop and
  classify it rather than deleting it.
- Validate the credential file only by path and Git tracking state; never print
  its content or add it to documentation.

## Validation

1. Run `python -m compileall -q app tools`.
2. Run `python -m pytest tests -q`.
3. Run `git diff --check`.
4. Verify representative generated paths with `git check-ignore -v`.
5. Inspect `git status --short --ignored` and confirm that only intentional
   source/documentation moves and edits are tracked, while build/cache/local
   outputs are ignored.
6. Verify `README.md` commands and the user build command still name the
   supported entry points.

## Out of Scope

- No production behavior, GUI, betting, crawler, or packaging logic changes.
- No forced `src/` package migration.
- No deletion of current application code, active automated tests, or retained
  recovery evidence.
