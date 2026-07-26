from __future__ import annotations
import argparse, sys
from pathlib import Path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
def _parse_args() -> "argparse.Namespace":
    parser = argparse.ArgumentParser(description="星迹分析"); parser.add_argument("--debug", action="store_true", default=False, help="启用调试模式，终端输出详细日志（在保护壳中无效）"); parser.add_argument("--admin", action="store_true", default=False, help="启用本地管理员模式，直接打开管理员功能页")
    return parser.parse_args()

if __name__ == "__main__":
    args = _parse_args()
    import app.build_config as build_config
    if args.admin:
        build_config.IS_ADMIN_VERSION = True
        build_config.IS_PRODUCTION = False
    from app.utils.logging_config import configure
    configure(debug=args.debug)
    from app.utils.protection import run_protection_checks
    if build_config.IS_PRODUCTION and getattr(sys, "frozen", False):
        run_protection_checks(exe_hash="", fast=False)
    from app.ui.main_window import run_app
    run_app()
    return
