"""Runtime protection checks for the packaged Windows application."""

from __future__ import annotations

import ctypes
import hashlib
import logging
import os
import struct
import sys
from ctypes import wintypes
from pathlib import Path

logger = logging.getLogger(__name__)

_P0 = 56
_P4 = 32
_P5 = 1
_P6 = 0


def _r(name: str) -> ctypes.WinDLL:
    return ctypes.WinDLL(name, use_last_error=True)


def _x() -> tuple[ctypes.WinDLL, object, ctypes.c_bool, object, object, object]:
    kernel32 = _r("kernel32")
    return (
        _r("ntdll"),
        kernel32.IsDebuggerPresent,
        ctypes.c_bool(False),
        kernel32.CheckRemoteDebuggerPresent,
        wintypes.HANDLE,
        wintypes.BOOL,
    )


def _a0() -> bool:
    try:
        _, is_debugger_present, _, _, _, _ = _x()
        return bool(is_debugger_present())
    except Exception:
        return False


def _a1() -> bool:
    try:
        _, _, _, check_remote_debugger_present, _, _ = _x()
        present = wintypes.BOOL(False)
        check_remote_debugger_present(wintypes.HANDLE(-1), ctypes.byref(present))
        return bool(present.value)
    except Exception:
        return False


def _a2() -> bool:
    try:
        ntdll, _, _, _, _, _ = _x()
        pbi = (ctypes.c_ubyte * 8)()
        pbi_len = wintypes.ULONG(0)
        ret = ntdll.NtQueryInformationProcess(
            wintypes.HANDLE(-1),
            0,
            pbi,
            ctypes.sizeof(pbi),
            ctypes.byref(pbi_len),
        )
        if ret != 0:
            return False
        peb_ptr = struct.unpack_from("P", bytes(pbi), ctypes.sizeof(ctypes.c_void_p))[0]
        if not peb_ptr:
            return False
        return ctypes.cast(peb_ptr + 2, ctypes.POINTER(ctypes.c_ubyte)).contents.value != 0
    except Exception:
        return False


def _a3() -> bool:
    debuggers = {
        "process hacker",
        "ida",
        "dnspy",
        "ida64",
        "ilspy",
        "de4dot",
        "windbg",
        "x32dbg",
        "x64dbg",
        "dbgview",
        "fiddler",
        "ollydbg",
        "debugview",
        "reflector",
        "processhacker",
    }
    try:
        kernel32 = _r("kernel32")
        snapshot = kernel32.CreateToolhelp32Snapshot(2, 0)
        if snapshot == wintypes.HANDLE(-1).value:
            return False

        pe = ctypes.create_string_buffer(296)
        ctypes.memset(pe, 0, ctypes.sizeof(pe))
        pe_dw_size = _P0 * 4 + 8
        struct.pack_into("I", pe, 0, pe_dw_size)

        if kernel32.Process32FirstW(snapshot, pe):
            exe = pe[8:268].decode("utf-16-le", errors="ignore").rstrip("\x00").lower()
            for debugger in debuggers:
                if debugger in exe:
                    ctypes.windll.kernel32.CloseHandle(wintypes.HANDLE(snapshot))
                    return True
            ctypes.memset(pe, 0, ctypes.sizeof(pe))
            struct.pack_into("I", pe, 0, pe_dw_size)

        ctypes.windll.kernel32.CloseHandle(wintypes.HANDLE(snapshot))
        return False
    except Exception:
        return False


def _a4() -> bool:
    try:
        ntdll, _, _, _, _, _ = _x()
        pbi = (ctypes.c_ubyte * 32)()
        pbi_len = wintypes.ULONG(0)
        ret = ntdll.NtQueryInformationProcess(
            wintypes.HANDLE(-1),
            0,
            pbi,
            ctypes.sizeof(pbi),
            ctypes.byref(pbi_len),
        )
        if ret != 0:
            return False
        peb_ptr = struct.unpack_from("P", bytes(pbi), ctypes.sizeof(ctypes.c_void_p))[0]
        if not peb_ptr:
            return False
        flag = ctypes.cast(peb_ptr + 188, ctypes.POINTER(wintypes.DWORD)).contents.value
        return (flag & 112) != 0
    except Exception:
        return False


def _b(fast: bool = False) -> bool:
    checks = [_a0, _a1, _a2]
    if not fast:
        checks.extend([_a3, _a4])

    for check in checks:
        if check():
            logger.warning("Detected debugger by %s", check.__name__)
            return True

    return False


def _c(exe_path: str | None = None) -> str:
    if exe_path is None:
        exe_path = sys.executable
    if not exe_path or not Path(exe_path).exists():
        return ""

    sha = hashlib.sha256()
    with open(exe_path, "rb") as fh:
        while True:
            chunk = fh.read(65_536)
            if not chunk:
                break
            sha.update(chunk)

    return sha.hexdigest()


_K0 = ""


def _d(expected: str = "") -> bool:
    try:
        actual = _c()
        if not actual:
            return True
        if expected and actual != expected:
            logger.critical("完整性校验失败: exe 已被篡改")
            return False
        return True
    except Exception:
        logger.critical("完整性校验过程异常")
        return False


def _e() -> bool:
    try:
        import time as _t

        t1 = _t.time()
        t2 = _t.time()
        if t2 < t1:
            logger.critical("检测到系统时间被篡改")
            return False
        return True
    except Exception:
        return True


def _f(exe_hash: str = "", fast: bool = False) -> bool:
    checks: list[tuple[str, object]] = []
    if exe_hash:
        checks.append(("完整性校验", lambda: _d(exe_hash)))
    else:
        checks.append(("完整性校验", lambda: _d()))
    checks.append(("系统时间检测", _e))
    checks.append(("反调试检测", lambda: not _b(fast=fast)))

    for name, check in checks:
        try:
            if not check():
                logger.critical("保护壳自检失败: %s", name)
                return False
        except Exception:
            logger.critical("保护壳检测异常: %s", name)
            return False

    return True


def _g(title: str = "Error", message: str = "Integrity check failed") -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, message, title, _P4 | _P5 | _P6)
    except Exception:
        pass
    os._exit(1)


def run_protection_checks(exe_hash: str = "", fast: bool = False) -> None:
    if not _f(exe_hash=exe_hash, fast=fast):
        _g(
            "星迹分析 - 安全警告",
            "软件安全自检未通过，程序已退出。\n\n请从官方渠道重新下载安装。",
        )
