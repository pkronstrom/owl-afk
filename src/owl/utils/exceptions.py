"""Custom exceptions for owl."""


class OwlError(Exception):
    """Base exception for all owl errors.

    All owl-specific exceptions inherit from this class, allowing
    callers to catch all owl errors with a single except clause.
    """

    pass
