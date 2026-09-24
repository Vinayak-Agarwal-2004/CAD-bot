"""
Logging configuration
"""
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

_FORMAT = '%(asctime)s %(levelname)-7s %(name)s: %(message)s'


def setup_logger(log_dir: Optional[Path] = None, level=logging.INFO) -> logging.Logger:
    """Configure the root logger once (safe to call repeatedly)."""
    logger = logging.getLogger()
    logger.setLevel(level)
    if getattr(logger, '_cadbot_configured', False):
        return logger

    formatter = logging.Formatter(_FORMAT, datefmt='%Y-%m-%d %H:%M:%S')
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / f'cadbot_{datetime.now():%Y%m%d}.log')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    for noisy in ('googleapiclient.discovery_cache', 'urllib3', 'httpx', 'trimesh', 'anthropic'):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logger._cadbot_configured = True
    return logger
