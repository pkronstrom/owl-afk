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
    "ssh": {"type": CommandType.WRAPPER, "description": "SSH remote execution"},
    "docker": {"type": CommandType.WRAPPER, "description": "Docker container execution"},
    "sudo": {"type": CommandType.WRAPPER, "description": "Sudo privilege escalation"},
    "nix-shell": {"type": CommandType.WRAPPER, "description": "Nix shell environment"},
    "kubectl": {"type": CommandType.WRAPPER, "description": "Kubernetes command execution"},
    "screen": {"type": CommandType.WRAPPER, "description": "Screen session command"},
    "tmux": {"type": CommandType.WRAPPER, "description": "Tmux session command"},
    "env": {"type": CommandType.WRAPPER, "description": "Environment variable wrapper"},
    "timeout": {"type": CommandType.WRAPPER, "description": "Timeout wrapper"},
}
