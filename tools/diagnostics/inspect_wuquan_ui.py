from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass
class WindowInfo:
    hwnd: int
    pid: int
    process_name: str
    title: str
    class_name: str
    rect: tuple[int, int, int, int]
    visible: bool


def _rect_size(rect: tuple[int, int, int, int]) -> tuple[int, int, int]:
    width = max(0, int(rect[2]) - int(rect[0]))
    height = max(0, int(rect[3]) - int(rect[1]))
    return width, height, width * height


def _looks_offscreen_or_tiny(rect: tuple[int, int, int, int]) -> bool:
    width, height, area = _rect_size(rect)
    if area < 20_000:
        return True
    # Windows often moves minimized Flutter windows to (-32000, -32000) or
    # similar coordinates.  Such handles are real but not useful for UIA/click
    # inspection.
    return int(rect[0]) < -10_000 or int(rect[1]) < -10_000


def rank_window_candidate(window: WindowInfo) -> tuple[int, int, int, int]:
    """Rank real WuQuan main windows before IME/helper/offscreen windows."""
    title_cf = window.title.casefold()
    class_cf = window.class_name.casefold()
    width, height, area = _rect_size(window.rect)
    is_flutter_main = class_cf == "flutter_runner_win32_window"
    helper_title = title_cf in {
        "default ime",
        "sogou_tsf_ui",
        "hintwnd",
        "msctfime ui",
    }
    helper_class = "ime" in class_cf or "tsf" in class_cf
    offscreen_or_tiny = _looks_offscreen_or_tiny(window.rect)
    return (
        0 if is_flutter_main else 1,
        1 if helper_title or helper_class else 0,
        1 if offscreen_or_tiny else 0,
        -area,
    )


def _import_win32():
    try:
        import psutil
        import win32gui
        import win32process
    except Exception as exc:  # pragma: no cover - depends on local Windows env
        raise RuntimeError(
            "需要 pywin32/psutil 才能定位 WuQuan 窗口。请先安装：pip install pywin32 psutil"
        ) from exc
    return psutil, win32gui, win32process


def find_windows(process_name: str, title_keyword: str = "") -> list[WindowInfo]:
    psutil, win32gui, win32process = _import_win32()
    process_name_cf = process_name.casefold().strip()
    title_keyword_cf = title_keyword.casefold().strip()
    result: list[WindowInfo] = []

    def callback(hwnd: int, _lparam: int) -> bool:
        if not win32gui.IsWindow(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd) or ""
        class_name = win32gui.GetClassName(hwnd) or ""
        visible = bool(win32gui.IsWindowVisible(hwnd))
        if not visible and not title:
            return True
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            proc_name = psutil.Process(pid).name()
        except Exception:
            proc_name = ""
        if process_name_cf and proc_name.casefold() != process_name_cf:
            return True
        if title_keyword_cf and title_keyword_cf not in title.casefold():
            return True
        try:
            rect = tuple(int(v) for v in win32gui.GetWindowRect(hwnd))
        except Exception:
            rect = (0, 0, 0, 0)
        result.append(
            WindowInfo(
                hwnd=int(hwnd),
                pid=int(pid),
                process_name=proc_name,
                title=title,
                class_name=class_name,
                rect=rect,  # type: ignore[arg-type]
                visible=visible,
            )
        )
        return True

    win32gui.EnumWindows(callback, 0)
    result.sort(key=rank_window_candidate)
    return result


def dump_win32_children(hwnd: int, max_depth: int) -> list[dict[str, Any]]:
    _psutil, win32gui, _win32process = _import_win32()

    def describe(child_hwnd: int, depth: int) -> dict[str, Any]:
        try:
            rect = tuple(int(v) for v in win32gui.GetWindowRect(child_hwnd))
        except Exception:
            rect = (0, 0, 0, 0)
        item: dict[str, Any] = {
            "depth": depth,
            "hwnd": int(child_hwnd),
            "class_name": win32gui.GetClassName(child_hwnd) or "",
            "title": win32gui.GetWindowText(child_hwnd) or "",
            "visible": bool(win32gui.IsWindowVisible(child_hwnd)),
            "enabled": bool(win32gui.IsWindowEnabled(child_hwnd)),
            "rect": rect,
        }
        return item

    rows: list[dict[str, Any]] = []

    def walk(parent: int, depth: int) -> None:
        if depth > max_depth:
            return
        children: list[int] = []
        win32gui.EnumChildWindows(parent, lambda h, _p: children.append(int(h)) or True, 0)
        for child in children:
            rows.append(describe(child, depth))
            walk(child, depth + 1)

    walk(hwnd, 1)
    return rows


