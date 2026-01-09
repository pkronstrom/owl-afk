"""Tests for custom exceptions."""

import pytest

from pyafk.utils.exceptions import (
    ChainApprovalError,
    ConfigurationError,
    PyafkError,
    RuleMatchError,
    StorageError,
    TelegramAPIError,
)


def test_pyafk_error_is_base():
    """Test PyafkError is base exception for all pyafk errors."""
    assert issubclass(StorageError, PyafkError)
    assert issubclass(TelegramAPIError, PyafkError)
    assert issubclass(ChainApprovalError, PyafkError)
    assert issubclass(ConfigurationError, PyafkError)
    assert issubclass(RuleMatchError, PyafkError)


def test_exceptions_with_message():
    """Test exceptions can carry messages."""
    err = StorageError("database locked")
    assert str(err) == "database locked"

    err = ChainApprovalError("chain state invalid")
    assert "chain state invalid" in str(err)


def test_telegram_error_has_code():
    """Test TelegramAPIError can carry error code."""
    err = TelegramAPIError("forbidden", error_code=403)
    assert err.error_code == 403

    err = TelegramAPIError("rate limited", error_code=429)
    assert err.error_code == 429
    assert "rate limited" in str(err)


def test_telegram_error_without_code():
    """Test TelegramAPIError works without error code."""
    err = TelegramAPIError("unknown error")
    assert err.error_code is None
    assert "unknown error" in str(err)


def test_catch_specific_exception():
    """Test that specific exceptions can be caught."""
    with pytest.raises(StorageError):
        raise StorageError("test")

    with pytest.raises(PyafkError):
        raise StorageError("also caught by base")
