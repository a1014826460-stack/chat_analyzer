"""IDA Pro MCP Client — minimal, working SSE-based MCP interaction."""
from __future__ import annotations

import json
import threading
import time
import urllib.request
import urllib.error
import sys


class IDAMCPClient:
    """MCP-over-SSE client for IDA Pro."""

    def __init__(self, base_url: str = "http://127.0.0.1:13338"):
        self._base = base_url
        self._session_id: str | None = None
        self._response: dict | None = None
        self._response_ready = threading.Event()
        self._stream = None
        self._running = False

    def connect(self) -> bool:
        """Establish SSE connection. Blocks until session ID received."""
        try:
            self._stream = urllib.request.urlopen(f"{self._base}/sse", timeout=10)
            self._stream.readline()  # event: endpoint
            data_line = self._stream.readline().decode()
            if "session=" in data_line:
                self._session_id = data_line.strip().split("session=")[1]
                self._running = True
                t = threading.Thread(target=self._reader, daemon=True)
                t.start()
                return True
        except Exception as e:
            print(f"[SSE] Error: {e}")
        return False

    def _reader(self) -> None:
        """Background thread: read SSE events from the persistent GET connection."""
        buf = b""
        while self._running:
            try:
                chunk = self._stream.read(4096)
                if not chunk:
                    time.sleep(0.05)
                    continue
                buf += chunk
                while b"\n\n" in buf:
                    block, buf = buf.split(b"\n\n", 1)
                    text = block.decode(errors="ignore")
                    # Extract data field
                    for line in text.split("\n"):
                        line = line.strip()
                        if line.startswith("data: "):
                            payload = line[6:]
                            if payload:
                                try:
                                    self._response = json.loads(payload)
                                    self._response_ready.set()
                                except json.JSONDecodeError:
                                    pass
            except Exception:
                if self._running:
                    time.sleep(0.05)

    def call(self, method: str, params: dict | None = None) -> dict | None:
        """Call an MCP method. Returns the JSON-RPC response."""
        if not self._session_id:
            return None

        self._response_ready.clear()
        self._response = None

        request = json.dumps({
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000),
            "method": method,
            "params": params or {},
        }).encode("utf-8")

        url = f"{self._base}/sse?session={self._session_id}"
        req = urllib.request.Request(
            url, data=request,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as e:
            # 202 Accepted is expected — response comes through SSE
            if e.code not in (200, 202, 204):
                print(f"[POST] HTTP {e.code}: {e.reason}")
                return None
        except Exception as e:
            print(f"[POST] Error: {e}")
            return None

        # Wait for the response to arrive through the SSE stream
        if self._response_ready.wait(timeout=20):
            return self._response
        print("[MCP] Timeout waiting for response")
        return None

    def py_eval(self, code: str) -> dict | None:
        """Execute Python code in IDA Pro context. Returns the raw response."""
        return self.call("tools/call", {
            "name": "py_eval",
            "arguments": {"code": code}
        })

    def py_eval_text(self, code: str) -> str:
        """Execute Python code and return text output."""
        r = self.py_eval(code)
        if r:
            content = r.get("result", {}).get("content", [])
            for c in content:
                if c.get("type") == "text":
                    return c.get("text", "")
        return ""

    def survey(self) -> str:
        """Get binary survey."""
        r = self.call("tools/call", {
            "name": "survey_binary",
            "arguments": {}
        })
        if r:
            content = r.get("result", {}).get("content", [])
            for c in content:
                if c.get("type") == "text":
                    return c.get("text", "")
        return ""

    def search_strings(self, pattern: str, limit: int = 50) -> str:
        """Search strings by regex. Returns raw JSON text."""
        r = self.call("tools/call", {
            "name": "find_regex",
            "arguments": {"pattern": pattern, "limit": limit, "offset": 0}
        })
        if r:
            content = r.get("result", {}).get("content", [])
            for c in content:
                if c.get("type") == "text":
                    return c.get("text", "")
        return ""

    def decompile(self, addr: str) -> str:
        """Decompile function at address."""
        r = self.call("tools/call", {
            "name": "decompile",
            "arguments": {"addrs": [addr]}
        })
        if r:
            content = r.get("result", {}).get("content", [])
            for c in content:
                if c.get("type") == "text":
                    return c.get("text", "")
        return ""

    def analyze_function(self, addr: str) -> str:
        """Comprehensive single-function analysis."""
        r = self.call("tools/call", {
            "name": "analyze_function",
            "arguments": {"addr": addr}
        })
        if r:
            content = r.get("result", {}).get("content", [])
            for c in content:
                if c.get("type") == "text":
                    return c.get("text", "")
        return ""

    def list_funcs(self, offset: int = 0, count: int = 50) -> str:
        """List functions."""
        r = self.call("tools/call", {
            "name": "list_funcs",
            "arguments": {"offset": offset, "count": count}
        })
        if r:
            content = r.get("result", {}).get("content", [])
            for c in content:
                if c.get("type") == "text":
                    return c.get("text", "")
        return ""


def main():
    client = IDAMCPClient()
    if not client.connect():
        print("CONNECT FAILED")
        sys.exit(1)

    time.sleep(0.3)

    # Test 1: py_eval
    print("=== py_eval ===")
    text = client.py_eval_text("print('CONNECTED OK'); import idc; print('Binary:', idc.get_input_file_path())")
    print(text[:500] if text else "NO RESPONSE")

    # Test 2: Search for message-related strings
    print("\n=== String search: 'send' ===")
    text = client.search_strings("send", limit=15)
    print(text[:1500] if text else "NO RESPONSE")


if __name__ == "__main__":
    main()
