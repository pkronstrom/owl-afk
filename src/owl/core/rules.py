"""Auto-approve rules engine."""

import json
import re
from typing import Any, Optional

from owl.core.storage import Storage


MAX_PATTERN_LENGTH = 500  # Limit pattern length to prevent ReDoS attacks


def normalize_command_for_matching(cmd: str) -> str:
    """Normalize a command string for pattern matching.

    Strips outer quotes from command arguments to match how patterns are generated.
    For example: ssh aarni 'docker exec bouillon...' -> ssh aarni docker exec bouillon...

    This ensures commands match patterns regardless of quoting style.
    """
    # Use the same smart split logic as CommandParser to handle quotes properly
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
            # Don't include the quote in the token
            i += 1
        elif char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            # Don't include the quote in the token
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

    return " ".join(tokens)


def matches_pattern(tool_call: str, pattern: str) -> bool:
    """Check if a tool call matches a pattern.

    Patterns can be:
    - Exact: "Read" matches "Read"
    - Wildcard: "Bash(git *)" matches "Bash(git status)"
    - Glob: "Read(*.py)" matches "Read(/path/to/file.py)"
    """
    if not pattern:
        return False

    # Limit pattern length to prevent ReDoS
    if len(pattern) > MAX_PATTERN_LENGTH:
        return False

    # Convert pattern to regex
    # Escape special regex chars except * and ?
    regex_pattern = ""
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            regex_pattern += ".*"
        elif c == "?":
            regex_pattern += "."
        elif c in ".^$+{}[]|()":
            regex_pattern += "\\" + c
        else:
            regex_pattern += c
        i += 1

    regex_pattern = "^" + regex_pattern + "$"
    return bool(re.match(regex_pattern, tool_call, re.IGNORECASE))


def format_tool_call(tool_name: str, tool_input: Optional[str]) -> str:
    """Format tool name and input for pattern matching.

    Examples:
    - ("Bash", '{"command": "git status"}') -> "Bash(git status)"
    - ("Bash", '{"command": "ssh host 'cmd'"}') -> "Bash(ssh host cmd)"  # quotes stripped
    - ("Read", '{"file_path": "/foo/bar.py"}') -> "Read(/foo/bar.py)"
    - ("Edit", '{"file_path": "/x.py", "old": "a"}') -> "Edit(/x.py)"
    - ("TodoWrite", '{"todos": [...]}') -> "TodoWrite(...)"
    """
    if not tool_input:
        return f"{tool_name}()"

    try:
        data = json.loads(tool_input)
    except (json.JSONDecodeError, TypeError):
        return f"{tool_name}()"

    # Extract the most relevant field for matching
    if "command" in data:
        # Normalize command to strip quotes for consistent pattern matching
        normalized_cmd = normalize_command_for_matching(data["command"])
        return f"{tool_name}({normalized_cmd})"
    elif "file_path" in data:
        return f"{tool_name}({data['file_path']})"
    elif "path" in data:
        return f"{tool_name}({data['path']})"
    elif "url" in data:
        return f"{tool_name}({data['url']})"

    # For tools without specific fields, use empty parens to match patterns like Tool(*)
    return f"{tool_name}()"


class RulesEngine:
    """Evaluate auto-approve rules against tool calls."""

    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    async def check(self, tool_name: str, tool_input: Optional[str] = None) -> Optional[str]:
        """Check if a tool call matches any rule.

        Returns:
            "approve", "deny", or None if no rule matches
        """
        tool_call = format_tool_call(tool_name, tool_input)

        # Load rules (sorted by priority descending)
        rules = await self.storage.get_rules_for_matching()

        for pattern, action in rules:
            if matches_pattern(tool_call, pattern):
                return action

        return None

    async def add_rule(
        self,
        pattern: str,
        action: str = "approve",
        priority: int = 0,
        created_via: str = "cli",
    ) -> int:
        """Add a new rule. Returns existing rule ID if duplicate."""
        if action not in ("approve", "deny"):
            raise ValueError(f"Invalid action: {action}")
        if not pattern:
            raise ValueError("Pattern cannot be empty")
        if len(pattern) > MAX_PATTERN_LENGTH:
            raise ValueError(f"Pattern too long (max {MAX_PATTERN_LENGTH} chars)")

        # Check for existing rule with same pattern and action
        existing = await self.storage.get_rule_by_pattern(pattern, action)
        if existing:
            return int(existing["id"])  # Return existing rule ID

        return await self.storage.add_rule(pattern, action, priority, created_via)

    async def remove_rule(self, rule_id: int) -> bool:
        """Remove a rule by ID."""
        return await self.storage.remove_rule(rule_id)

    async def list_rules(self) -> list[dict[str, Any]]:
        """List all rules."""
        return await self.storage.get_rules()
