from __future__ import annotations

from datetime import datetime, timedelta
import base64
import json

from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa


class LicenseSigner:
    def __init__(self) -> None:
        self._private = ECC.generate(curve="Ed25519")
        self.public_key_pem = self._private.public_key().export_key(format="PEM")

    def sign(
        self,
        machine_code: str,
        *,
        license_id: str | None = None,
        expires_in_seconds: int = 3600,
        edition: str = "user",
    ) -> str:
        payload = {
            "license_id": license_id or machine_code.replace("-", "")[:24],
            "edition": edition,
            "schema": 1,
            "machine_code": machine_code,
            "expires_at": (datetime.now() + timedelta(seconds=expires_in_seconds)).isoformat(),
        }
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        signature = eddsa.new(self._private, "rfc8032").sign(raw)
        encode = lambda value: base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
        return f"{encode(raw)}.{encode(signature)}"
