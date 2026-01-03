"""Shared pytest fixtures."""

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test data."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def mock_pyafk_dir(temp_dir, monkeypatch):
    """Set up a mock ~/.pyafk directory."""
    pyafk_dir = temp_dir / ".pyafk"
    pyafk_dir.mkdir()
    monkeypatch.setenv("PYAFK_DIR", str(pyafk_dir))
    return pyafk_dir
