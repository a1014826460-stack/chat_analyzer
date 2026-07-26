from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="StarTrace Chat Analyzer")
    parser.add_argument("--debug", action="store_true", default=False, help="Enable debug logging")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    import app.build_config as build_config

    from app.utils.logging_config import configure

    configure(debug=args.debug)

    from app.utils.protection import run_protection_checks

    if build_config.IS_PRODUCTION and getattr(sys, "frozen", False):
        run_protection_checks(exe_hash="", fast=False)

    from app.ui.main_window import run_app

    run_app()


if __name__ == "__main__":
    main()
