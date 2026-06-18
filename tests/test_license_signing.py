from __future__ import annotations

from datetime import datetime, timedelta

from Crypto.PublicKey import ECC
import pytest


def _key_pair() -> tuple[str, str]:
    key = ECC.generate(curve="Ed25519")
    return key.export_key(format="PEM"), key.public_key().export_key(format="PEM")


def test_signed_token_round_trip_rejects_tampering() -> None:
    from app.services.signing_service import sign_payload, verify_token

    private_pem, public_pem = _key_pair()
    token = sign_payload({"machine_code": "machine-1", "schema": 1}, private_pem)

    assert verify_token(token, public_pem)["machine_code"] == "machine-1"

    payload_part, signature_part = token.split(".", 1)
    tampered = payload_part[:-1] + ("A" if payload_part[-1] != "A" else "B")
    with pytest.raises(ValueError, match="signature"):
        verify_token(f"{tampered}.{signature_part}", public_pem)


def test_license_service_generates_activation_for_target_machine_and_saves_signed_license(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import license_service as module
    from app.services.license_service import LicenseService

    saved_state: dict[str, object] = {}

    class MemoryStore:
        def load(self, default: object) -> object:
            return dict(saved_state) if saved_state else default

        def save(self, payload: object) -> None:
            saved_state.clear()
            saved_state.update(dict(payload))

    private_pem, public_pem = _key_pair()
    monkeypatch.setattr(module, "LICENSE_STORE", MemoryStore())

    service = LicenseService(
        private_key_pem=private_pem,
        public_key_pem=public_pem,
        machine_code_provider=lambda: "target-machine",
    )
    key = service.generate_key(1, "target-machine", unit="days")

    ok, message = service.activate(key)

    assert ok, message
    assert "Activated until" in message
    assert service.is_activated()
    assert saved_state["activation_code"] == key
    assert saved_state["machine_code"] == "target-machine"
    assert saved_state["license_id"]

    offline_service = LicenseService(
        public_key_pem=public_pem,
        machine_code_provider=lambda: "target-machine",
    )
    assert offline_service.is_activated()


def test_license_service_rejects_wrong_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import license_service as module
    from app.services.license_service import LicenseService

    class MemoryStore:
        def load(self, default: object) -> object:
            return default

        def save(self, payload: object) -> None:
            raise AssertionError("wrong-machine activation must not be saved")

    private_pem, public_pem = _key_pair()
    monkeypatch.setattr(module, "LICENSE_STORE", MemoryStore())
    admin = LicenseService(
        private_key_pem=private_pem,
        public_key_pem=public_pem,
        machine_code_provider=lambda: "admin-machine",
    )
    key = admin.generate_key(1, "target-machine", unit="days")

    user = LicenseService(public_key_pem=public_pem, machine_code_provider=lambda: "other-machine")

    ok, message = user.activate(key)

    assert not ok
    assert "machine" in message.lower()


def test_license_service_rejects_clock_rollback(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import license_service as module
    from app.services.license_service import LicenseService

    future_ts = (datetime.now() + timedelta(hours=1)).timestamp()

    class MemoryStore:
        def load(self, default: object) -> object:
            return {
                "activation_code": "",
                "expires_at": (datetime.now() + timedelta(days=1)).isoformat(timespec="seconds"),
                "machine_code": "target-machine",
                module.LAST_SEEN_FIELD: str(future_ts),
            }

        def save(self, payload: object) -> None:
            raise AssertionError("rollback state must not be saved")

    monkeypatch.setattr(module, "LICENSE_STORE", MemoryStore())
    service = LicenseService(public_key_pem=_key_pair()[1], machine_code_provider=lambda: "target-machine")

    assert not service.is_activated()
