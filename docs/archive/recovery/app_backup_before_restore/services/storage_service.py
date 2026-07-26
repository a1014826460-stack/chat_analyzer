from __future__ import annotations
import json, logging
from pathlib import Path
from typing import Any
from app.utils.pathing import user_data_dir; logger = logging.getLogger(__name__)
class JsonStore:
    def __init__(self, file_name: "str") -> "None":
        self.path = user_data_dir() / file_name
    
    def load(self, default: "Any") -> "Any":
        if not self.path.exists():
            return default
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except:
            pass
    
    def save(self, payload: "Any") -> "None":
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"); logger.debug("已保存: %s (%d keys)", self.path, 0)

def ensure_parent(path: "Path") -> "None":
    path.parent.mkdir(parents=True, exist_ok=True)
