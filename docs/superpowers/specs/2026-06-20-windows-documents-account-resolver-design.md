# Windows Documents Account Resolver Design

## Goal

Make account database auto-location continue working when a Windows user has moved their `Documents` folder to another drive, and make diagnostics show the real resolved config root instead of a stale hardcoded home-directory path.

## Problem

`app/services/account_resolver.py` currently mixes dynamic Windows `Documents` lookup with a hardcoded default of `Path.home() / "Documents" / "TencentCloudChat" / "Config"`.

That creates three problems:

1. The constructor default still points at the home-drive `Documents` path even when Windows has redirected `Documents` elsewhere.
2. Candidate config roots can include the stale home-drive path early enough to make diagnostics confusing.
3. Diagnostic output may suggest the wrong root path during troubleshooting, even if Windows would resolve a different `Documents` location.

## Requirements

### Functional

1. Default config-root resolution must prefer the Windows actual `Documents` location on Windows systems.
2. Account auto-location must still work when `Documents` has been moved to another drive.
3. Diagnostics must report the actual chosen config root.
4. Candidate roots must preserve backward-compatible fallbacks when Windows APIs do not provide a usable location.

### Non-Functional

1. Resolution logic should live in one place so default values, candidate roots, and diagnostics cannot drift apart.
2. The change should remain safe on non-Windows systems.
3. Tests must cover both redirected-Documents and fallback behavior.

## Approach Options

### Option 1: Centralized Documents resolver

Introduce a single helper that returns ordered `Documents` candidates, preferring Windows registry and Shell API results before legacy home-based fallbacks. Build the default config root and candidate config-root list from that helper.

Why this is recommended:

- One source of truth keeps constructor defaults, runtime lookup, and diagnostics aligned.
- The fallback order is explicit and testable.
- Future adjustments only need to happen in one place.

### Option 2: Dynamic default only

Only change `DEFAULT_CONFIG_ROOT` to use a dynamic Windows lookup and leave `_candidate_config_roots()` mostly unchanged.

Why this is weaker:

- Runtime lookup and default initialization can still diverge.
- Diagnostics may still include stale paths prominently.

### Option 3: Keep hardcoded home `Documents` as a primary fallback

Retain `Path.home() / "Documents"` as an early or equal-priority candidate while adding dynamic Windows lookup ahead of it.

Why this is rejected:

- It preserves the misleading path shape we are trying to eliminate.
- It makes troubleshooting harder because the stale path remains visually dominant.

## Design

### 1. Canonical Documents resolution

Add a helper that returns an ordered, deduplicated list of `Documents` directories:

1. Windows registry `User Shell Folders\\Personal`
2. Windows Shell API `SHGetFolderPathW(CSIDL_PERSONAL)`
3. `Path.home() / "Documents"`
4. `Path.home() / "OneDrive" / "Documents"`

Rules:

- On non-Windows, only the generic home-based fallbacks are relevant.
- Empty and duplicate paths are removed case-insensitively.
- Registry and Shell API candidates come first because they reflect the system-configured location.

### 2. Config-root derivation

Build config roots by appending `TencentCloudChat/Config` to each ordered `Documents` candidate.

The constructor default for `AccountResolver.config_root` should no longer rely on a module-level `DEFAULT_CONFIG_ROOT` that was baked from `Path.home() / "Documents"` during import. Instead, the constructor should resolve a dynamic default when no explicit `config_root` is provided.

### 3. Runtime selection

`_candidate_config_roots()` should be generated from the same canonical helper used by the constructor default. `_select_config_root()` continues to prefer the first existing path, but if none exist it returns the first canonical root so diagnostics still reflect the best current guess.

### 4. Diagnostics

`ResolveDiagnostic.config_root` should continue to show the selected root, but after this change that value will be based on the real Windows `Documents` location when available.

This means a user who moved `Documents` to `D:\Users\Name\Documents` should see a corresponding `D:\...\TencentCloudChat\Config` path in diagnostics rather than a stale `C:\Users\Name\Documents\...` default.

## Testing

Add focused tests for `AccountResolver` covering:

1. Dynamic default config root uses redirected Windows `Documents`.
2. Candidate config roots prioritize redirected Windows `Documents`.
3. Runtime selection picks the redirected existing config root.
4. When Windows-specific lookups are unavailable, the legacy home-based fallback still appears.

Tests should isolate path resolution with monkeypatching rather than depending on the host machine's real profile configuration.

## Files In Scope

- `app/services/account_resolver.py`
- `tests/test_account_resolver.py` (new)

## Out of Scope

- Changing shared-preferences path resolution
- Refactoring unrelated account parsing logic
- UI wording changes outside the diagnostic path values
