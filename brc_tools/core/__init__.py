"""BRC Tools Core Package

Core utilities and shared functionality for the BRC Tools package.

Modules:
    logging: Centralized logging configuration
    exceptions: Custom exception classes
    retry: Retry logic and decorators
    validation: Data validation utilities
"""

from .exceptions import BRCError, APIError, DataError
from .logging import setup_logging

__all__ = ['BRCError', 'APIError', 'DataError', 'setup_logging']