from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Protect/compress a StarTrace exe with UPX.")
    parser.add_argument("artifact", help="Path to the exe artifact.")
    parser.add_argument("--upx", default="upx", help="UPX executable path.")
    parser.add_argument("--backup", action="store_true", help="Create a .before-upx.exe backup next to the artifact.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    artifact = Path(args.artifact).resolve()
    if not artifact.exists():
        raise SystemExit(f"Artifact not found: {artifact}")
    if args.backup:
        backup = artifact.with_suffix(".before-upx.exe")
        shutil.copy2(artifact, backup)
        print(f"Backup written: {backup}")
    command = [args.upx, "--best", "--lzma", str(artifact)]
    print("Running:", " ".join(command))
    completed = subprocess.run(command)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
