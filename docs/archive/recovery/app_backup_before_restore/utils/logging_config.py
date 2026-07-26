from __future__ import annotations
import logging
from logging.handlers import RotatingFileHandler
import sys
from app.utils.pathing import user_data_dir; LOG_FMT = "%(asctime)s [%(levelname)-7s] %(name)-24s %(message)s"; DATE_FMT = "%H:%M:%S"; LOG_MAX_BYTES = 10_485_760; LOG_BACKUP_COUNT = 5
def configure(debug: "bool"=False) -> "None":
    root = logging.getLogger(); root.setLevel(logging.INFO); root.handlers.clear()
    if debug:
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.DEBUG)
        console.setFormatter(logging.Formatter(f"\x1b[36m{LOG_FMT}\x1b[0m", DATE_FMT))
        root.addHandler(console)
    log_dir = user_data_dir(); log_dir.mkdir(parents=True, exist_ok=True)
    
    file_handler = RotatingFileHandler(str(log_dir / "chat_analyzer.log"), encoding="utf-8", maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT)
    
    file_handler.setLevel(logging.DEBUG); file_handler.setFormatter(logging.Formatter(LOG_FMT, DATE_FMT))
    
    root.addHandler(file_handler)
    for noisy in ("urllib3", "requests", "charset_normalizer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    
    logging.getLogger(__name__).info("日志系统初始化完成 debug=%s", debug)
