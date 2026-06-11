# StarTrace Chat Analyzer

Recovered desktop application for loading chat logs, filtering blocked users, and analyzing betting-style messages.

## Environment

Create or refresh the local virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Run the application:

```powershell
.\.venv\Scripts\python.exe app\main.py --admin --debug
```

## Build

User build:

```powershell
build.bat
```

Admin build:

```powershell
build_admin.bat
```

Both wrappers call `tools/build.py`, which packages `app/main.py` with PyInstaller and includes `assets/favicon.ico`.

## Recovery Notes

- Core application sources were restored from `.codex_recovery/recovered_src/decompiled`.
- The current project environment has been rebuilt under `.venv`.
- Some non-runtime docs or tooling assets outside `app/` may still need manual restoration if you have an older source backup.
