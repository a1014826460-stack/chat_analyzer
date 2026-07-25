import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import win32gui, win32process

# Find wq_v2 process
import subprocess
result = subprocess.run(['tasklist', '/fi', 'IMAGENAME eq wq_v2.exe', '/fo', 'csv', '/nh'], capture_output=True, text=True)
print("wq_v2 processes:", result.stdout.strip())

# Get PID
lines = result.stdout.strip().split('\n')
target_pid = None
for line in lines:
    parts = line.replace('"', '').split(',')
    if len(parts) >= 2:
        target_pid = int(parts[1])
        break

if not target_pid:
    print("wq_v2 not running!")
    exit()

print(f"Target PID: {target_pid}")

# Find windows
results = []
def enum_cb(hwnd, _):
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    title = win32gui.GetWindowText(hwnd)
    cls = win32gui.GetClassName(hwnd)
    rect = win32gui.GetWindowRect(hwnd)
    visible = win32gui.IsWindowVisible(hwnd)
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    results.append((hwnd, title, cls, visible, w, h, pid))

win32gui.EnumWindows(enum_cb, None)

# Show windows for wq_v2
wq_windows = [r for r in results if r[6] == target_pid]
print(f"\nWindows for PID {target_pid}:")
for hwnd, title, cls, visible, w, h, _ in wq_windows:
    print(f"  hwnd={hwnd:#010x}, class='{cls}', visible={visible}, size={w}x{h}, title='{title[:80]}'")

# Also show ALL windows with "Messager" or "Su" in title
print("\nSearching for 'Messager' or 'Su' windows:")
for hwnd, title, cls, visible, w, h, pid in results:
    if 'su' in title.lower() or 'messager' in title.lower():
        print(f"  hwnd={hwnd:#010x}, pid={pid}, class='{cls}', visible={visible}, size={w}x{h}, title='{title[:80]}'")
