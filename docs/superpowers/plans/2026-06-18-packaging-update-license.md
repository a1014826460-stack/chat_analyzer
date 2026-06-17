# Packaging Update License Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the first working phase of the selected packaging/update/license design: asymmetric offline licenses, signed CDN update manifests, version metadata, and release artifact helpers.

**Architecture:** Keep PyInstaller as the packaging entry and add small focused services for signing, license verification, and update manifest verification. User builds contain only public keys; admin signing requires an injected private key from environment or release secrets. Commercial executable protection remains a release-stage step documented and wired into release tooling rather than implemented as a bundled third-party tool.

**Tech Stack:** Python 3, PySide6, PyCryptodome Ed25519, PyInstaller, pytest.

---

## File Structure

- Modify `app/services/license_service.py`: replace symmetric activation-code verification with Ed25519 signed payload verification while keeping the existing UI-facing API.
- Create `app/services/signing_service.py`: canonical JSON, base64url helpers, Ed25519 signing and verification primitives shared by license and update code.
- Create `app/services/update_service.py`: signed manifest verification, version comparison, SHA-256 helpers, and update check result models.
- Modify `app/build_config.py`: expose version, edition, update URLs, and public keys as central build metadata.
- Modify `tools/build.py`: use versioned artifact names and pass edition/version consistently.
- Create `tools/release_manifest.py`: generate signed static CDN manifests for built artifacts.
- Create `docs/release-packaging.md`: release checklist including code signing and user-edition protector steps.
- Create `tests/test_license_signing.py`: asymmetric activation and offline license behavior.
- Create `tests/test_update_service.py`: manifest verification and artifact hash behavior.

## Task 1: Shared Signing Primitives

**Files:**
- Create: `app/services/signing_service.py`
- Test: `tests/test_license_signing.py`

- [ ] **Step 1: Write failing tests for canonical signing**

Add tests that generate an Ed25519 key pair, sign a payload, verify it, and reject tampering.

- [ ] **Step 2: Run tests and verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_license_signing.py -q`

Expected: FAIL because `app.services.signing_service` does not exist.

- [ ] **Step 3: Implement signing primitives**

Add canonical JSON, base64url encode/decode, Ed25519 sign, Ed25519 verify, and token encode/decode helpers.

- [ ] **Step 4: Run tests and verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_license_signing.py -q`

Expected: PASS for signing primitive tests.

## Task 2: Asymmetric Offline License Service

**Files:**
- Modify: `app/services/license_service.py`
- Test: `tests/test_license_signing.py`

- [ ] **Step 1: Write failing tests for admin-generated user activation**

Add tests that create `LicenseService(private_key_pem=..., public_key_pem=...)`, generate an activation code for a machine, activate it, and verify the saved signed license works offline.

- [ ] **Step 2: Run tests and verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_license_signing.py -q`

Expected: FAIL because the current implementation still uses HMAC.

- [ ] **Step 3: Implement asymmetric license payloads**

Update `LicenseService.generate_key`, `verify_key`, `activate`, `load_license`, and `is_activated` to use signed payload tokens while preserving existing method names used by the UI.

- [ ] **Step 4: Run tests and verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_license_signing.py -q`

Expected: PASS.

## Task 3: Signed Update Manifest Service

**Files:**
- Create: `app/services/update_service.py`
- Test: `tests/test_update_service.py`

- [ ] **Step 1: Write failing tests for manifest verification**

Add tests that accept a signed manifest, reject tampered manifest fields, compare versions, and verify downloaded file SHA-256.

- [ ] **Step 2: Run tests and verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_update_service.py -q`

Expected: FAIL because `app.services.update_service` does not exist.

- [ ] **Step 3: Implement update service**

Add `UpdateManifest`, `UpdateCheckResult`, manifest signing helper, verifier, version comparison, and file hash verification.

- [ ] **Step 4: Run tests and verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_update_service.py -q`

Expected: PASS.

## Task 4: Build Metadata and Release Helpers

**Files:**
- Modify: `app/build_config.py`
- Modify: `tools/build.py`
- Create: `tools/release_manifest.py`
- Create: `docs/release-packaging.md`
- Test: `tests/test_update_service.py`

- [ ] **Step 1: Write failing tests for build metadata usage**

Add tests that assert generated manifest payloads include channel, version, size, SHA-256, URL, and signature.

- [ ] **Step 2: Run tests and verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_update_service.py -q`

Expected: FAIL because manifest generation helper is missing.

- [ ] **Step 3: Implement metadata and helper tooling**

Add central version constants, versioned build names, manifest generation CLI, and release documentation for protector/code-sign/CDN upload steps.

- [ ] **Step 4: Run targeted tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_license_signing.py tests/test_update_service.py -q`

Expected: PASS.

## Task 5: Integration Verification

**Files:**
- Modify as needed based on failures only.

- [ ] **Step 1: Run existing focused test suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_source_recovery.py -q`

Expected: PASS, or report pre-existing failures if unrelated to the new services.

- [ ] **Step 2: Run a build command smoke check without building**

Run: `.\.venv\Scripts\python.exe tools/build.py --help`

Expected: command prints help and exits 0.

- [ ] **Step 3: Review changed files**

Run: `git diff -- app/services/license_service.py app/services/signing_service.py app/services/update_service.py app/build_config.py tools/build.py tools/release_manifest.py docs/release-packaging.md tests/test_license_signing.py tests/test_update_service.py`

Expected: diff is limited to this feature and does not revert unrelated user changes.
