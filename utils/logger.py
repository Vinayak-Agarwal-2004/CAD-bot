"""
Logging configuration
"""
import logging
import sys
from pathlib import Path
from datetime import datetime

def setup_logger(log_dir: Path = None, level=logging.INFO):
    """
    Setup logging configuration

    Args:
        log_dir: Directory for log files
        level: Logging level
    """
    # Create logger
    logger = logging.getLogger()
    logger.setLevel(level)

    # Create formatters
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler (if log_dir specified)
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f'render_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'

        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
