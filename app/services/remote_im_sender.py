"""Send IM messages via remote thread injection into wq_v2.exe.

Calls TIMMsgSendMessage inside the WuQuan process to reuse its existing
IM login session — no new TIMLogin, no kick-off, no admin account needed.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import logging
import struct
from ctypes import wintypes

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Win32 constants
# ---------------------------------------------------------------------------
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_READ = 0x0010
PROCESS_CREATE_THREAD = 0x0002
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_EXECUTE_READWRITE = 0x40
PAGE_READWRITE = 0x04
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPPROCESS = 0x00000002

kernel32 = ctypes.windll.kernel32

# ---------------------------------------------------------------------------
# Set up proper x64 argtypes
# ---------------------------------------------------------------------------
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

kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE

# ---------------------------------------------------------------------------
# x64 trampoline shellcode
# ---------------------------------------------------------------------------
# Receives struct pointer in RCX, calls TIMMsgSendMessage.
# Struct (8-byte fields):
#   +0x00: char* conv_id       → RCX
#   +0x08: int64 conv_type     → RDX
#   +0x10: char* json_msg      → R8
#   +0x18: char* msg_buf       → R9
#   +0x20: void* callback      → [RSP+0x20]
#   +0x28: void* user_data     → [RSP+0x28]
#   +0x30: void* target_func   → call via RAX
SHELLCODE = bytes([
    0x53,                         # push rbx
    0x48, 0x83, 0xEC, 0x20,       # sub rsp, 0x20
    0x48, 0x89, 0xCB,             # mov rbx, rcx
    0x48, 0x8B, 0x0B,             # mov rcx, [rbx]
    0x48, 0x8B, 0x53, 0x08,       # mov rdx, [rbx+8]
    0x4C, 0x8B, 0x43, 0x10,       # mov r8, [rbx+16]
    0x4C, 0x8B, 0x4B, 0x18,       # mov r9, [rbx+24]
    0x48, 0x8B, 0x43, 0x28,       # mov rax, [rbx+40]
    0x48, 0x89, 0x44, 0x24, 0x28, # mov [rsp+0x28], rax
    0x48, 0x8B, 0x43, 0x20,       # mov rax, [rbx+32]
    0x48, 0x89, 0x44, 0x24, 0x20, # mov [rsp+0x20], rax
    0x48, 0x8B, 0x43, 0x30,       # mov rax, [rbx+48]
    0xFF, 0xD0,                   # call rax
    0x48, 0x83, 0xC4, 0x20,       # add rsp, 0x20
    0x5B,                         # pop rbx
    0xC3,                         # ret
])

TIMMSG_RVA = 0x3EA473  # RVA of TIMMsgSendMessage in ImSDK.dll


# ---------------------------------------------------------------------------
# RemoteIMSender
# ---------------------------------------------------------------------------

class RemoteIMSender:
    """Send messages through wq_v2.exe's existing IM session.

    Uses CreateRemoteThread to call TIMMsgSendMessage inside the
    WuQuan process.  Does NOT create a new login — no kick-off.
    """

    def __init__(self) -> None:
        self._pid = self._find_pid()
        self._hProcess = self._open_process(self._pid)
        self._func_addr = self._resolve_func_addr(self._pid)
        self._running = True

    # ------------------------------------------------------------------
    # Public API (compatible with MessageInjector)
    # ------------------------------------------------------------------

    def startup(self) -> bool:
        """Always ready — no login needed."""
        return self._running

    def shutdown(self) -> None:
        """Release process handle."""
        if self._hProcess:
            kernel32.CloseHandle(self._hProcess)
            self._hProcess = 0
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running and bool(self._hProcess)

    def inject_bet(self, group_id: str, play_type: str, amount: float) -> bool:
        text = f"{play_type} {self._fmt_amount(amount)}"
        return self.inject_text(group_id, text, is_group=True)

    def inject_text(
        self, target_id: str, text: str, *, is_group: bool = True,
    ) -> bool:
        conv_type = 2 if is_group else 1
        return self._send(target_id, conv_type, text)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _send(self, target_id: str, conv_type: int, text: str) -> bool:
        msg_json = json.dumps({
            "message_elem_array": [
                {"elem_type": 0, "text_elem_content": text}
            ],
        }, ensure_ascii=False)

        # Allocate strings and buffer in remote process
        remote_target = self._write_remote(target_id.encode("utf-8") + b"\x00")
        remote_json = self._write_remote(msg_json.encode("utf-8") + b"\x00")
        remote_buf = self._alloc_remote(512)

        # Build params struct
        params = struct.pack(
            "QQQQQQQ",
            remote_target,      # +0x00: char* conv_id
            conv_type,          # +0x08: int64 conv_type
            remote_json,        # +0x10: char* json
            remote_buf,         # +0x18: char* msg_buf
            0,                  # +0x20: callback (NULL)
            0,                  # +0x28: user_data (NULL)
            self._func_addr,    # +0x30: TIMMsgSendMessage
        )
        remote_params = self._write_remote(params)

        # Write shellcode to executable memory
        remote_code = self._write_remote(SHELLCODE, executable=True)

        # Create remote thread
        hThread = kernel32.CreateRemoteThread(
            self._hProcess, None, 0, remote_code, remote_params, 0, None,
        )
        if not hThread:
            logger.error("CreateRemoteThread failed: %d", kernel32.GetLastError())
            return False

        kernel32.WaitForSingleObject(hThread, 10000)
        kernel32.CloseHandle(hThread)

        # Read result from msg buffer
        buf = self._read_remote(remote_buf, 256)
        msg_id = buf.split(b"\x00")[0].decode("utf-8", errors="ignore")
        ok = len(msg_id) > 0
        if ok:
            logger.info("Remote IM message sent: msg_id=%s target=%s", msg_id, target_id)
        else:
            logger.error("Remote IM send failed: no msg_id (target=%s)", target_id)
        return ok

    def _write_remote(self, data: bytes, executable: bool = False) -> int:
        protect = PAGE_EXECUTE_READWRITE if executable else PAGE_READWRITE
        addr = kernel32.VirtualAllocEx(
            self._hProcess, None, len(data), MEM_COMMIT | MEM_RESERVE, protect,
        )
        if not addr:
            raise OSError(f"VirtualAllocEx failed: {kernel32.GetLastError()}")
        addr_int = addr if isinstance(addr, int) else (addr.value if addr else 0)
        written = ctypes.c_size_t()
        kernel32.WriteProcessMemory(self._hProcess, addr_int, data, len(data), ctypes.byref(written))
        return addr_int

    def _alloc_remote(self, size: int) -> int:
        addr = kernel32.VirtualAllocEx(
            self._hProcess, None, size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE,
        )
        if not addr:
            raise OSError(f"VirtualAllocEx failed: {kernel32.GetLastError()}")
        return addr if isinstance(addr, int) else (addr.value if addr else 0)

    def _read_remote(self, addr: int, size: int) -> bytes:
        buf = ctypes.create_string_buffer(size)
        read = ctypes.c_size_t()
        kernel32.ReadProcessMemory(self._hProcess, addr, buf, size, ctypes.byref(read))
        return buf.raw[:read.value]

    # ------------------------------------------------------------------
    # Process discovery
    # ------------------------------------------------------------------

    @staticmethod
    def _find_pid() -> int:
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)

        class PENTRY(ctypes.Structure):
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
        pe = PENTRY(); pe.dwSize = ctypes.sizeof(PENTRY)
        pid = None
        if kernel32.Process32FirstW(snapshot, ctypes.byref(pe)):
            while True:
                if "wq_v2" in pe.szExeFile:
                    pid = pe.th32ProcessID; break
                if not kernel32.Process32NextW(snapshot, ctypes.byref(pe)):
                    break
        kernel32.CloseHandle(snapshot)
        if pid is None:
            raise RuntimeError("wq_v2.exe not running")
        return pid

    @staticmethod
    def _open_process(pid: int) -> int:
        access = PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_VM_READ | PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION
        h = kernel32.OpenProcess(access, False, pid)
        if not h:
            raise OSError(f"OpenProcess failed (need admin): {kernel32.GetLastError()}")
        return h

    @staticmethod
    def _resolve_func_addr(pid: int) -> int:
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPPROCESS, pid)

        class MENTRY(ctypes.Structure):
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
        me = MENTRY(); me.dwSize = ctypes.sizeof(MENTRY)
        base = None
        if kernel32.Module32FirstW(snapshot, ctypes.byref(me)):
            while True:
                if "imsdk" in me.szModule.lower():
                    base = me.modBaseAddr; break
                if not kernel32.Module32NextW(snapshot, ctypes.byref(me)):
                    break
        kernel32.CloseHandle(snapshot)
        if base is None:
            raise RuntimeError("ImSDK.dll not loaded in wq_v2.exe")
        base_int = base if isinstance(base, int) else (base.value if base else 0)
        return base_int + TIMMSG_RVA

    @staticmethod
    def _fmt_amount(value: float) -> str:
        if value == int(value):
            return str(int(value))
        return f"{value:.2f}"
