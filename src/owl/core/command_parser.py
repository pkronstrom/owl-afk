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
    COMPOUND = "compound"  # for/while/if/case/subshell


class CompoundType(Enum):
    """Types of compound commands."""

    FOR_LOOP = "for"
    WHILE_LOOP = "while"
    UNTIL_LOOP = "until"
    IF_STATEMENT = "if"
    CASE_STATEMENT = "case"
    SUBSHELL = "subshell"  # ( commands )
    BRACE_GROUP = "brace_group"  # { commands; }


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

        Respects quotes, heredocs, compound commands (for/while/if), and shell
        operators (&&, ||, ;, |).

        Args:
            cmd: The command string to split.

        Returns:
            List of individual commands.
        """
        commands = []
        current_cmd = []
        in_double_quote = False
        in_single_quote = False
        in_heredoc = False
        heredoc_delimiter = ""
        # Track compound command depth (for/while/until...done, if...fi, case...esac)
        compound_depth = 0
        i = 0

        def get_word_at(pos: int) -> str:
            """Extract word starting at position."""
            end = pos
            while end < len(cmd) and (cmd[end].isalnum() or cmd[end] == "_"):
                end += 1
            return cmd[pos:end]

        def is_word_boundary(pos: int) -> bool:
            """Check if position is at word boundary (start or after whitespace/operator)."""
            if pos == 0:
                return True
            prev = cmd[pos - 1]
            return prev.isspace() or prev in ";|&"

        while i < len(cmd):
            char = cmd[i]

            # Handle heredoc content - skip until we find the delimiter on its own line
            if in_heredoc:
                current_cmd.append(char)
                # Check if we're at the start of a line that might be the delimiter
                if char == "\n" or (i == 0):
                    # Look ahead for the delimiter at start of next line
                    start = i + 1 if char == "\n" else i
                    # Check if the delimiter appears at this position
                    if cmd[start:].startswith(heredoc_delimiter):
                        end_pos = start + len(heredoc_delimiter)
                        # Delimiter must be followed by newline or end of string
                        if end_pos >= len(cmd) or cmd[end_pos] == "\n":
                            # Found the end of heredoc - consume the delimiter
                            current_cmd.extend(list(cmd[start:end_pos]))
                            i = end_pos
                            in_heredoc = False
                            heredoc_delimiter = ""
                            continue
                i += 1
                continue

            # Handle quotes
            if char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
                current_cmd.append(char)
                i += 1
            elif char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
                current_cmd.append(char)
                i += 1
            # Track compound commands (only outside quotes)
            elif not in_double_quote and not in_single_quote and char.isalpha() and is_word_boundary(i):
                word = get_word_at(i)
                # Opening keywords increase depth
                if word in ("for", "while", "until", "if", "case"):
                    compound_depth += 1
                # Closing keywords decrease depth
                elif word in ("done", "fi", "esac") and compound_depth > 0:
                    compound_depth -= 1
                # Add the character and continue
                current_cmd.append(char)
                i += 1
            # Handle heredoc start (only outside quotes)
            elif not in_double_quote and not in_single_quote and char == "<":
                # Check for << heredoc operator
                if i + 1 < len(cmd) and cmd[i + 1] == "<":
                    current_cmd.append(char)
                    current_cmd.append(cmd[i + 1])
                    i += 2
                    # Skip optional - for <<-
                    if i < len(cmd) and cmd[i] == "-":
                        current_cmd.append(cmd[i])
                        i += 1
                    # Skip whitespace before delimiter
                    while i < len(cmd) and cmd[i] in " \t":
                        current_cmd.append(cmd[i])
                        i += 1
                    # Extract the delimiter (may be quoted or unquoted)
                    if i < len(cmd):
                        delim_char = cmd[i]
                        if delim_char in ("'", '"'):
                            # Quoted delimiter - find closing quote
                            current_cmd.append(delim_char)
                            i += 1
                            delim_start = i
                            while i < len(cmd) and cmd[i] != delim_char:
                                current_cmd.append(cmd[i])
                                i += 1
                            heredoc_delimiter = cmd[delim_start:i]
                            if i < len(cmd):
                                current_cmd.append(cmd[i])  # closing quote
                                i += 1
                        else:
                            # Unquoted delimiter - read until whitespace/newline
                            delim_start = i
                            while i < len(cmd) and cmd[i] not in " \t\n":
                                current_cmd.append(cmd[i])
                                i += 1
                            heredoc_delimiter = cmd[delim_start:i]
                        if heredoc_delimiter:
                            in_heredoc = True
                else:
                    # Just a single < (input redirection)
                    current_cmd.append(char)
                    i += 1
            # Handle operators only when not in quotes AND not in compound command
            elif not in_double_quote and not in_single_quote and compound_depth == 0:
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

    def _parse_compound(self, cmd: str) -> Optional[CompoundInfo]:
        """Detect and parse compound commands (for/while/if/case/subshells).

        Args:
            cmd: The command string to check.

        Returns:
            CompoundInfo if this is a compound command, None otherwise.
        """
        cmd_stripped = cmd.strip()

        # Check for subshell: ( commands )
        if cmd_stripped.startswith("(") and cmd_stripped.endswith(")"):
            body = cmd_stripped[1:-1].strip()
            body_commands = [self.parse_single_command(c) for c in self.split_chain(body)]
            return CompoundInfo(
                compound_type=CompoundType.SUBSHELL,
                body=body,
                body_commands=body_commands,
            )

        # Check for brace group: { commands; }
        if cmd_stripped.startswith("{") and cmd_stripped.endswith("}"):
            body = cmd_stripped[1:-1].strip()
            body_commands = [self.parse_single_command(c) for c in self.split_chain(body)]
            return CompoundInfo(
                compound_type=CompoundType.BRACE_GROUP,
                body=body,
                body_commands=body_commands,
            )

        # Check for for loop: for VAR in LIST; do BODY; done
        for_match = re.match(
            r"^for\s+(\w+)\s+in\s+(.+?)\s*;\s*do\s+(.+?)\s*;\s*done$",
            cmd_stripped,
            re.DOTALL,
        )
        if for_match:
            variable, iterator, body = for_match.groups()
            body_commands = [self.parse_single_command(c) for c in self.split_chain(body)]
            return CompoundInfo(
                compound_type=CompoundType.FOR_LOOP,
                variable=variable,
                iterator=iterator,
                body=body,
                body_commands=body_commands,
            )

        # Check for while loop: while CONDITION; do BODY; done
        while_match = re.match(
            r"^while\s+(.+?)\s*;\s*do\s+(.+?)\s*;\s*done$",
            cmd_stripped,
            re.DOTALL,
        )
        if while_match:
            condition, body = while_match.groups()
            body_commands = [self.parse_single_command(c) for c in self.split_chain(body)]
            return CompoundInfo(
                compound_type=CompoundType.WHILE_LOOP,
                condition=condition,
                body=body,
                body_commands=body_commands,
            )

        # Check for until loop: until CONDITION; do BODY; done
        until_match = re.match(
            r"^until\s+(.+?)\s*;\s*do\s+(.+?)\s*;\s*done$",
            cmd_stripped,
            re.DOTALL,
        )
        if until_match:
            condition, body = until_match.groups()
            body_commands = [self.parse_single_command(c) for c in self.split_chain(body)]
            return CompoundInfo(
                compound_type=CompoundType.UNTIL_LOOP,
                condition=condition,
                body=body,
                body_commands=body_commands,
            )

        # Check for if statement: if CONDITION; then BODY; [else ELSE_BODY;] fi
        # IMPORTANT: Check if-else BEFORE simple if (more specific first)
        # If with else: if CONDITION; then BODY; else ELSE_BODY; fi
        if_else_match = re.match(
            r"^if\s+(.+?)\s*;\s*then\s+(.+?)\s*;\s*else\s+(.+?)\s*;\s*fi$",
            cmd_stripped,
            re.DOTALL,
        )
        if if_else_match:
            condition, body, else_body = if_else_match.groups()
            body_commands = [self.parse_single_command(c) for c in self.split_chain(body)]
            else_commands = [self.parse_single_command(c) for c in self.split_chain(else_body)]
            return CompoundInfo(
                compound_type=CompoundType.IF_STATEMENT,
                condition=condition,
                body=body,
                body_commands=body_commands,
                else_body=else_body,
                else_commands=else_commands,
            )

        # Simple if: if CONDITION; then BODY; fi
        if_simple_match = re.match(
            r"^if\s+(.+?)\s*;\s*then\s+(.+?)\s*;\s*fi$",
            cmd_stripped,
            re.DOTALL,
        )
        if if_simple_match:
            condition, body = if_simple_match.groups()
            body_commands = [self.parse_single_command(c) for c in self.split_chain(body)]
            return CompoundInfo(
                compound_type=CompoundType.IF_STATEMENT,
                condition=condition,
                body=body,
                body_commands=body_commands,
            )

        return None

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

        # Check if it's a compound command (for/while/if/subshell)
        compound_result = self._parse_compound(cmd)
        if compound_result:
            return CommandNode(
                type=CommandType.COMPOUND,
                name=compound_result.compound_type.value,
                compound=compound_result,
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
        elif node.type == CommandType.COMPOUND:
            return self._generate_compound_patterns(node)
        else:
            return self._generate_simple_patterns(node)

    def _generate_simple_patterns(self, node: CommandNode) -> List[str]:
        """Generate patterns for non-wrapper commands.

        Progressively trims args from the end, producing patterns at every
        intermediate level — same algorithm as wrapper patterns.

        For "git push origin main":
        1. git push origin main      (exact)
        2. git push origin main *    (exact + wildcard)
        3. git push origin *         (remote-specific)
        4. git push *                (subcommand)
        5. git *                     (command)

        Args:
            node: The CommandNode to generate patterns from.

        Returns:
            List of patterns from specific to general.
        """
        patterns = [node.full_cmd]

        if not node.name:
            return patterns

        parts = [node.name] + (node.args or [])

        for end in range(len(parts), 0, -1):
            prefix = " ".join(parts[:end])
            pattern = f"{prefix} *"
            if pattern not in patterns:
                patterns.append(pattern)

        return patterns

    def _generate_compound_patterns(self, node: CommandNode) -> List[str]:
        """Generate patterns for compound commands (loops, conditionals).

        For compound commands, we generate:
        1. Exact match of the full command
        2. Patterns for each inner command in the body

        This allows approving inner commands separately from the loop structure.

        Args:
            node: The CommandNode to generate patterns from.

        Returns:
            List of patterns from specific to general.
        """
        patterns = []

        # Pattern 1: Exact match of the full compound command
        patterns.append(node.full_cmd)

        # Generate patterns for inner body commands
        if node.compound and node.compound.body_commands:
            for inner_node in node.compound.body_commands:
                inner_patterns = self.generate_patterns(inner_node)
                for p in inner_patterns:
                    if p not in patterns:
                        patterns.append(p)

        # Generate patterns for else commands (if present)
        if node.compound and node.compound.else_commands:
            for inner_node in node.compound.else_commands:
                inner_patterns = self.generate_patterns(inner_node)
                for p in inner_patterns:
                    if p not in patterns:
                        patterns.append(p)

        return patterns

    def _generate_wrapper_patterns(self, node: CommandNode) -> List[str]:
        """Generate patterns for wrapper commands.

        Generates patterns at multiple levels of specificity by progressively
        trimming detail from the nested command structure.

        For "ssh aarni docker exec container bash":
        1. ssh aarni docker exec container bash    (exact)
        2. ssh aarni docker exec container bash *  (full chain + wildcard)
        3. ssh aarni docker exec container *       (inner wrapper + container)
        4. ssh aarni docker exec *                 (inner wrapper action)
        5. ssh aarni docker *                      (nested command name)
        6. ssh aarni *                             (outermost wrapper)

        For "ssh aarni ls /tmp":
        1. ssh aarni ls /tmp    (exact)
        2. ssh aarni ls /tmp *  (full chain + wildcard)
        3. ssh aarni ls *       (wrapper + nested command)
        4. ssh aarni *          (outermost wrapper)

        Args:
            node: The CommandNode to generate patterns from.

        Returns:
            List of patterns from specific to general.
        """
        patterns = []

        # Pattern 1: Exact match (needed for rule checking in check_chain_rules)
        patterns.append(node.full_cmd)

        # Build flat parts list and generate patterns by progressively trimming
        parts = self._build_wrapper_parts(node)

        # Minimum prefix length = wrapper name + its param count
        # (e.g., "ssh aarni" = 2, "docker exec container" = 3, "sudo" = 1)
        min_prefix_len = 1 + len(WRAPPERS[node.name]["param_keys"])

        # Generate patterns from most specific to least specific
        for end in range(len(parts), min_prefix_len - 1, -1):
            prefix = " ".join(parts[:end])
            pattern = f"{prefix} *"
            if pattern not in patterns:
                patterns.append(pattern)

        return patterns

    def _build_wrapper_parts(self, node: CommandNode) -> List[str]:
        """Build flat list of parts from wrapper chain for pattern generation.

        Traverses the nested wrapper structure and builds a flat list of
        meaningful parts (wrapper names, parameters, nested command name,
        and first argument).

        For "ssh aarni docker exec container bash":
        Returns: ["ssh", "aarni", "docker", "exec", "container", "bash"]

        For "ssh aarni ls /tmp":
        Returns: ["ssh", "aarni", "ls", "/tmp"]

        Args:
            node: The wrapper CommandNode to build parts from.

        Returns:
            Flat list of command parts.
        """
        parts = [node.name]
        for param_key in WRAPPERS[node.name]["param_keys"]:
            if param_key in node.params:
                parts.append(node.params[param_key])

        if node.nested:
            if node.nested.type == CommandType.WRAPPER:
                # Recurse into nested wrapper
                parts.extend(self._build_wrapper_parts(node.nested))
            elif node.nested.name:
                # Simple nested command - include name and first arg
                parts.append(node.nested.name)
                if node.nested.args:
                    parts.append(node.nested.args[0])

        return parts

    def get_compound_display_info(self, node: CommandNode) -> Optional[Dict]:
        """Get display info for compound commands.

        Returns structured info for UI display showing the compound structure
        and inner commands.

        Args:
            node: The CommandNode to get display info for.

        Returns:
            Dict with display info, or None if not a compound command.
        """
        if node.type != CommandType.COMPOUND or not node.compound:
            return None

        info = node.compound
        result = {
            "type": info.compound_type.value,
            "body_commands": [cmd.full_cmd for cmd in info.body_commands],
        }

        if info.compound_type == CompoundType.FOR_LOOP:
            result["description"] = f"for {info.variable} in {info.iterator}"
        elif info.compound_type == CompoundType.WHILE_LOOP:
            result["description"] = f"while {info.condition}"
        elif info.compound_type == CompoundType.UNTIL_LOOP:
            result["description"] = f"until {info.condition}"
        elif info.compound_type == CompoundType.IF_STATEMENT:
            result["description"] = f"if {info.condition}"
            if info.else_commands:
                result["else_commands"] = [cmd.full_cmd for cmd in info.else_commands]
        elif info.compound_type == CompoundType.SUBSHELL:
            result["description"] = "subshell"
        elif info.compound_type == CompoundType.BRACE_GROUP:
            result["description"] = "command group"

        return result

    def analyze_chain(self, cmd: str) -> ChainAnalysis:
        """Analyze a bash command's chain structure for approval.

        Single source of truth for how a command should be split into
        individually-approvable steps. Handles 3 cases in priority order:

        1. Single wrapper with inner chain → expand wrapper around each inner cmd
        2. Single compound command → extract inner commands
        3. Regular chain or single command → as-is

        Args:
            cmd: The complete bash command string.

        Returns:
            ChainAnalysis with steps, each containing a command string and parsed node.
        """
        # First, split at the top level
        top_parts = self.split_chain(cmd)

        # Case 1: Single command that might be a wrapper with inner chain
        if len(top_parts) == 1:
            result = self._expand_wrapper_chain(cmd)
            if result:
                return result

            # Case 2: Single compound command
            result = self._expand_compound(cmd)
            if result:
                return result

        # Case 3: Regular chain or single command — as-is
        steps = []
        for part in top_parts:
            node = self.parse_single_command(part)
            steps.append(ChainStep(command=part, node=node))

        return ChainAnalysis(original_cmd=cmd, steps=steps)

    def _expand_wrapper_chain(self, cmd: str) -> Optional[ChainAnalysis]:
        """Expand a wrapper command with an inner chain.

        For 'ssh aarni "cd /tmp && ls -la"', produces steps:
        - "ssh aarni cd /tmp" (wrapped)
        - "ssh aarni ls -la" (wrapped)
        With chain_title="ssh aarni".

        Returns None if not a wrapper or inner command is not a chain.
        """
        wrapper_info = self._parse_wrapper(cmd)
        if not wrapper_info or not wrapper_info["nested_cmd"]:
            return None

        nested_cmd = wrapper_info["nested_cmd"]

        # Guard: empty or whitespace-only nested command
        if not nested_cmd.strip():
            return None

        inner_parts = self.split_chain(nested_cmd)
        if len(inner_parts) <= 1:
            return None  # No inner chain to expand

        # Build wrapper prefix: "ssh aarni", "docker exec app", etc.
        wrapper_name = wrapper_info["name"]
        prefix_parts = [wrapper_name]
        for key in WRAPPERS[wrapper_name]["param_keys"]:
            if key in wrapper_info["params"]:
                prefix_parts.append(wrapper_info["params"][key])
        wrapper_prefix = " ".join(prefix_parts)

        # Build a ChainStep for each inner command, wrapped with prefix
        steps = []
        for inner_cmd in inner_parts:
            wrapped_cmd = f"{wrapper_prefix} {inner_cmd}"
            node = self.parse_single_command(wrapped_cmd)
            steps.append(ChainStep(command=wrapped_cmd, node=node))

        return ChainAnalysis(
            original_cmd=cmd,
            steps=steps,
            chain_title=wrapper_prefix,
        )

    def _expand_compound(self, cmd: str) -> Optional[ChainAnalysis]:
        """Expand a compound command (for/while/if) into inner commands.

        For 'for f in *.txt; do rm $f; done', produces steps for each
        inner body command, with chain_title describing the compound structure.

        Returns None if not a compound command.
        """
        node = self.parse_single_command(cmd)
        if node.type != CommandType.COMPOUND or not node.compound:
            return None

        inner_cmds = [c.full_cmd for c in node.compound.body_commands]
        if node.compound.else_commands:
            inner_cmds.extend([c.full_cmd for c in node.compound.else_commands])

        if not inner_cmds:
            return None

        # Build chain title from compound display info
        info = self.get_compound_display_info(node)
        chain_title = None
        if info:
            chain_title = f"{info['type'].capitalize()}: {info['description']}"

        steps = []
        for inner_cmd in inner_cmds:
            inner_node = self.parse_single_command(inner_cmd)
            steps.append(ChainStep(command=inner_cmd, node=inner_node))

        return ChainAnalysis(
            original_cmd=cmd,
            steps=steps,
            chain_title=chain_title,
        )


@dataclass
class ChainStep:
    """A single command in a chain analysis."""

    command: str  # Command string (wrapped for wrapper chains)
    node: CommandNode  # Parsed node for pattern generation


@dataclass
class ChainAnalysis:
    """Result of analyzing a bash command's chain structure.

    Single source of truth for how a command should be split into
    individually-approvable steps. Used by all 3 call sites:
    _check_rules(), check_chain_rules(), get_or_init_state().
    """

    original_cmd: str
    steps: List[ChainStep]
    chain_title: Optional[str] = None  # Wrapper prefix or compound description

    @property
    def is_chain(self) -> bool:
        return len(self.steps) > 1 or self.chain_title is not None

    @property
    def commands(self) -> List[str]:
        return [s.command for s in self.steps]

    @property
    def nodes(self) -> List[CommandNode]:
        return [s.node for s in self.steps]


@dataclass
class CompoundInfo:
    """Info about compound commands (loops, conditionals).

    Stores the structure of compound commands so we can extract and display
    the inner commands separately for approval.
    """

    compound_type: CompoundType
    variable: Optional[str] = None  # for loop variable (e.g., "x" in "for x in ...")
    iterator: Optional[str] = None  # for loop list (e.g., "*.txt" in "for x in *.txt")
    condition: Optional[str] = None  # while/until/if condition
    body: Optional[str] = None  # raw body string before parsing
    body_commands: List["CommandNode"] = field(default_factory=list)  # parsed inner commands
    else_body: Optional[str] = None  # else clause for if statements
    else_commands: List["CommandNode"] = field(default_factory=list)  # parsed else commands


@dataclass
class CommandNode:
    """A node in the command parse tree.

    Represents a single command that may contain nested commands (for wrappers)
    or compound structures (for loops, conditionals).
    """

    type: CommandType
    name: str
    args: List[str] = field(default_factory=list)
    params: Dict[str, str] = field(default_factory=dict)
    nested: Optional["CommandNode"] = None
    compound: Optional[CompoundInfo] = None  # for compound commands
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
