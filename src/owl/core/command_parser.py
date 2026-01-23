"""Recursive command parser for bash wrappers, chains, and substitutions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

# Pattern for environment variable assignments (FOO=bar, _VAR=value, VAR+=append, etc.)
_ENV_VAR_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")


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

    def _is_env_assignment(self, token: str) -> bool:
        """Check if token is an environment variable assignment (FOO=bar).

        Args:
            token: The token to check.

        Returns:
            True if token matches pattern like VAR=value.
        """
        return bool(_ENV_VAR_PATTERN.match(token))

    def _skip_env_vars(self, tokens: List[str]) -> List[str]:
        """Skip leading environment variable assignments from token list.

        In bash, 'FOO=bar BAZ=qux command args' runs command with FOO and BAZ
        set only for that command. This method strips the env var prefixes
        so we can identify the actual command.

        Args:
            tokens: List of command tokens.

        Returns:
            Tokens starting from first non-env-var token.
        """
        idx = 0
        while idx < len(tokens) and self._is_env_assignment(tokens[idx]):
            idx += 1
        return tokens[idx:]

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

        # Skip leading env var assignments (FOO=bar ssh host cmd -> check ssh)
        cmd_tokens = self._skip_env_vars(tokens)
        if not cmd_tokens:
            return None

        first_token = cmd_tokens[0]
        if first_token not in WRAPPERS:
            return None

        wrapper_info = WRAPPERS[first_token]
        param_count = wrapper_info["param_count"]
        param_keys = wrapper_info["param_keys"]

        # Check if we have enough tokens for parameters + nested command
        if len(cmd_tokens) < param_count + 1:
            return None

        # Check subcommand whitelist if present (e.g., docker only wraps exec/run)
        if "subcommands" in wrapper_info:
            # First param is typically the subcommand (action)
            if len(cmd_tokens) > 1:
                subcommand = cmd_tokens[1]
                if subcommand not in wrapper_info["subcommands"]:
                    # Not a wrapper subcommand, treat as regular command
                    return None

        params = {}
        for i, key in enumerate(param_keys):
            if i + 1 < len(cmd_tokens):
                params[key] = cmd_tokens[i + 1]

        # Reconstruct nested command from remaining tokens
        remaining_tokens = cmd_tokens[param_count + 1 :]
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

        # Handle comment-only commands (lines starting with #)
        if cmd.startswith("#"):
            return CommandNode(
                type=CommandType.GENERIC,
                name="",
                full_cmd=cmd,
            )

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

        # Skip leading env var assignments (FOO=bar cmd args -> cmd is the command)
        cmd_tokens = self._skip_env_vars(tokens)
        if not cmd_tokens:
            # All tokens were env vars (unusual but valid: just sets vars)
            return CommandNode(
                type=CommandType.GENERIC,
                name="",
                args=[],
                full_cmd=cmd,
            )

        cmd_name = cmd_tokens[0]
        args = cmd_tokens[1:]

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

    def generate_patterns(self, node: CommandNode) -> List[str]:
        """Generate approval patterns from a CommandNode.

        Creates patterns from most specific to most general. For simple commands,
        returns [full_command, command_name + " *"]. For wrappers, returns
        patterns with wrapper context plus unwrapped nested patterns.

        Args:
            node: The CommandNode to generate patterns from.

        Returns:
            List of patterns from specific to general.
        """
        if node.type == CommandType.WRAPPER:
            return self._generate_wrapper_patterns(node)
        else:
            return self._generate_simple_patterns(node)

    def _generate_simple_patterns(self, node: CommandNode) -> List[str]:
        """Generate patterns for non-wrapper commands.

        Simplified to 3 patterns max:
        1. Exact match
        2. Command + first arg + wildcard (subcommand level)
        3. Command + wildcard (broadest)

        Args:
            node: The CommandNode to generate patterns from.

        Returns:
            List of patterns from specific to general.
        """
        patterns = []

        # Pattern 1: Exact match
        patterns.append(node.full_cmd)

        if node.name and node.args:
            # Pattern 2: Command + first arg + wildcard (e.g., "git branch *")
            patterns.append(f"{node.name} {node.args[0]} *")

        # Pattern 3: Command + wildcard (e.g., "git *")
        if node.name:
            patterns.append(f"{node.name} *")

        return patterns

    def _generate_wrapper_patterns(self, node: CommandNode) -> List[str]:
        """Generate patterns for wrapper commands.

        Simplified pattern generation for wrappers:
        1. Exact command (for exact-match rules)
        2. Full wrapper chain + wildcard (e.g., "ssh host docker exec container *")
        3. Outermost wrapper + wildcard (e.g., "ssh host *")

        This avoids exponential pattern growth with nested wrappers.

        Args:
            node: The CommandNode to generate patterns from.

        Returns:
            List of patterns from specific to general.
        """
        patterns = []

        # Pattern 1: Exact match (needed for rule checking in check_chain_rules)
        patterns.append(node.full_cmd)

        # Build the full wrapper chain prefix by traversing nested wrappers
        full_prefix = self._build_full_wrapper_prefix(node)

        # Pattern 2: Full wrapper chain + wildcard
        patterns.append(f"{full_prefix} *")

        # Pattern 3: Outermost wrapper + wildcard (if different from full prefix)
        outer_prefix = self._build_outer_wrapper_prefix(node)
        if outer_prefix != full_prefix:
            patterns.append(f"{outer_prefix} *")

        return patterns

    def _build_full_wrapper_prefix(self, node: CommandNode) -> str:
        """Build the full wrapper chain prefix including all nested wrappers.

        For "ssh host 'docker exec container cmd'", returns "ssh host docker exec container".
        """
        parts = [node.name]
        for param_key in WRAPPERS[node.name]["param_keys"]:
            if param_key in node.params:
                parts.append(node.params[param_key])

        # If nested is also a wrapper, recurse to include its prefix
        if node.nested and node.nested.type == CommandType.WRAPPER:
            nested_prefix = self._build_full_wrapper_prefix(node.nested)
            parts.append(nested_prefix)
        elif node.nested and node.nested.name:
            # Nested is a simple command - include command name and first arg if present
            parts.append(node.nested.name)
            if node.nested.args:
                parts.append(node.nested.args[0])

        return " ".join(parts)

    def _build_outer_wrapper_prefix(self, node: CommandNode) -> str:
        """Build just the outermost wrapper prefix.

        For "ssh host 'docker exec container cmd'", returns "ssh host".
        """
        parts = [node.name]
        for param_key in WRAPPERS[node.name]["param_keys"]:
            if param_key in node.params:
                parts.append(node.params[param_key])
        return " ".join(parts)


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
# For commands with subcommand-specific behavior, use "subcommands" to whitelist
WRAPPERS = {
    "ssh": {
        "param_keys": ["host"],
        "param_count": 1,
    },
    "docker": {
        # Only exec and run have nested commands
        "param_keys": ["action", "container"],
        "param_count": 2,
        "subcommands": ["exec", "run"],  # Only these are wrappers
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
        "param_keys": ["action", "pod"],
        "param_count": 2,
        "subcommands": ["exec"],  # Only kubectl exec is a wrapper
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
