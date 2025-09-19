"""Centralized logging configuration for BRC Tools."""

import logging
import sys
from datetime import datetime
from pathlib import Path


def setup_logging(
    level=logging.INFO,
    log_file=None,
    format_string=None,
    include_console=True
):
    """Set up logging configuration for BRC Tools.
    
    Args:
        level: Logging level (default: INFO)
        log_file: Path to log file (optional)
        format_string: Custom format string (optional)
        include_console: Whether to include console output (default: True)
    
    Returns:
        logging.Logger: Configured logger instance
    """
    
    if format_string is None:
        format_string = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # Create formatter
    formatter = logging.Formatter(format_string)
    
    # Get root logger
    logger = logging.getLogger('brc_tools')
    logger.setLevel(level)
    
    # Clear existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Console handler
    if include_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    # File handler
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


def get_logger(name):
    """Get a logger instance for a specific module.
    
    Args:
        name: Logger name (typically __name__)
        
    Returns:
        logging.Logger: Logger instance
    """
    return logging.getLogger(f'brc_tools.{name}')