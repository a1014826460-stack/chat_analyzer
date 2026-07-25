"""Send message via UI automation in WuQuan (Su Messager) window."""
import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import win32gui
import win32con
import win32process
import win32api

def find_wuquan_window():
    """Find the main Flutter window of wq_v2.exe."""
    # Get PID
    import subprocess
    result = subprocess.run(
        ['tasklist', '/fi', 'IMAGENAME eq wq_v2.exe', '/fo', 'csv', '/nh'],
        capture_output=True, text=True
    )
    for line in result.stdout.strip().split('\n'):
        parts = line.replace('"', '').split(',')
        if len(parts) >= 2:
            target_pid = int(parts[1])
            break
    else:
        return None, None

    # Find main window
    def enum_cb(hwnd, results):
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid != target_pid:
            return
        cls = win32gui.GetClassName(hwnd)
        if cls == 'FLUTTER_RUNNER_WIN32_WINDOW':
            title = win32gui.GetWindowText(hwnd)
            rect = win32gui.GetWindowRect(hwnd)
            w, h = rect[2] - rect[0], rect[3] - rect[1]
            results.append((hwnd, title, w, h, pid))

    results = []
    win32gui.EnumWindows(enum_cb, results)

    # Return the largest window (main window)
    if results:
        results.sort(key=lambda r: r[2] * r[3], reverse=True)
        best = results[0]
        return best[0], target_pid
    return None, None


def send_message(hwnd, text):
    """Send a text message via the WuQuan window."""

    # Step 1: Show and activate the window
    print(f"Activating window {hwnd:#010x}...")
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    time.sleep(0.5)
    win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
    time.sleep(0.5)
    win32gui.SetForegroundWindow(hwnd)
    time.sleep(0.5)

    # Check new window size
    rect = win32gui.GetWindowRect(hwnd)
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    print(f"Window size after maximize: {w}x{h}")

    if w < 300:
        print("Window still too small — may be minimized to tray. Trying ShowWindow...")
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        time.sleep(0.5)
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.5)
        rect = win32gui.GetWindowRect(hwnd)
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        print(f"Window size after show/restore: {w}x{h}")

    # For Flutter, we can't find child text inputs — use keyboard events
    # First, try Ctrl+F to focus search, or just type at window level

    # Click in the center-bottom area (likely message input area)
    if w > 300 and h > 300:
        center_x = rect[0] + w // 2
        bottom_y = rect[1] + h - 50  # Near bottom
        print(f"Clicking at ({center_x}, {bottom_y})...")
        win32api.SetCursorPos((center_x, bottom_y))
        time.sleep(0.3)
        # Simulate left click
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.1)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.3)

    # Type the message using SendInput
    print(f"Typing: '{text}'")
    import ctypes
    from ctypes import wintypes

    # Use SendInput to type each character
    user32 = ctypes.windll.user32

    INPUT_KEYBOARD = 1
    KEYEVENTF_UNICODE = 4
    KEYEVENTF_KEYUP = 2

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [
            ("type", wintypes.DWORD),
            ("ki", KEYBDINPUT),
        ]

    # Type each character as Unicode
    inputs = []
    for ch in text:
        # Key down
        down = INPUT()
        down.type = INPUT_KEYBOARD
        down.ki.wVk = 0
        down.ki.wScan = ord(ch)
        down.ki.dwFlags = KEYEVENTF_UNICODE
        down.ki.time = 0
        down.ki.dwExtraInfo = None
        inputs.append(down)

        # Key up
        up = INPUT()
        up.type = INPUT_KEYBOARD
        up.ki.wVk = 0
        up.ki.wScan = ord(ch)
        up.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
        up.ki.time = 0
        up.ki.dwExtraInfo = None
        inputs.append(up)

    # Send all inputs
    input_array = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), input_array, ctypes.sizeof(INPUT))
    print(f"Sent {len(text)} characters")

    # Press Enter to send
    time.sleep(0.5)
    print("Pressing Enter...")
    enter_down = INPUT()
    enter_down.type = INPUT_KEYBOARD
    enter_down.ki.wVk = win32con.VK_RETURN
    enter_down.ki.dwFlags = 0
    enter_up = INPUT()
    enter_up.type = INPUT_KEYBOARD
    enter_up.ki.wVk = win32con.VK_RETURN
    enter_up.ki.dwFlags = KEYEVENTF_KEYUP

    enter_inputs = (INPUT * 2)(enter_down, enter_up)
    user32.SendInput(2, enter_inputs, ctypes.sizeof(INPUT))
    print("Enter sent!")


def main():
    hwnd, pid = find_wuquan_window()
    if hwnd is None:
        print("WuQuan window not found!")
        return

    print(f"Found WuQuan window: hwnd={hwnd:#010x}, pid={pid}")

    # Send a test message
    test_msg = "Automated test from Python"
    send_message(hwnd, test_msg)

    print("\nDone! Check the WuQuan app to see if the message was sent.")


if __name__ == "__main__":
    main()
