from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ServerModeSettings:
    enabled: bool = False
    base_url: str = "http://127.0.0.1:8080"

    @classmethod
    def from_dict(cls, data: object) -> "ServerModeSettings":
        value = data if isinstance(data, dict) else {}
        base_url = str(value.get("base_url") or cls.base_url).strip().rstrip("/")
        return cls(enabled=bool(value.get("enabled", False)), base_url=base_url or cls.base_url)

    def to_dict(self) -> dict[str, object]:
        return {"enabled": self.enabled, "base_url": self.base_url}
