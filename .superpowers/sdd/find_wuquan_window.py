"""Find WuQuan window and test UI automation."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import win32gui
import win32con

# Find all visible windows
results = []

def enum_cb(hwnd, _):
    if win32gui.IsWindowVisible(hwnd):
        title = win32gui.GetWindowText(hwnd)
        cls = win32gui.GetClassName(hwnd)
        rect = win32gui.GetWindowRect(hwnd)
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        if title and w > 300 and h > 300:
            results.append((hwnd, title, cls, rect))

win32gui.EnumWindows(enum_cb, None)

print("=== Visible windows (>300x300) ===")
for hwnd, title, cls, rect in results:
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    print(f"  hwnd={hwnd:#x}, class='{cls}', size={w}x{h}, title='{title[:80]}'")

# Try to find Flutter window specifically
print("\n=== Searching for Flutter/WuQuan windows ===")
for hwnd, title, cls, rect in results:
    if any(k in title.lower() or k in cls.lower()
           for k in ['wu', 'flutter', 'wq', 'chat', 'tencent']):
        print(f"  MATCH: hwnd={hwnd:#x}, class='{cls}', title='{title[:80]}'")

# If no match found, show ALL windows
if not any(any(k in t.lower() or k in c.lower() for k in ['wu', 'flutter', 'wq', 'chat', 'tencent'])
           for _, t, c, _ in results):
    print("\n=== All windows ===")
    for hwnd, title, cls, rect in results:
        print(f"  hwnd={hwnd:#x}, class='{cls}', title='{title[:80]}'")
