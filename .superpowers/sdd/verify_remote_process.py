"""Verify wq_v2.exe process info for remote injection."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import ctypes, ctypes.wintypes
from ctypes import wintypes

kernel32 = ctypes.windll.kernel32
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.c_void_p),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", wintypes.HMODULE),
        ("szModule", ctypes.c_wchar * 256),
        ("szExePath", ctypes.c_wchar * 260),
    ]

# Find wq_v2.exe
snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
if snapshot == INVALID_HANDLE_VALUE:
    print("Failed to create process snapshot")
    exit(1)

class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]

pe = PROCESSENTRY32W()
pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)

target_pid = None
if kernel32.Process32FirstW(snapshot, ctypes.byref(pe)):
    while True:
        name = pe.szExeFile
        if 'wq_v2' in name or 'Su Messager' in name:
            target_pid = pe.th32ProcessID
            print(f"Found: {name} (PID={target_pid})")
        if not kernel32.Process32NextW(snapshot, ctypes.byref(pe)):
            break
kernel32.CloseHandle(snapshot)

if target_pid is None:
    print("wq_v2.exe not found!")
    exit(1)

# Open process
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_WRITE = 0x0020
PROCESS_CREATE_THREAD = 0x0002

hProcess = kernel32.OpenProcess(
    PROCESS_QUERY_INFORMATION | PROCESS_VM_READ | PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_CREATE_THREAD,
    False, target_pid
)
if not hProcess:
    print(f"OpenProcess failed: {kernel32.GetLastError()}")
    # Try with lower privilege
    hProcess = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ | PROCESS_VM_OPERATION | PROCESS_VM_WRITE, False, target_pid)
    if not hProcess:
        print(f"OpenProcess (lower) failed: {kernel32.GetLastError()}")
        print("Need admin privileges to open wq_v2.exe")
        exit(1)
print(f"Opened process: handle={hex(hProcess)}")

# Find ImSDK.dll in remote process
snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPPROCESS, target_pid)
if snapshot == INVALID_HANDLE_VALUE:
    print(f"Module snapshot failed: {kernel32.GetLastError()}")
    kernel32.CloseHandle(hProcess)
    exit(1)

me = MODULEENTRY32W()
me.dwSize = ctypes.sizeof(MODULEENTRY32W)

imsdk_base = None
if kernel32.Module32FirstW(snapshot, ctypes.byref(me)):
    while True:
        if 'ImSDK' in me.szModule or 'imsdk' in me.szModule.lower():
            imsdk_base = me.modBaseAddr
            print(f"ImSDK.dll in wq_v2.exe:")
            print(f"  base: {hex(imsdk_base) if imsdk_base else 'NONE'}")
            print(f"  size: {me.modBaseSize}")
            print(f"  path: {me.szExePath}")
            break
        if not kernel32.Module32NextW(snapshot, ctypes.byref(me)):
            break
kernel32.CloseHandle(snapshot)

if imsdk_base is None:
    print("ImSDK.dll not found in wq_v2.exe modules!")
    kernel32.CloseHandle(hProcess)
    exit(1)

# Compare with our process
our_dll = ctypes.CDLL(r'd:\pythonProject\outsource\chat_analyzer\WuQuan\ImSDK.dll')
our_base = our_dll._handle
our_func = ctypes.cast(our_dll.TIMMsgSendMessage, ctypes.c_void_p).value
rva = our_func - our_base

print(f"\nOur process ImSDK base: {hex(our_base)}")
print(f"Remote process ImSDK base: {hex(imsdk_base)}")
print(f"TIMMsgSendMessage RVA: {hex(rva)}")
print(f"TIMMsgSendMessage in remote: {hex(imsdk_base + rva)}")
print(f"Same base? {'YES' if our_base == imsdk_base else 'NO (different!)'}")

kernel32.CloseHandle(hProcess)
print("\nVerification complete!")
