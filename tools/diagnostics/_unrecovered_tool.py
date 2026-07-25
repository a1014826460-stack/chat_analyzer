from __future__ import annotations

import argparse
from pathlib import Path


RECOVERY_DIR = Path(__file__).resolve().parents[1] / ".codex_recovery" / "corrupted_tools_20260610_0205"


def build_parser(tool_name: str) -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description=(
            f"{tool_name} has not been fully recovered yet. "
            f"The corrupted original was archived to {RECOVERY_DIR}."
        )
    )


def main(tool_name: str) -> int:
    parser = build_parser(tool_name)
    parser.parse_args()
    print(
        f"{tool_name} is currently a recovery placeholder. "
        f"See {RECOVERY_DIR} for the archived corrupted original."
    )
    return 1
