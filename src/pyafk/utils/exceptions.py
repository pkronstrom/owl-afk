"""Custom exceptions for pyafk."""


class PyafkError(Exception):
    """Base exception for all pyafk errors.

    All pyafk-specific exceptions inherit from this class, allowing
    callers to catch all pyafk errors with a single except clause.
    """

    pass
