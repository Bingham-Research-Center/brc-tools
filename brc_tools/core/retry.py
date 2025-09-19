"""Retry logic and decorators for BRC Tools."""

import time
import functools
import logging
from typing import Callable, Type, Union, Tuple

from .exceptions import APIError

logger = logging.getLogger(__name__)


def retry_with_backoff(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    exceptions: Union[Type[Exception], Tuple[Type[Exception], ...]] = (APIError,)
):
    """Decorator that retries a function with exponential backoff.
    
    Args:
        max_attempts: Maximum number of retry attempts
        base_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries in seconds
        exponential_base: Base for exponential backoff calculation
        exceptions: Exception types to catch and retry on
        
    Returns:
        Decorated function
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt == max_attempts - 1:
                        logger.error(
                            f"Function {func.__name__} failed after {max_attempts} attempts. "
                            f"Last error: {e}"
                        )
                        raise
                    
                    # Calculate delay with exponential backoff
                    delay = min(base_delay * (exponential_base ** attempt), max_delay)
                    
                    logger.warning(
                        f"Function {func.__name__} failed on attempt {attempt + 1}/{max_attempts}. "
                        f"Retrying in {delay:.2f} seconds. Error: {e}"
                    )
                    
                    time.sleep(delay)
            
            # This should never be reached, but just in case
            raise last_exception
        
        return wrapper
    return decorator


def simple_retry(func: Callable, max_attempts: int = 3, delay: float = 1.0):
    """Simple retry function without decorator.
    
    Args:
        func: Function to retry
        max_attempts: Maximum number of attempts
        delay: Fixed delay between attempts in seconds
        
    Returns:
        Result of the function call
        
    Raises:
        Last exception encountered if all attempts fail
    """
    last_exception = None
    
    for attempt in range(max_attempts):
        try:
            return func()
        except Exception as e:
            last_exception = e
            
            if attempt == max_attempts - 1:
                logger.error(f"Function failed after {max_attempts} attempts: {e}")
                raise
            
            logger.warning(f"Attempt {attempt + 1} failed, retrying in {delay}s: {e}")
            time.sleep(delay)
    
    raise last_exception