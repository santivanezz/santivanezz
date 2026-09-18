from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from .security import redact


class RedactingFormatter(logging.Formatter):
    """Never write secrets to logs."""

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        cleaned, _ = redact(msg)
        return cleaned


def setup_logging(log_dir: Path, level: int = logging.INFO) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("sergio_brain")
    if logger.handlers:
        return logger
    logger.setLevel(level)
    fmt = RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = logging.handlers.RotatingFileHandler(log_dir / "sergio_brain.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    sh.setLevel(logging.WARNING)
    logger.addHandler(sh)
    return logger
