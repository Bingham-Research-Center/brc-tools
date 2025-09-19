"""Custom exception classes for BRC Tools."""


class BRCError(Exception):
    """Base exception class for BRC Tools."""
    pass


class APIError(BRCError):
    """Exception raised for API-related errors."""
    
    def __init__(self, message, status_code=None, response=None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class DataError(BRCError):
    """Exception raised for data processing errors."""
    pass


class ConfigurationError(BRCError):
    """Exception raised for configuration-related errors."""
    pass


class ValidationError(BRCError):
    """Exception raised for data validation errors."""
    pass