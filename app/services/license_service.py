from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from app.models import LicenseInfo
from app.services.storage_service import JsonStore


logger = logging.getLogger(__name__)
LICENSE_STORE = JsonStore("license.json")
SECRET = "ouWpzjUPKHXsQEdX8JlhESDNTvSh6oaXtrT9xbZCwfORu8wQ"
DAY_OPTIONS = [1, 7, 30, 60, 90, 180, 365, 999]
HOUR_OPTIONS = list(range(1, 25))
CONSUMED_KEY_FIELD = "consumed_key_hashes"
LAST_SEEN_FIELD = "_last_seen_ts"


class LicenseService:
    def __init__(self, secret: str = SECRET) -> None:
        self.secret = secret.encode("utf-8")

    def get_machine_code(self) -> str:
        raw = f"{uuid.getnode()}-{uuid.UUID(int=uuid.getnode())}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def load_license(self) -> LicenseInfo:
        state = self._load_state()
        return LicenseInfo(
            key=str(state.get("key", "")),
            key_hash=str(state.get("key_hash", "")),
            expires_at=self._parse_dt(state.get("expires_at")),
            machine_code=str(state.get("machine_code", "")),
            activated_at=self._parse_dt(state.get("activated_at")),
        )

    def save_license(self, info: LicenseInfo) -> None:
        state = self._load_state()
        state.update(
            {
                "key": info.key,
                "key_hash": info.key_hash,
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
            machine_code=self.get_machine_code(),
            activated_at=datetime.now(),
        )
        self.save_license(info)
        return True, f"Activated until {info.expires_at:%Y-%m-%d %H:%M}"

    def verify_key(self, key: str) -> tuple[bool, dict[str, Any] | str]:
        try:
            payload_b64, signature = key.strip().split(".", 1)
            payload_bytes = base64.urlsafe_b64decode(self._pad_b64(payload_b64))
            expected = hmac.new(self.secret, payload_bytes, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, signature):
                return False, "Invalid activation signature."

            payload = json.loads(payload_bytes.decode("utf-8"))
            if payload.get("machine_code") != self.get_machine_code():
                return False, "Activation code does not match this machine."

            expires_at = datetime.fromisoformat(str(payload["expires_at"]))
            if expires_at < datetime.now():
                return False, "Activation code has expired."
            return True, payload
        except Exception:
            return False, "Invalid activation code format."

    def generate_key(self, value: int, machine_code: str | None = None, *, unit: str) -> str:
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
            "machine_code": machine_code,
            "duration_value": value,
            "duration_unit": unit,
            "expires_at": expires_at.isoformat(timespec="seconds"),
            "issued_at": datetime.now().isoformat(timespec="seconds"),
        }
        payload_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")
        signature = hmac.new(self.secret, payload_bytes, hashlib.sha256).hexdigest()
        return f"{payload_b64}.{signature}"

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
