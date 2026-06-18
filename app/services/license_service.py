from __future__ import annotations

import base64
import hashlib
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable

from app.build_config import LICENSE_PRIVATE_KEY_PEM, LICENSE_PUBLIC_KEY_PEM
from app.models import LicenseInfo
from app.services.signing_service import sign_payload, verify_token
from app.services.storage_service import JsonStore


logger = logging.getLogger(__name__)
LICENSE_STORE = JsonStore("license.json")
DAY_OPTIONS = [1, 7, 30, 60, 90, 180, 365, 999]
HOUR_OPTIONS = list(range(1, 25))
CONSUMED_KEY_FIELD = "consumed_key_hashes"
LAST_SEEN_FIELD = "_last_seen_ts"
ACTIVATION_CODE_FIELD = "activation_code"
LICENSE_SCHEMA = 1


class LicenseService:
    def __init__(
        self,
        private_key_pem: str | None = None,
        public_key_pem: str | None = None,
        machine_code_provider: Callable[[], str] | None = None,
    ) -> None:
        self.private_key_pem = private_key_pem if private_key_pem is not None else LICENSE_PRIVATE_KEY_PEM
        self.public_key_pem = public_key_pem if public_key_pem is not None else LICENSE_PUBLIC_KEY_PEM
        self._machine_code_provider = machine_code_provider

    def get_machine_code(self) -> str:
        if self._machine_code_provider is not None:
            return str(self._machine_code_provider())
        raw = f"{uuid.getnode()}-{uuid.UUID(int=uuid.getnode())}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def load_license(self) -> LicenseInfo:
        state = self._load_state()
        activation_code = str(state.get(ACTIVATION_CODE_FIELD, "")).strip()
        payload: dict[str, Any] = {}
        if activation_code and self.public_key_pem.strip():
            try:
                payload = verify_token(activation_code, self.public_key_pem)
            except ValueError:
                payload = {}
        return LicenseInfo(
            key=activation_code or str(state.get("key", "")),
            key_hash=str(state.get("key_hash", "")),
            expires_at=self._parse_dt(str(payload.get("expires_at", "")) or state.get("expires_at")),
            machine_code=str(payload.get("machine_code", "")) or str(state.get("machine_code", "")),
            activated_at=self._parse_dt(state.get("activated_at")),
        )

    def save_license(self, info: LicenseInfo) -> None:
        state = self._load_state()
        payload: dict[str, Any] = {}
        if info.key and self.public_key_pem.strip():
            try:
                payload = verify_token(info.key, self.public_key_pem)
            except ValueError:
                payload = {}
        state.update(
            {
                "key": info.key,
                ACTIVATION_CODE_FIELD: info.key,
                "key_hash": info.key_hash,
                "license_id": str(payload.get("license_id", state.get("license_id", ""))),
                "payload": payload,
                "expires_at": info.expires_at.isoformat() if info.expires_at else "",
                "machine_code": info.machine_code,
                "activated_at": info.activated_at.isoformat() if info.activated_at else "",
            }
        )
        consumed = self._consumed_hashes(state)
        if info.key_hash:
            consumed.add(info.key_hash)
        state[CONSUMED_KEY_FIELD] = sorted(consumed)
        state[LAST_SEEN_FIELD] = str(datetime.now().timestamp())
        LICENSE_STORE.save(state)

    def is_activated(self) -> bool:
        info = self.load_license()
        if not info.is_active:
            return False
        if info.machine_code != self.get_machine_code():
            return False
        return self._verify_time_integrity()

    def _verify_time_integrity(self) -> bool:
        state = self._load_state()
        last_seen_str = str(state.get(LAST_SEEN_FIELD, "")).strip()
        now_ts = datetime.now().timestamp()
        if last_seen_str:
            try:
                last_seen = float(last_seen_str)
            except ValueError:
                last_seen = now_ts
            if now_ts < last_seen - 60:
                logger.critical("System clock rollback detected: last=%s now=%s", last_seen, now_ts)
                return False
        state[LAST_SEEN_FIELD] = str(now_ts)
        LICENSE_STORE.save(state)
        return True

    def activate(self, key: str) -> tuple[bool, str]:
        key = key.strip()
        ok, payload_or_message = self.verify_key(key)
        if not ok:
            return False, str(payload_or_message)

        payload = payload_or_message
        key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        state = self._load_state()
        consumed = self._consumed_hashes(state)
        if key_hash in consumed:
            return False, "This activation code has already been used."

        info = LicenseInfo(
            key=key,
            key_hash=key_hash,
            expires_at=datetime.fromisoformat(str(payload["expires_at"])),
            machine_code=str(payload["machine_code"]),
            activated_at=datetime.now(),
        )
        self.save_license(info)
        return True, f"Activated until {info.expires_at:%Y-%m-%d %H:%M}"

    def verify_key(self, key: str) -> tuple[bool, dict[str, Any] | str]:
        try:
            payload = verify_token(key, self.public_key_pem)
            if payload.get("edition") != "user":
                return False, "Invalid activation edition."
            if int(payload.get("schema", 0)) != LICENSE_SCHEMA:
                return False, "Unsupported activation schema."
            if payload.get("machine_code") != self.get_machine_code():
                return False, "Activation code does not match this machine."

            expires_at = datetime.fromisoformat(str(payload["expires_at"]))
            if expires_at < datetime.now():
                return False, "Activation code has expired."
            return True, payload
        except ValueError as exc:
            message = str(exc)
            if "signature" in message.lower():
                return False, "Invalid activation signature."
            return False, "Invalid activation code format."
        except Exception:
            return False, "Invalid activation code format."

    def generate_key(self, value: int, machine_code: str | None = None, *, unit: str) -> str:
        if not self.private_key_pem.strip():
            raise ValueError("Private signing key is not configured.")
        if unit == "days":
            if value not in DAY_OPTIONS:
                raise ValueError("Unsupported license duration")
            expires_at = datetime.now() + timedelta(days=value)
        elif unit == "hours":
            if value not in HOUR_OPTIONS:
                raise ValueError("Unsupported license duration")
            expires_at = datetime.now() + timedelta(hours=value)
        else:
            raise ValueError("Unsupported license duration unit")

        machine_code = machine_code or self.get_machine_code()
        payload = {
            "license_id": uuid.uuid4().hex,
            "edition": "user",
            "schema": LICENSE_SCHEMA,
            "machine_code": machine_code,
            "duration_value": value,
            "duration_unit": unit,
            "features": ["standard"],
            "expires_at": expires_at.isoformat(timespec="seconds"),
            "issued_at": datetime.now().isoformat(timespec="seconds"),
        }
        return sign_payload(payload, self.private_key_pem)

    def _load_state(self) -> dict[str, Any]:
        state = LICENSE_STORE.load({})
        if not isinstance(state, dict):
            return {}
        if not isinstance(state.get(CONSUMED_KEY_FIELD), list):
            state[CONSUMED_KEY_FIELD] = []
        return state

    def _consumed_hashes(self, state: dict[str, Any] | None = None) -> set[str]:
        state = self._load_state() if state is None else state
        return {str(item).strip() for item in state.get(CONSUMED_KEY_FIELD, []) if str(item).strip()}

    def _pad_b64(self, value: str) -> str:
        return value + "=" * (-len(value) % 4)

    def _parse_dt(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
