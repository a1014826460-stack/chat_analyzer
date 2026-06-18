from __future__ import annotations

from pathlib import Path


def test_prepare_windows_update_script_contains_wait_replace_and_restart(tmp_path: Path) -> None:
    from app.services.update_installer import prepare_windows_update_script

    current_exe = tmp_path / "StarTrace.exe"
    staged_exe = tmp_path / "StarTrace-1.98.0.exe"
    script_path = tmp_path / "install-update.cmd"
    current_exe.write_bytes(b"old")
    staged_exe.write_bytes(b"new")

    result = prepare_windows_update_script(
        current_exe=current_exe,
        staged_exe=staged_exe,
        script_path=script_path,
        pid=1234,
    )

    assert result == script_path
    content = script_path.read_text(encoding="utf-8")
    assert "tasklist /FI \"PID eq 1234\"" in content
    assert f'copy /Y "{staged_exe}" "{current_exe}"' in content
    assert f'start "" "{current_exe}"' in content
    assert "del \"%~f0\"" in content


def test_schedule_update_install_dry_run_returns_script_without_launching(tmp_path: Path) -> None:
    from app.services.update_installer import schedule_update_install

    current_exe = tmp_path / "StarTrace.exe"
    staged_exe = tmp_path / "StarTrace-1.98.0.exe"
    current_exe.write_bytes(b"old")
    staged_exe.write_bytes(b"new")

    script_path = schedule_update_install(
        current_exe=current_exe,
        staged_exe=staged_exe,
        pid=1234,
        dry_run=True,
    )

    assert script_path.exists()
    assert script_path.suffix == ".cmd"
