from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


def prepare_windows_update_script(
    *,
    current_exe: Path,
    staged_exe: Path,
    script_path: Path,
    pid: int,
) -> Path:
    current = current_exe.resolve()
    staged = staged_exe.resolve()
    script_path.parent.mkdir(parents=True, exist_ok=True)
    content = f"""@echo off
setlocal
set PID={pid}
set STAGED="{staged}"
set TARGET="{current}"
:wait_loop
tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL
if not errorlevel 1 (
  timeout /T 1 /NOBREAK >NUL
  goto wait_loop
)
copy /Y "{staged}" "{current}" >NUL
if errorlevel 1 (
  echo Failed to install update.
  pause
  exit /B 1
)
start "" "{current}"
del "%~f0"
"""
    script_path.write_text(content, encoding="utf-8")
    return script_path


def schedule_update_install(
    *,
    current_exe: Path,
    staged_exe: Path,
    pid: int | None = None,
    dry_run: bool = False,
) -> Path:
    """Launch the downloaded setup.exe installer (setup-installer mode).

    The bare-exe swap is no longer used: releases are packaged as setup.exe
    and the installer drives the replacement during the setup wizard.
    """
    del current_exe, pid
    if dry_run:
        return Path(str(staged_exe))
    subprocess.Popen([str(staged_exe)], shell=True)
    return Path(str(staged_exe))
