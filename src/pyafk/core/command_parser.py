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


class CommandParser:
    """Parser for bash commands with chain splitting and quote handling."""

    def split_chain(self, cmd: str) -> List[str]:
        """Split a command chain into individual commands.

        Respects quotes and shell operators (&&, ||, ;, |).

        Args:
            cmd: The command string to split.

        Returns:
            List of individual commands.
        """
        commands = []
        current_cmd = []
        in_double_quote = False
        in_single_quote = False
        i = 0

        while i < len(cmd):
            char = cmd[i]

            # Handle quotes
            if char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
                current_cmd.append(char)
                i += 1
            elif char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
                current_cmd.append(char)
                i += 1
            # Handle operators only when not in quotes
            elif not in_double_quote and not in_single_quote:
                # Check for two-character operators first
                if i + 1 < len(cmd):
                    two_char = cmd[i : i + 2]
                    if two_char in ("&&", "||"):
                        # Save current command
                        cmd_str = "".join(current_cmd).strip()
                        if cmd_str:
                            commands.append(cmd_str)
                        current_cmd = []
                        i += 2
                        continue

                # Check for single-character operators
                if char in (";", "|"):
                    # Save current command
                    cmd_str = "".join(current_cmd).strip()
                    if cmd_str:
                        commands.append(cmd_str)
                    current_cmd = []
                    i += 1
                else:
                    current_cmd.append(char)
                    i += 1
            else:
                current_cmd.append(char)
                i += 1

        # Don't forget the last command
        cmd_str = "".join(current_cmd).strip()
        if cmd_str:
            commands.append(cmd_str)

        return commands


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
