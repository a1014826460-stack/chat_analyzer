from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.utils.pathing import user_data_dir


logger = logging.getLogger(__name__)


class JsonStore:
    def __init__(self, file_name: str) -> None:
        self.path = user_data_dir() / file_name

    def load(self, default: Any) -> Any:
        if not self.path.exists():
            return default
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Failed to load JSON store %s, using default value", self.path)
            return default

    def save(self, payload: Any) -> None:
        ensure_parent(self.path)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.debug("Saved JSON store %s", self.path)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
