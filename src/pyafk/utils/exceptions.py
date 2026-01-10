"""Custom exceptions for pyafk.

This module defines a hierarchy of exceptions for different error types:
- PyafkError: Base exception for all pyafk errors
- StorageError: Database/storage related errors
- TelegramAPIError: Telegram Bot API errors (with optional error code)
- ChainApprovalError: Chain approval flow errors
- ConfigurationError: Configuration related errors
- RuleMatchError: Rule pattern matching errors
"""

from typing import Optional


class PyafkError(Exception):
    """Base exception for all pyafk errors.

    All pyafk-specific exceptions inherit from this class, allowing
    callers to catch all pyafk errors with a single except clause.
    """

    pass


class StorageError(PyafkError):
    """Database/storage related errors.

    Raised when database operations fail, such as:
    - Connection failures
    - Query errors
    - Constraint violations
    """

    pass


class NotifierError(PyafkError):
    """Base exception for notifier-related errors.

    Raised when notification operations fail.
    """

    pass


class TelegramAPIError(NotifierError):
    """Telegram Bot API errors.

    Attributes:
        error_code: Optional HTTP error code from Telegram API
    """

    def __init__(self, message: str, error_code: Optional[int] = None):
        super().__init__(message)
        self.error_code = error_code


class ChainApprovalError(PyafkError):
    """Chain approval flow errors.

    Raised when chain approval operations fail, such as:
    - Invalid chain state
    - Missing chain data
    - State transitions errors
    """

    pass


class ConfigurationError(PyafkError):
    """Configuration related errors.

    Raised when configuration is invalid or missing, such as:
    - Missing required config values
    - Invalid config format
    - Environment variable errors
    """

    pass


class RuleMatchError(PyafkError):
    """Rule pattern matching errors.

    Raised when rule operations fail, such as:
    - Invalid pattern syntax
    - Pattern compilation errors
    """

    pass
