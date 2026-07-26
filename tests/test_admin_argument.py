from __future__ import annotations

import pytest


def test_normal_source_launcher_rejects_admin_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import _parse_args

    monkeypatch.setattr("sys.argv", ["main.py", "--admin"])
    with pytest.raises(SystemExit):
        _parse_args()
