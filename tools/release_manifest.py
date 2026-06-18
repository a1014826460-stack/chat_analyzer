from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.update_service import build_manifest, manifest_token_to_json


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a signed StarTrace release manifest token.")
    parser.add_argument("--artifact", required=True, help="Path to built artifact exe.")
    parser.add_argument("--channel", required=True, choices=["user", "admin"], help="Release channel.")
    parser.add_argument("--version", required=True, help="Release version.")
    parser.add_argument("--base-url", required=True, help="CDN directory URL containing the artifact.")
    parser.add_argument("--notes", default="", help="Release notes.")
    parser.add_argument("--private-key", required=True, help="Path to Ed25519 private key PEM.")
    parser.add_argument("--min-supported-version", default="", help="Minimum supported version.")
    parser.add_argument("--force", action="store_true", help="Mark update as forced.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    artifact_path = Path(args.artifact).resolve()
    private_key_pem = Path(args.private_key).read_text(encoding="utf-8")
    token = build_manifest(
        artifact_path=artifact_path,
        channel=args.channel,
        version=args.version,
        base_url=args.base_url,
        notes=args.notes,
        private_key_pem=private_key_pem,
        min_supported_version=args.min_supported_version or args.version,
        force=args.force,
        published_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    print(json.dumps(manifest_token_to_json(token), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
