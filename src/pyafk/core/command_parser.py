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

    FILE_OPS = {
        "rm",
        "cp",
        "mv",
        "ls",
        "cat",
        "head",
        "tail",
        "sed",
        "awk",
        "grep",
        "chmod",
        "chown",
        "mkdir",
        "rmdir",
        "touch",
    }

    VCS_CMDS = {"git", "hg", "svn"}

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

    def _smart_split(self, cmd: str) -> List[str]:
        """Split command into tokens respecting quotes.

        Args:
            cmd: The command string to split.

        Returns:
            List of tokens.
        """
        tokens = []
        current_token = []
        in_double_quote = False
        in_single_quote = False
        i = 0

        while i < len(cmd):
            char = cmd[i]

            # Handle quotes
            if char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
                current_token.append(char)
                i += 1
            elif char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
                current_token.append(char)
                i += 1
            # Handle whitespace as token separator (only outside quotes)
            elif char.isspace() and not in_double_quote and not in_single_quote:
                if current_token:
                    tokens.append("".join(current_token))
                    current_token = []
                i += 1
            else:
                current_token.append(char)
                i += 1

        # Don't forget the last token
        if current_token:
            tokens.append("".join(current_token))

        return tokens

    def _parse_wrapper(self, cmd: str) -> Optional[dict]:
        """Detect if command is a wrapper and extract parameters.

        Args:
            cmd: The command string to check.

        Returns:
            Dict with {name, params, nested_cmd} if wrapper, None otherwise.
        """
        tokens = self._smart_split(cmd)
        if not tokens:
            return None

        first_token = tokens[0]
        if first_token not in WRAPPERS:
            return None

        wrapper_info = WRAPPERS[first_token]
        param_count = wrapper_info["param_count"]
        param_keys = wrapper_info["param_keys"]

        # Check if we have enough tokens for parameters + nested command
        if len(tokens) < param_count + 1:
            return None

        params = {}
        for i, key in enumerate(param_keys):
            if i + 1 < len(tokens):
                params[key] = tokens[i + 1]

        # Reconstruct nested command from remaining tokens
        remaining_tokens = tokens[param_count + 1 :]
        nested_cmd = " ".join(remaining_tokens) if remaining_tokens else None

        # Strip surrounding quotes from nested command if present
        if nested_cmd:
            if (nested_cmd.startswith('"') and nested_cmd.endswith('"')) or (
                nested_cmd.startswith("'") and nested_cmd.endswith("'")
            ):
                nested_cmd = nested_cmd[1:-1]

        return {
            "name": first_token,
            "params": params,
            "nested_cmd": nested_cmd,
        }

    def parse(self, cmd: str) -> List[CommandNode]:
        """Parse a complete bash command string into a list of CommandNode objects.

        Splits the command by chain operators (&&, ||, ;, |) and parses each
        individual command. Respects quotes so chained commands inside quotes
        are not split.

        Args:
            cmd: The complete command string to parse.

        Returns:
            List of CommandNode objects, one per chained command.
        """
        commands = self.split_chain(cmd)
        return [self.parse_single_command(cmd_str) for cmd_str in commands]

    def parse_single_command(self, cmd: str) -> CommandNode:
        """Parse a single command string into a CommandNode tree.

        Handles nested wrappers recursively.

        Args:
            cmd: The command string to parse.

        Returns:
            CommandNode representing the parsed command.
        """
        cmd = cmd.strip()

        # Check if it's a wrapper
        wrapper_result = self._parse_wrapper(cmd)
        if wrapper_result:
            nested_node = None
            if wrapper_result["nested_cmd"]:
                # Only parse the first command in the chain as the nested command
                nested_cmd_str = wrapper_result["nested_cmd"]
                chain_parts = self.split_chain(nested_cmd_str)
                if chain_parts:
                    first_cmd = chain_parts[0]
                    nested_node = self.parse_single_command(first_cmd)

            return CommandNode(
                type=CommandType.WRAPPER,
                name=wrapper_result["name"],
                params=wrapper_result["params"],
                nested=nested_node,
                full_cmd=cmd,
            )

        # It's a regular command, detect its type
        tokens = self._smart_split(cmd)
        if not tokens:
            return CommandNode(
                type=CommandType.GENERIC,
                name="",
                full_cmd=cmd,
            )

        cmd_name = tokens[0]
        args = tokens[1:]

        # Determine command type
        if cmd_name in self.FILE_OPS:
            cmd_type = CommandType.FILE_OP
        elif cmd_name in self.VCS_CMDS:
            cmd_type = CommandType.VCS
        else:
            cmd_type = CommandType.GENERIC

        return CommandNode(
            type=cmd_type,
            name=cmd_name,
            args=args,
            full_cmd=cmd,
        )


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
