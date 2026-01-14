"""Tests for custom exceptions."""

import pytest

from owl.utils.exceptions import OwlError


def test_owl_error_is_exception():
    """Test OwlError is an exception."""
    assert issubclass(OwlError, Exception)


def test_owl_error_with_message():
    """Test OwlError can carry messages."""
    err = OwlError("test error")
    assert str(err) == "test error"


def test_catch_owl_error():
    """Test that OwlError can be caught."""
    with pytest.raises(OwlError):
        raise OwlError("test")
