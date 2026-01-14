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
def mock_owl_dir(temp_dir, monkeypatch):
    """Set up a mock ~/.owl directory."""
    owl_dir = temp_dir / ".owl"
    owl_dir.mkdir()
    monkeypatch.setenv("OWL_DIR", str(owl_dir))
    return owl_dir
