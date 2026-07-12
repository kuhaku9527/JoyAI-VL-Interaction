"""Timestamped logger for per-service log files.

Each service gets a fresh log file on every startup, named with
timestamp + PID, to avoid mixing logs from different test runs.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


def setup_timestamped_logger(
    name: str,
    log_dir: str = "services/.logs",
    level: Optional[str] = None,
) -> logging.Logger:
    """Create a logger with a fresh timestamped file handler.

    Each call creates a new log file (timestamp + PID), so multiple
    service restarts do not mix logs.

    Args:
        name: logger name (e.g. "joyai.webinfer")
        log_dir: base directory for log files
        level: log level override (default: env LOG_LEVEL or INFO)

    Returns:
        Configured logger instance.
    """
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    pid = os.getpid()
    log_file = Path(log_dir) / f"{name}-{timestamp}-{pid}.log"

    logger = logging.getLogger(name)
    logger.setLevel((level or os.getenv("LOG_LEVEL", "INFO")).upper())
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    # File handler
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # Console handler (dev only)
    if os.getenv("LOG_TO_CONSOLE", "1") == "1":
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(formatter)
        logger.addHandler(ch)

    logger.info(f"Logger initialized: {log_file}")
    return logger