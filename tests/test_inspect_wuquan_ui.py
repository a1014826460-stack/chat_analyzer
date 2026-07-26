from __future__ import annotations

from pathlib import Path


def test_inspect_wuquan_ui_script_exists_and_documents_usage():
    path = Path("tools/diagnostics/inspect_wuquan_ui.py")

    assert path.exists()
    source = path.read_text(encoding="utf-8")
    assert "--group-id" in source
    assert "--max-depth" in source
    assert "UI Automation" in source
    assert "WuQuan UI Inspection" in source


def test_window_ranking_prefers_normal_flutter_window_over_offscreen_and_ime():
    from tools.diagnostics.inspect_wuquan_ui import WindowInfo, rank_window_candidate

    offscreen_main = WindowInfo(
        hwnd=1,
        pid=10,
        process_name="wq_v2.exe",
        title="Su Messager",
        class_name="FLUTTER_RUNNER_WIN32_WINDOW",
        rect=(-25600, -25600, -25441, -25573),
        visible=True,
    )
    ime = WindowInfo(
        hwnd=2,
        pid=10,
        process_name="wq_v2.exe",
        title="Default IME",
        class_name="IME",
        rect=(0, 0, 0, 0),
        visible=True,
    )
    normal_main = WindowInfo(
        hwnd=3,
        pid=10,
        process_name="wq_v2.exe",
        title="Su Messager",
        class_name="FLUTTER_RUNNER_WIN32_WINDOW",
        rect=(100, 100, 1300, 900),
        visible=True,
    )

    assert rank_window_candidate(normal_main) < rank_window_candidate(offscreen_main)
    assert rank_window_candidate(normal_main) < rank_window_candidate(ime)


def test_uia_dump_does_not_use_missing_pywinauto_ancestors_method():
    source = Path("tools/diagnostics/inspect_wuquan_ui.py").read_text(encoding="utf-8")

    assert ".ancestors(" not in source
