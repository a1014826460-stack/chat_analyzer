# StarTrace Release Packaging

## Build

User edition:

```powershell
.\.venv\Scripts\python.exe tools\build.py --clean
```

Admin edition:

```powershell
.\.venv\Scripts\python.exe tools\build.py --admin --clean
```

Artifacts are versioned from `app/build_config.py` or the `STARTRACE_VERSION` environment variable.

## Keys

- User edition runtime must contain only `STARTRACE_LICENSE_PUBLIC_KEY_PEM` and `STARTRACE_UPDATE_PUBLIC_KEY_PEM`.
- Admin signing flow requires `STARTRACE_LICENSE_PRIVATE_KEY_PEM`.
- Release manifest generation requires an update private key PEM file.

Keep private keys out of the repository and load them from environment variables or local secret files.

## Code Signing and Protection

Recommended release order for the user edition:

1. Build the user exe with PyInstaller.
2. Apply the selected protector to the user exe.
3. Code-sign the final protected exe.
4. Compute hash and generate the release manifest.

Recommended release order for the admin edition:

1. Build the admin exe with PyInstaller.
2. Code-sign the exe.
3. Generate the release manifest if admin auto-update is enabled.

## Generate Update Manifest Token

```powershell
.\.venv\Scripts\python.exe tools\release_manifest.py `
  --artifact dist\StarTrace-1.97.0.exe `
  --channel user `
  --version 1.97.0 `
  --base-url https://cdn.example.com/startrace/user `
  --private-key C:\keys\update_private.pem `
  --notes "Bug fixes and license hardening"
```

The script prints a signed token. Store the decoded payload plus signature as the `latest.json` CDN content used by the application update check.

## CDN Layout

- `${CDN_BASE_URL}/startrace/user/latest.json`
- `${CDN_BASE_URL}/startrace/user/StarTrace-<version>.exe`
- `${CDN_BASE_URL}/startrace/admin/latest.json`
- `${CDN_BASE_URL}/startrace/admin/StarTrace-Admin-<version>.exe`

## Manual Validation

1. Launch user edition on a clean machine.
2. Activate using an admin-generated code.
3. Restart offline and verify activation persists.
4. Publish a higher-version manifest and verify the client accepts it.
5. Corrupt a downloaded artifact and verify hash validation rejects it.