def dump_pywinauto_uia(hwnd: int, max_depth: int) -> tuple[bool, list[str]]:
    """Try UI Automation through pywinauto if it is installed.

    UI Automation is the important check for Flutter apps: if WuQuan exposes
    the group list/input box to UIA, we can build a mostly-background sender.
    If it exposes only one custom pane, we will need a coordinate fallback.
    """
    try:
        from pywinauto import Desktop
    except Exception:
        return False, [
            "pywinauto 未安装，跳过 UI Automation 控件树。",
            "如需完整 UIA 探测，请执行：pip install pywinauto comtypes",
        ]

    lines: list[str] = []
    try:
        wrapper = Desktop(backend="uia").window(handle=hwnd)
        descendants = wrapper.descendants()
    except Exception as exc:
        return False, [f"UI Automation 连接失败: {exc!r}"]

    lines.append(f"UI Automation descendants: {len(descendants)}")
    for ctrl in descendants[:2000]:
        try:
            info = ctrl.element_info
            depth = 1
            rect = info.rectangle
            lines.append(
                "  "
                + "  " * max(depth - 1, 0)
                + f"- control_type={info.control_type!r} "
                + f"name={info.name!r} "
                + f"automation_id={info.automation_id!r} "
                + f"class={info.class_name!r} "
                + f"rect=({rect.left},{rect.top},{rect.right},{rect.bottom})"
            )
        except Exception as exc:
            lines.append(f"  - <读取控件失败: {exc!r}>")
    return True, lines


def print_window_summary(window: WindowInfo) -> None:
    print("WuQuan UI Inspection")
    print("====================")
    print(f"hwnd:          {window.hwnd}")
    print(f"pid:           {window.pid}")
    print(f"process_name:  {window.process_name}")
    print(f"title:         {window.title!r}")
    print(f"class_name:    {window.class_name!r}")
    print(f"visible:       {window.visible}")
    print(f"rect:          {window.rect}")


def print_win32_tree(rows: list[dict[str, Any]], group_id: str) -> None:
    print("\n[Win32 child windows]")
    if not rows:
        print("No Win32 child windows found. This is common for Flutter-rendered windows.")
        return
    for row in rows:
        indent = "  " * int(row["depth"])
        marker = ""
        text = str(row.get("title") or "")
        if group_id and group_id in text:
            marker = "  <-- group-id match"
        print(
            f"{indent}- hwnd={row['hwnd']} class={row['class_name']!r} "
            f"title={text!r} visible={row['visible']} enabled={row['enabled']} "
            f"rect={row['rect']}{marker}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="WuQuan UI Inspection: inspect Win32/UI Automation tree for group chat automation."
    )
    parser.add_argument("--process-name", default="wq_v2.exe", help="WuQuan process name")
    parser.add_argument("--title-keyword", default="", help="optional title keyword filter")
    parser.add_argument("--hwnd", type=int, default=0, help="inspect a specific window handle")
    parser.add_argument("--group-id", default="", help="group id to search in visible UI text, e.g. 207191791")
    parser.add_argument("--max-depth", type=int, default=6, help="max UI tree depth to print")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON for Win32 tree")
    args = parser.parse_args(argv)

    try:
        if args.hwnd:
            windows = [w for w in find_windows("", "") if w.hwnd == int(args.hwnd)]
        else:
            windows = find_windows(args.process_name, args.title_keyword)
    except RuntimeError as exc:
        print(f"FAILED: {exc}")
        return 2

    if not windows:
        print(f"FAILED: 未找到 WuQuan 窗口 process={args.process_name!r} title_keyword={args.title_keyword!r}")
        print("请确认 WuQuan 已启动；如果进程名不是 wq_v2.exe，请用 --process-name 指定。")
        return 1

    window = windows[0]
    print_window_summary(window)
    if len(windows) > 1:
        print(f"\n注意：找到 {len(windows)} 个候选窗口，当前检查第一个。可用 --hwnd 指定。")
        for candidate in windows[1:]:
            print(f"  candidate hwnd={candidate.hwnd} title={candidate.title!r} rect={candidate.rect}")

    rows = dump_win32_children(window.hwnd, max(0, int(args.max_depth)))
    if args.json:
        payload = {"window": asdict(window), "win32_children": rows}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_win32_tree(rows, args.group_id)

    print("\n[UI Automation]")
    ok, lines = dump_pywinauto_uia(window.hwnd, max(0, int(args.max_depth)))
    for line in lines:
        suffix = ""
        if args.group_id and args.group_id in line:
            suffix = "  <-- group-id match"
        print(f"{line}{suffix}")

    print("\n[结论提示]")
    if ok:
        print("如果上面的 UIA 树能看到群号、搜索框、输入框或发送按钮，就可以继续做 UIA 后台自动进群发送。")
        print("如果 UIA 树只有少量 Pane/Custom 控件，看不到文本，则需要走窗口内坐标点击方案。")
    else:
        print("当前没有完整 UIA 数据。先安装 pywinauto/comtypes 后重新运行，可判断是否能后台识别群聊。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
