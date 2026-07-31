from __future__ import annotations

from dataclasses import dataclass

from app.build_config import server_api_base_url


@dataclass(frozen=True)
class ServerModeSettings:
    enabled: bool = True
    base_url: str = ""

    @classmethod
    def from_dict(cls, data: object) -> "ServerModeSettings":
        # Ordinary clients always use the centrally managed service.  The
        # legacy switch and URL are deliberately ignored so saved settings
        # cannot disable online authorization or redirect WSS credentials.
        del data
        return cls(enabled=True, base_url=server_api_base_url())

    def to_dict(self) -> dict[str, object]:
        return {"enabled": True}
