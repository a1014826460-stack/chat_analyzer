from __future__ import annotations

import logging
import sys
import time
from logging.handlers import RotatingFileHandler

from app.utils.pathing import user_data_dir


LOG_FMT = "%(asctime)s [%(levelname)-7s] %(name)-24s %(message)s"
DATE_FMT = "%H:%M:%S"
LOG_MAX_BYTES = 10_485_760
LOG_BACKUP_COUNT = 5


class RateLimitFilter(logging.Filter):
    """Suppress repeated low-value log lines within a short window."""

    def __init__(self, interval_seconds: float = 30.0, key_prefixes: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.interval_seconds = float(interval_seconds)
        self.key_prefixes = tuple(key_prefixes)
        self._last_seen: dict[str, float] = {}

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        if self.key_prefixes and not any(message.startswith(prefix) for prefix in self.key_prefixes):
            return True
        key = f"{record.name}:{message}"
        now = time.monotonic()
        last = self._last_seen.get(key)
        if last is not None and now - last < self.interval_seconds:
            return False
        self._last_seen[key] = now
        return True


def configure(debug: bool = False) -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    root.handlers.clear()
    rate_limit_filter = RateLimitFilter(
        interval_seconds=30,
        key_prefixes=(
            "Skip auto message refresh",
            "Unable to refresh server pending bets",
            "Unable to refresh server statistics",
            "Unable to refresh server frequency analysis",
        ),
    )

    if debug:
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.DEBUG)
        console.setFormatter(logging.Formatter(f"\x1b[36m{LOG_FMT}\x1b[0m", DATE_FMT))
        console.addFilter(rate_limit_filter)
        root.addHandler(console)

    log_dir = user_data_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "chat_analyzer.log"

    file_handler = RotatingFileHandler(
        str(log_path),
        encoding="utf-8",
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(LOG_FMT, DATE_FMT))
    file_handler.addFilter(rate_limit_filter)
    root.addHandler(file_handler)

    for noisy in ("urllib3", "requests", "charset_normalizer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Keep --debug useful for operator diagnostics without flooding logs with
    # per-group chat rows or WSS push frames. Business-level UI logs remain at
    # DEBUG through app.ui.main_window_data and related modules.
    for noisy in (
        "app.services.chat_service",
        "app.services.ws_message_sender",
        "app.services.wss_sender",
        "backend.server_api.services.wss_sender",
        "server_api.services.wss_sender",
        "app.ui.chart_window",
        "app.services.settings_service",
        "app.services.storage_service",
    ):
        logging.getLogger(noisy).setLevel(logging.INFO)

    logging.getLogger("app.ui.main_window_realtime").setLevel(logging.ERROR)

    logging.getLogger(__name__).info(
        "日志系统初始化完成 debug=%s log_path=%s",
        debug,
        log_path,
    )
