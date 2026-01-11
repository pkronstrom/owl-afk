"""Tests for custom exceptions."""

import pytest

from pyafk.utils.exceptions import PyafkError


def test_pyafk_error_is_exception():
    """Test PyafkError is an exception."""
    assert issubclass(PyafkError, Exception)


def test_pyafk_error_with_message():
    """Test PyafkError can carry messages."""
    err = PyafkError("test error")
    assert str(err) == "test error"


def test_catch_pyafk_error():
    """Test that PyafkError can be caught."""
    with pytest.raises(PyafkError):
        raise PyafkError("test")
