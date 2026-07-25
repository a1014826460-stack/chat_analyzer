# StarTrace Packaging, Update, License, and Protection Design

## Goal

Package StarTrace as independent Windows executables while keeping the existing PyInstaller-based workflow. The user edition must require activation before normal use, support long-term offline use after activation, and enforce the expiry time encoded by an admin-generated activation code. The admin edition must run without activation and generate user activation codes from machine codes. Online update delivery should use static files or a CDN instead of a custom application server.

## Selected Approach

Use option B: keep PyInstaller as the main packager, but isolate and strengthen the license, update, and protection core. The user edition will be protected after packaging with an executable protector. This keeps the current build model intact while improving the most sensitive parts of the system.

This design intentionally avoids a live license server. Static CDN files are used only for update discovery and binary delivery. User activation and later license checks work offline through signed license data.

## Editions

### User Edition

The user edition is built from the current application entry point with the user runtime hook. It must not expose the admin activation-code generator. On startup, it checks the local signed license before enabling the main application workflow.

If the license is missing, invalid, expired, bound to another machine, or blocked by local time-integrity checks, the application opens the activation page and prevents normal use. After a valid activation code is entered, the application stores the signed license locally and can continue working offline until the signed expiry time.

### Admin Edition

The admin edition is built from the same source tree with the admin runtime hook. It can run without activation and exposes the existing license generator UI. The generator accepts a user-provided machine code, a duration unit, and a duration value, then returns a signed activation code for that machine.

The admin edition contains the private signing key or a protected equivalent. Because a private key in any distributed executable can eventually be extracted by a determined attacker, the admin edition must be distributed only to trusted operators. If admin operators are not trusted, license signing must move to an online service later.

## Packaging

The current `tools/build.py` flow remains the primary build entry:

- User build: `build_user.bat` or `python tools/build.py`.
- Admin build: `build_admin.bat` or `python tools/build.py --admin`.
- Output names should be versioned consistently, for example `StarTrace-1.97.0.exe` and `StarTrace-Admin-1.97.0.exe`.
- The application version should be defined once in source or build metadata and injected into both the UI and update manifest generation.

The user packaging pipeline should be:

1. Build with PyInstaller.
2. Code-sign the unpacked PyInstaller output if required by the protector.
3. Apply the selected executable protector to the user exe.
4. Code-sign the final protected exe.
5. Compute SHA-256 of the final exe.
6. Generate and sign the CDN update manifest.

The admin packaging pipeline should be:

1. Build with PyInstaller.
2. Code-sign the final exe.
3. Compute SHA-256.
4. Generate and sign the admin update manifest if admin auto-update is enabled.

## License Model

Replace the current symmetric HMAC activation-code scheme with asymmetric signing.

The user edition contains only the license public key. The admin edition contains the license private key and uses it to sign activation-code payloads. The user edition verifies signatures with the public key and never needs the signing secret.

Activation-code payload fields:

- `license_id`: unique identifier for the issued license.
- `edition`: expected value `user`.
- `machine_code`: target machine code.
- `issued_at`: signing time.
- `expires_at`: absolute expiry time.
- `duration_value`: selected duration value.
- `duration_unit`: selected duration unit, such as `hours` or `days`.
- `features`: optional feature flags, initially `["standard"]`.
- `schema`: activation payload schema version, initially `1`.

Activation-code format:

```text
base64url(canonical_json_payload).base64url(signature)
```

The signature algorithm should be Ed25519 or RSA-PSS. Ed25519 is preferred because signatures and keys are compact and the verification API is straightforward. The project already depends on `pycryptodome`, but using `cryptography` for Ed25519 is acceptable if dependency size is acceptable after packaging.

## Offline Activation Flow

1. User opens the user edition.
2. The activation page displays the local machine code.
3. User sends the machine code to an admin operator.
4. Admin enters the machine code and duration into the admin edition.
5. Admin sends the activation code back to the user.
6. User pastes the activation code into the user edition.
7. User edition verifies the payload signature, edition, machine code, issue time, and expiry time.
8. User edition saves the signed activation payload and local metadata to `license.json`.
9. Future launches verify the saved signed payload offline.

The saved license must retain the signed payload and signature rather than storing only decoded fields. Local decoded fields can be cached for display, but the signed blob remains the source of truth.

## Time Integrity

Offline licenses rely on the local clock, so the application must keep the existing last-seen timestamp check and make it stricter and clearer.

Rules:

- Store `last_seen_ts` after every successful license check.
- Reject normal use if the current local time is more than five minutes earlier than `last_seen_ts`.
- Reject normal use if `expires_at` is earlier than the current local time.
- Do not require network time, because long-term offline use is a requirement.
- Show a clear user-facing message when clock rollback is detected.

This does not make offline expiry tamper-proof against a fully controlled machine. It raises the cost enough for the lightweight offline model and should be combined with executable protection.

## Update Model

Updates are delivered through static CDN files. The actual CDN host is configured by release settings, and each edition has a separate update channel:

- `${CDN_BASE_URL}/startrace/user/latest.json`
- `${CDN_BASE_URL}/startrace/admin/latest.json`

Manifest fields:

- `schema`: manifest schema version, initially `1`.
- `channel`: `user` or `admin`.
- `version`: latest release version.
- `min_supported_version`: oldest version allowed to continue without forced update.
- `force`: whether the update is mandatory.
- `url`: download URL for the exe package.
- `sha256`: SHA-256 of the final downloadable file.
- `size`: file size in bytes.
- `notes`: short update notes.
- `published_at`: release time.
- `signature`: signature over the canonical manifest fields excluding `signature`.

The application contains only the update public key. The manifest signing private key stays in the release environment and should not be embedded in either user or admin executables.

## Update Flow

1. Application starts normally.
2. A background update check fetches the edition-specific `latest.json`.
3. If the CDN is unavailable, startup continues without update.
4. The application verifies manifest signature before trusting any field.
5. If the manifest version is newer than the current version, the user is prompted unless `force` is true.
6. The new exe is downloaded to a temporary staging path.
7. The downloaded file SHA-256 must match the manifest.
8. A small updater helper is launched.
9. The updater waits for the main process to exit, replaces the old exe, and restarts the app.

Because Windows cannot replace a running exe, the updater must run as a separate process. To keep distribution simple, the updater can be bundled as a small helper executable resource and extracted only during update.

## Error Handling

License errors:

- Invalid format: show a localized "activation code format is invalid" message.
- Invalid signature: show a localized "activation code signature is invalid" message.
- Machine mismatch: show a localized "activation code does not match this machine" message.
- Expired code: show a localized "activation code has expired" message.
- Clock rollback: show a localized "system time is abnormal; restore the correct time and retry" message.

Update errors:

- Manifest unavailable: log and continue silently or show a non-blocking status message.
- Manifest signature invalid: ignore update and log a critical warning.
- Download hash mismatch: delete staged file and show a retryable error.
- Replacement failure: keep the current executable and show a clear restart/manual-download message.

Protection failures:

- Show a short security warning.
- Exit the application.
- Avoid exposing low-level implementation details in user-facing messages.

## Protection Strategy

Protection is layered. No single layer is treated as sufficient.

Required first-stage protections:

- User edition must not include the license private key.
- User edition must not include the admin license generator UI path.
- Manifest signing private key must never be embedded in any packaged application.
- License verification and update verification should be isolated in small modules with narrow interfaces.
- Existing runtime protection checks should be preserved and cleaned up, including readable Chinese messages.

Recommended user-edition hardening:

- Obfuscate or compile the license, update, and protection modules before PyInstaller packaging.
- Apply a commercial executable protector to the final user exe, such as VMProtect, Themida, or Enigma Protector.
- Enable anti-debugging and integrity options conservatively to avoid false positives on normal customer machines.
- Code-sign after protection when the protector requires it.

Optional later hardening:

- Move the license and update verification core to Cython, Nuitka module mode, or a small native extension.
- Add a local integrity hash generated during release.
- Add telemetry-free crash-safe logs for protection failures.

## Data Storage

The existing `JsonStore("license.json")` can remain the storage mechanism. The license state should include:

- `activation_code`: original signed activation code.
- `payload`: decoded payload cache for display.
- `license_id`: cached license id.
- `machine_code`: cached machine code.
- `expires_at`: cached expiry time.
- `activated_at`: local activation time.
- `last_seen_ts`: local last successful license check timestamp.
- `consumed_key_hashes`: local hashes of activation codes already consumed on this machine.

The signed activation code remains authoritative. Cached fields must be refreshed from the verified payload rather than trusted independently.

## Testing

Unit tests should cover:

- Admin generation produces a user activation code accepted by the user verifier.
- User verifier rejects tampered payloads.
- User verifier rejects tampered signatures.
- User verifier rejects machine-code mismatches.
- User verifier rejects expired licenses.
- User verifier accepts saved signed licenses offline.
- Last-seen timestamp rejects clock rollback.
- User build does not expose admin-only UI when activation is required.
- Manifest verifier accepts a signed manifest.
- Manifest verifier rejects tampered fields.
- Hash verification rejects corrupted downloads.

Manual release tests should cover:

- Fresh user install, activation, restart offline.
- Expired user license.
- Clock rollback behavior.
- Optional update, download, replacement, restart.
- Forced update path.
- CDN unavailable path.
- Protected exe launch on a clean Windows machine.

## Rollout Plan

Phase 1 delivers the secure architecture without adding a protector:

- Introduce version metadata.
- Replace HMAC activation with public-key verification.
- Keep admin generation working with the private key.
- Store signed license blobs.
- Add manifest signing and verification.
- Add update check and staged replacement.

Phase 2 adds packaging automation:

- Generate versioned artifact names.
- Generate signed CDN manifests.
- Add hash calculation to release tooling.
- Add release checklist documentation.

Phase 3 adds user-edition hardening:

- Compile or obfuscate sensitive modules.
- Apply the selected executable protector.
- Verify compatibility and false-positive rates.
- Code-sign final protected artifacts.

## Non-Goals

- No live activation server in this design.
- No online revocation list in the first implementation.
- No per-launch network requirement for user license checks.
- No complete guarantee against reverse engineering or system-clock tampering.
- No migration away from PyInstaller in the first implementation.

## Open Decisions Resolved

- Update hosting uses static CDN files.
- First activation can be performed offline through admin-generated activation codes.
- User licenses can be used offline until their signed expiry time.
- PyInstaller remains the primary packager.
- User edition gets additional post-build protection.
- Asymmetric signing replaces embedded HMAC secrets in the user edition.
