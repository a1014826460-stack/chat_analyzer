"""Test loading ImSDK.dll via ctypes and calling its API functions."""
from __future__ import annotations

import ctypes
import json
import os
import struct
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ---------------------------------------------------------------------------
# Load ImSDK.dll and list its exports
# ---------------------------------------------------------------------------
DLL_PATH = Path(r"d:\pythonProject\outsource\chat_analyzer\WuQuan\ImSDK.dll")

# Parse exports from PE header
def get_exports(dll_path: Path) -> dict[str, int]:
    """Parse PE export table → {name: RVA}."""
    with open(dll_path, "rb") as f:
        data = f.read()

    pe_off = struct.unpack_from("<I", data, 0x3C)[0]
    opt_hdr_off = pe_off + 24
    magic = struct.unpack_from("<H", data, opt_hdr_off)[0]
    is_64 = magic == 0x20B
    exp_off = 0x70 if is_64 else 0x60
    num_sec = struct.unpack_from("<H", data, pe_off + 6)[0]
    opt_size = struct.unpack_from("<H", data, pe_off + 20)[0]

    # Parse sections for RVA→file offset
    sec_start = pe_off + 24 + opt_size
    sections = []
    for i in range(num_sec):
        name = data[sec_start : sec_start + 8].rstrip(b"\x00").decode()
        vsize = struct.unpack_from("<I", data, sec_start + 8)[0]
        vrva = struct.unpack_from("<I", data, sec_start + 12)[0]
        raw = struct.unpack_from("<I", data, sec_start + 20)[0]
        sections.append((name, vrva, vsize, raw))
        sec_start += 40

    def rva2off(rva):
        for _, vrva, vsize, raw in sections:
            if vrva <= rva < vrva + vsize:
                return raw + (rva - vrva)
        return None

    # Export directory
    exp_rva = struct.unpack_from("<I", data, opt_hdr_off + exp_off)[0]
    file_off = rva2off(exp_rva)
    if file_off is None:
        return {}

    exp = data[file_off : file_off + 40]
    name_rva = struct.unpack_from("<I", exp, 12)[0]
    num_names = struct.unpack_from("<I", exp, 24)[0]
    addr_rva = struct.unpack_from("<I", exp, 28)[0]
    namep_rva = struct.unpack_from("<I", exp, 32)[0]
    ord_rva = struct.unpack_from("<I", exp, 36)[0]

    namep_off = rva2off(namep_rva)
    ord_off = rva2off(ord_rva)
    addr_off = rva2off(addr_rva)
    if not all([namep_off, ord_off, addr_off]):
        return {}

    exports = {}
    for i in range(num_names):
        n_rva = struct.unpack_from("<I", data, namep_off + i * 4)[0]
        n_off = rva2off(n_rva)
        if n_off:
            end = data.find(b"\x00", n_off)
            name = data[n_off:end].decode("ascii", errors="ignore")
            if name:
                ordinal = struct.unpack_from("<H", data, ord_off + i * 2)[0]
                func_rva = struct.unpack_from("<I", data, addr_off + ordinal * 4)[0]
                exports[name] = func_rva
    return exports


# ---------------------------------------------------------------------------
# Tencent Cloud IM SDK type definitions (from TIMCloud.h / TIMCloudDef.h)
# ---------------------------------------------------------------------------

# Callback types
TIMRecvNewMsgCallback = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p)
TIMCommCallback = ctypes.CFUNCTYPE(
    None, ctypes.c_int32, ctypes.c_char_p, ctypes.c_void_p
)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    exports = get_exports(DLL_PATH)
    print(f"Parsed {len(exports)} exports from {DLL_PATH.name}")

    # Key APIs we need
    key_apis = {
        "TIMInit": None,
        "TIMUninit": None,
        "TIMLogin": None,
        "TIMLogout": None,
        "TIMGetLoginStatus": None,
        "TIMGetLoginUserID": None,
        "TIMMsgSendMessage": None,
        "TIMMsgSendNewMsg": None,
        "TIMMsgSendNewMsgEx": None,
    }

    for api_name in key_apis:
        if api_name in exports:
            key_apis[api_name] = exports[api_name]
            print(f"  [OK] {api_name} -> RVA 0x{exports[api_name]:X}")
        else:
            print(f"  [MISS] {api_name} NOT FOUND")

    # Load DLL
    print(f"\nLoading {DLL_PATH}...")
    try:
        imsdk = ctypes.CDLL(str(DLL_PATH))
        print("  DLL loaded successfully!")
        print(f"  Handle: {imsdk._handle}")
    except Exception as e:
        print(f"  Failed to load: {e}")

        # Try with explicit path
        import os
        os.add_dll_directory(str(DLL_PATH.parent))
        imsdk = ctypes.CDLL(str(DLL_PATH))
        print(f"  DLL loaded with add_dll_directory, handle: {imsdk._handle}")

    # Try to get function pointers
    print("\n=== Testing function access ===")
    for api_name in ["TIMInit", "TIMGetLoginStatus"]:
        if api_name in exports:
            try:
                func = getattr(imsdk, api_name)
                print(f"  {api_name}: {func}")
            except AttributeError as e:
                print(f"  {api_name}: not available ({e})")

    # TIMGetLoginStatus — check login state
    print("\n=== TIMGetLoginStatus ===")
    # enum TIMLoginStatus { TIM_STATUS_LOGOFF=0, TIM_STATUS_LOGINING=1, TIM_STATUS_LOGINED=2, TIM_STATUS_LOGOUTING=3 }
    try:
        func = imsdk.TIMGetLoginStatus
        func.restype = ctypes.c_int
        status = func()
        status_names = {0: "LOGOFF", 1: "LOGINING", 2: "LOGINED", 3: "LOGOUTING"}
        print(f"  Login status: {status} ({status_names.get(status, 'UNKNOWN')})")
    except Exception as e:
        print(f"  Error: {e}")

    # TIMInit — initialize SDK
    print("\n=== TIMInit ===")
    try:
        func = imsdk.TIMInit
        func.restype = ctypes.c_int
        func.argtypes = [ctypes.c_uint64, ctypes.c_char_p]

        sdk_app_id = 20011216  # from shared_preferences.json

        # Config JSON
        config = json.dumps({
            "sdk_config_file_path": str(DLL_PATH.parent / "data"),
            "log_file_path": str(DLL_PATH.parent),
        }).encode("utf-8")

        print(f"  Calling TIMInit(sdkAppId={sdk_app_id}, config_path=...)")
        ret = func(sdk_app_id, config)
        print(f"  Result: {ret} {'(SUCCESS)' if ret == 0 else '(FAILED)'}")

        if ret == 0:
            # Check login status after init
            status_func = imsdk.TIMGetLoginStatus
            status_func.restype = ctypes.c_int
            status = status_func()
            print(f"  Login status after init: {status}")
    except Exception as e:
        print(f"  Error: {e}")

    print("\nDone.")


if __name__ == "__main__":
    main()
