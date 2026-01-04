"""Recursive command parser for bash wrappers, chains, and substitutions."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class CommandType(Enum):
    """Types of commands."""

    WRAPPER = "wrapper"
    FILE_OP = "file_op"
    VCS = "vcs"
    GENERIC = "generic"


@dataclass
class CommandNode:
    """A node in the command parse tree.

    Represents a single command that may contain nested commands (for wrappers).
    """

    type: CommandType
    name: str
    args: List[str] = field(default_factory=list)
    params: Dict[str, str] = field(default_factory=dict)
    nested: Optional["CommandNode"] = None
    full_cmd: str = ""

    def __post_init__(self) -> None:
        """Initialize None defaults properly."""
        if self.args is None:
            self.args = []
        if self.params is None:
            self.params = {}


# Registry of wrapper types that can contain nested commands
WRAPPERS = {
    "ssh": {
        "param_keys": ["host"],
        "param_count": 1,
    },
    "docker": {
        "param_keys": ["action", "container"],
        "param_count": 2,
    },
    "sudo": {
        "param_keys": [],
        "param_count": 0,
    },
    "nix-shell": {
        "param_keys": [],
        "param_count": 0,
    },
    "kubectl": {
        "param_keys": ["action"],
        "param_count": 1,
    },
    "screen": {
        "param_keys": ["session"],
        "param_count": 1,
    },
    "tmux": {
        "param_keys": ["session"],
        "param_count": 1,
    },
    "env": {
        "param_keys": [],
        "param_count": 0,
    },
    "timeout": {
        "param_keys": ["seconds"],
        "param_count": 1,
    },
}
