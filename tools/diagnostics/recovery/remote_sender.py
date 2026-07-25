"""Send IM messages via remote thread injection into wq_v2.exe.

Calls TIMMsgSendMessage inside the WuQuan process to reuse its existing
IM login session — no new TIMLogin, no kick-off.
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import ctypes, ctypes.wintypes, struct, time, json
from ctypes import wintypes

kernel32 = ctypes.windll.kernel32

# Set up proper x64 argtypes for key functions
kernel32.VirtualAllocEx.argtypes = [
    wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t,
    wintypes.DWORD, wintypes.DWORD,
]
kernel32.VirtualAllocEx.restype = wintypes.LPVOID

kernel32.WriteProcessMemory.argtypes = [
    wintypes.HANDLE, wintypes.LPVOID, wintypes.LPCVOID,
    ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t),
]
kernel32.WriteProcessMemory.restype = wintypes.BOOL

kernel32.ReadProcessMemory.argtypes = [
    wintypes.HANDLE, wintypes.LPCVOID, wintypes.LPVOID,
    ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t),
]
kernel32.ReadProcessMemory.restype = wintypes.BOOL

kernel32.CreateRemoteThread.argtypes = [
    wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t,
    wintypes.LPVOID, wintypes.LPVOID, wintypes.DWORD,
    wintypes.LPDWORD,
]
kernel32.CreateRemoteThread.restype = wintypes.HANDLE

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PROCESS_ALL_ACCESS = 0x1F0FFF
PROCESS_VM_OP = 0x0008
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_READ = 0x0010
PROCESS_CREATE_THREAD = 0x0002
PROCESS_QUERY_INFO = 0x0400
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_EXECUTE_READWRITE = 0x40
PAGE_READWRITE = 0x04
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPPROCESS = 0x00000002
INFINITE = 0xFFFFFFFF

# ---------------------------------------------------------------------------
# x64 trampoline shellcode
# ---------------------------------------------------------------------------
# This shellcode receives a struct pointer in RCX and calls TIMMsgSendMessage.
# Struct layout (8-byte fields):
#   +0x00: char*   conv_id
#   +0x08: int64   conv_type
#   +0x10: char*   json_msg_param
#   +0x18: char*   msg_id_buffer (256 bytes)
#   +0x20: void*   callback (NULL)
#   +0x28: void*   user_data (NULL)
#   +0x30: void*   target_func (address of TIMMsgSendMessage in remote process)
SHELLCODE = bytes([
    0x53,                   # push rbx
    0x48, 0x83, 0xEC, 0x20, # sub rsp, 0x20
    0x48, 0x89, 0xCB,       # mov rbx, rcx
    # Load register args
    0x48, 0x8B, 0x0B,       # mov rcx, [rbx]         ; conv_id
    0x48, 0x8B, 0x53, 0x08, # mov rdx, [rbx+8]       ; conv_type
    0x4C, 0x8B, 0x43, 0x10, # mov r8,  [rbx+16]      ; json_msg_param
    0x4C, 0x8B, 0x4B, 0x18, # mov r9,  [rbx+24]      ; msg_id_buffer
    # Stack args
    0x48, 0x8B, 0x43, 0x28, # mov rax, [rbx+40]      ; user_data
    0x48, 0x89, 0x44, 0x24, 0x28, # mov [rsp+0x28], rax
    0x48, 0x8B, 0x43, 0x20, # mov rax, [rbx+32]      ; callback
    0x48, 0x89, 0x44, 0x24, 0x20, # mov [rsp+0x20], rax
    # Call target
    0x48, 0x8B, 0x43, 0x30, # mov rax, [rbx+48]      ; target_func
    0xFF, 0xD0,             # call rax
    # Cleanup & return
    0x48, 0x83, 0xC4, 0x20, # add rsp, 0x20
    0x5B,                   # pop rbx
    0xC3,                   # ret
])

# ---------------------------------------------------------------------------
# Process finder
# ---------------------------------------------------------------------------

def find_wq_v2_pid() -> int | None:
    """Return PID of wq_v2.exe or None."""
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)

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
            if 'wq_v2' in pe.szExeFile:
                target_pid = pe.th32ProcessID
                break
            if not kernel32.Process32NextW(snapshot, ctypes.byref(pe)):
                break
    kernel32.CloseHandle(snapshot)
    return target_pid


def find_module_base(pid: int, module_name: str) -> int | None:
    """Return base address of a module in the remote process."""
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPPROCESS, pid)

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
    me = MODULEENTRY32W()
    me.dwSize = ctypes.sizeof(MODULEENTRY32W)
    base = None
    if kernel32.Module32FirstW(snapshot, ctypes.byref(me)):
        while True:
            if module_name.lower() in me.szModule.lower():
                base = me.modBaseAddr
                break
            if not kernel32.Module32NextW(snapshot, ctypes.byref(me)):
                break
    kernel32.CloseHandle(snapshot)
    return base


# ---------------------------------------------------------------------------
# Remote thread injector
# ---------------------------------------------------------------------------

class RemoteIMSender:
    """Send messages through wq_v2.exe's existing IM session."""

    TIMMSG_RVA = 0x3EA473  # RVA of TIMMsgSendMessage in ImSDK.dll

    def __init__(self, pid: int | None = None) -> None:
        self._pid = pid or find_wq_v2_pid()
        if self._pid is None:
            raise RuntimeError("wq_v2.exe not found")
        self._hProcess = self._open_process()
        imsdk_base = find_module_base(self._pid, "ImSDK.dll")
        if imsdk_base is None:
            raise RuntimeError("ImSDK.dll not found in wq_v2.exe")
        self._func_addr = imsdk_base + self.TIMMSG_RVA

    def _open_process(self) -> int:
        desired = PROCESS_VM_OP | PROCESS_VM_WRITE | PROCESS_VM_READ | PROCESS_CREATE_THREAD | PROCESS_QUERY_INFO
        h = kernel32.OpenProcess(desired, False, self._pid)
        if not h:
            raise OSError(f"OpenProcess failed: {kernel32.GetLastError()}")
        return h

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_group_message(self, group_id: str, text: str) -> bool:
        """Send a text message to a group. Returns True on success."""
        return self._send(group_id, 2, text)

    def send_c2c_message(self, user_id: str, text: str) -> bool:
        """Send a C2C text message."""
        return self._send(user_id, 1, text)

    def close(self) -> None:
        if self._hProcess:
            kernel32.CloseHandle(self._hProcess)
            self._hProcess = 0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _send(self, target_id: str, conv_type: int, text: str) -> bool:
        msg_json = json.dumps({
            "message_elem_array": [
                {"elem_type": 0, "text_elem_content": text}
            ],
        }, ensure_ascii=False)

        # Prepare strings in remote process
        remote_target = self._write_string(target_id)
        remote_json = self._write_string(msg_json)
        remote_buf = self._alloc(512)

        # Build params struct
        params = struct.pack(
            "QQQQQQQ",
            remote_target, conv_type, remote_json, remote_buf,
            0, 0, self._func_addr,
        )
        remote_params = self._write_bytes(params)

        # Write the shellcode
        remote_code = self._write_bytes(SHELLCODE, executable=True)

        # Create remote thread — calls shellcode(remote_params)
        hThread = kernel32.CreateRemoteThread(
            self._hProcess, None, 0,
            remote_code,        # lpStartAddress = shellcode
            remote_params,      # lpParameter = params struct
            0, None,
        )
        if not hThread:
            print(f"CreateRemoteThread failed: {kernel32.GetLastError()}")
            return False

        # Wait for thread to complete
        kernel32.WaitForSingleObject(hThread, 10000)  # 10s timeout
        kernel32.CloseHandle(hThread)

        # Check result from msg_id_buffer (first byte should be non-zero if message was sent)
        # Read msg_id from remote buffer
        buf_data = self._read_bytes(remote_buf, 256)
        msg_id = buf_data.split(b'\x00')[0].decode('utf-8', errors='ignore')
        print(f"  msg_id: {msg_id}")
        return len(msg_id) > 0

    def _write_string(self, text: str) -> int:
        data = text.encode('utf-8') + b'\x00'
        return self._write_bytes(data)

    def _write_bytes(self, data: bytes, executable: bool = False) -> int:
        protect = PAGE_EXECUTE_READWRITE if executable else PAGE_READWRITE
        size = len(data)
        addr = kernel32.VirtualAllocEx(self._hProcess, None, size, MEM_COMMIT | MEM_RESERVE, protect)
        if not addr:
            raise OSError(f"VirtualAllocEx failed: {kernel32.GetLastError()}")
        written = ctypes.c_size_t()
        kernel32.WriteProcessMemory(self._hProcess, addr, data, size, ctypes.byref(written))
        return addr if isinstance(addr, int) else (addr.value if addr else 0)

    def _alloc(self, size: int) -> int:
        addr = kernel32.VirtualAllocEx(self._hProcess, None, size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
        if not addr:
            raise OSError(f"VirtualAllocEx failed: {kernel32.GetLastError()}")
        return addr if isinstance(addr, int) else (addr.value if addr else 0)

    def _read_bytes(self, addr: int, size: int) -> bytes:
        buf = ctypes.create_string_buffer(size)
        read = ctypes.c_size_t()
        kernel32.ReadProcessMemory(self._hProcess, addr, buf, size, ctypes.byref(read))
        return buf.raw[:read.value]


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

def main():
    print("=== Remote IM Sender Test ===")
    try:
        sender = RemoteIMSender()
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return 1

    print(f"PID: {sender._pid}")
    print(f"TIMMsgSendMessage in remote: {hex(sender._func_addr)}")

    # Test: send group message
    group_id = "207191791"  # A吸金A
    text = "远程注入测试消息 from Python"
    print(f"\nSending to group {group_id}: {text!r}")

    ok = sender.send_group_message(group_id, text)
    print(f"\nResult: {'SUCCESS' if ok else 'FAILED'}")
    print("Check WuQuan — it should NOT have been kicked off!")
    sender.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
