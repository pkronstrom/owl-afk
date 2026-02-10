"""Language detection for syntax highlighting."""

import os
from typing import Optional

COMMAND_LANGUAGE_MAP: dict[str, str] = {
    "python": "python",
    "python3": "python",
    "node": "javascript",
    "npm": "javascript",
    "npx": "javascript",
    "cargo": "rust",
    "rustc": "rust",
    "go": "go",
    "ruby": "ruby",
    "perl": "perl",
    "php": "php",
    "java": "java",
    "javac": "java",
    "gcc": "c",
    "g++": "cpp",
    "make": "makefile",
}

SKIP_PREFIXES = {"sudo", "env", "nohup", "time", "nice"}

EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".rs": "rust",
    ".go": "go",
    ".rb": "ruby",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".css": "css",
    ".html": "html",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".sh": "bash",
    ".bash": "bash",
    ".md": "markdown",
    ".sql": "sql",
    ".xml": "xml",
}


def detect_bash_language(command: str) -> str:
    """Detect language from a bash command string.

    Skips sudo/env prefixes, maps first meaningful word to a language.
    Returns "bash" as fallback.
    """
    if not command:
        return "bash"

    words = command.strip().split()
    for word in words:
        if word in SKIP_PREFIXES:
            continue
        return COMMAND_LANGUAGE_MAP.get(word, "bash")

    return "bash"


def detect_file_language(file_path: str) -> Optional[str]:
    """Detect language from file extension. Returns None if unrecognized."""
    _, ext = os.path.splitext(file_path)
    if not ext:
        return None
    return EXTENSION_LANGUAGE_MAP.get(ext.lower())
