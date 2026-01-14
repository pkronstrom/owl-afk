"""Tests for fast path mode check."""

import pytest

from owl.fast_path import check_fast_path, FastPathResult


def test_fast_path_off_mode(mock_owl_dir):
    """Fast path should return fallback when mode is off (let Claude CLI handle it)."""
    mode_file = mock_owl_dir / "mode"
    mode_file.write_text("off")

    result = check_fast_path(mock_owl_dir)

    assert result == FastPathResult.FALLBACK


def test_fast_path_on_mode(mock_owl_dir):
    """Fast path should return continue when mode is on."""
    mode_file = mock_owl_dir / "mode"
    mode_file.write_text("on")

    result = check_fast_path(mock_owl_dir)

    assert result == FastPathResult.CONTINUE


def test_fast_path_no_mode_file(mock_owl_dir):
    """Fast path should return approve when no mode file."""
    result = check_fast_path(mock_owl_dir)

    assert result == FastPathResult.APPROVE


def test_fast_path_invalid_mode(mock_owl_dir):
    """Fast path should return continue for unknown mode."""
    mode_file = mock_owl_dir / "mode"
    mode_file.write_text("unknown")

    result = check_fast_path(mock_owl_dir)

    assert result == FastPathResult.CONTINUE
