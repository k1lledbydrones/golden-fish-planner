from __future__ import annotations

import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler

FMT = "%(asctime)s %(levelname)-7s %(name)s:%(lineno)d: %(message)s"
DATE_FMT = "%d.%m %H:%M:%S"
STICKER_FMT = "%(asctime)s | user=%(user_id)s chat=%(chat_id)s file_id=%(file_id)s"


def setup_logging(log_file_path: str = "logs/bot.log") -> None:
    log_path = Path(log_file_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        log_path, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(FMT, datefmt=DATE_FMT))

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(logging.Formatter(FMT, datefmt=DATE_FMT))

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    # Telebot uses urllib3 under the hood; we don't need per-request noise.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("telebot").setLevel(logging.WARNING)


def setup_sticker_logging(log_file_path: str = "logs/stickers.log") -> None:
    log_path = Path(log_file_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_path, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter(STICKER_FMT, datefmt=DATE_FMT))
    logger = logging.getLogger("stickers")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.addHandler(handler)
