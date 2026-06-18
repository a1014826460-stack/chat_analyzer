from __future__ import annotations

import base64
import json
from typing import Any

from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def sign_bytes(data: bytes, private_key_pem: str) -> bytes:
    if not private_key_pem.strip():
        raise ValueError("Private signing key is not configured.")
    key = ECC.import_key(private_key_pem)
    return eddsa.new(key, "rfc8032").sign(data)


def verify_bytes(data: bytes, signature: bytes, public_key_pem: str) -> None:
    if not public_key_pem.strip():
        raise ValueError("Public verification key is not configured.")
    key = ECC.import_key(public_key_pem)
    try:
        eddsa.new(key, "rfc8032").verify(data, signature)
    except ValueError as exc:
        raise ValueError("Invalid signature.") from exc


def sign_payload(payload: dict[str, Any], private_key_pem: str) -> str:
    payload_bytes = canonical_json_bytes(payload)
    signature = sign_bytes(payload_bytes, private_key_pem)
    return f"{b64url_encode(payload_bytes)}.{b64url_encode(signature)}"


def verify_token(token: str, public_key_pem: str) -> dict[str, Any]:
    try:
        payload_b64, signature_b64 = token.strip().split(".", 1)
        payload_bytes = b64url_decode(payload_b64)
        signature = b64url_decode(signature_b64)
    except Exception as exc:
        raise ValueError("Invalid signed token format.") from exc

    verify_bytes(payload_bytes, signature, public_key_pem)
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError("Invalid signed token payload.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Invalid signed token payload.")
    return payload
