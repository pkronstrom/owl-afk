"""Auto-approve rules engine."""

import json
import re
import time
from typing import Optional

from pyafk.core.storage import Storage


def matches_pattern(tool_call: str, pattern: str) -> bool:
    """Check if a tool call matches a pattern.

    Patterns can be:
    - Exact: "Read" matches "Read"
    - Wildcard: "Bash(git *)" matches "Bash(git status)"
    - Glob: "Read(*.py)" matches "Read(/path/to/file.py)"
    """
    if not pattern:
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
    - ("Read", '{"file_path": "/foo/bar.py"}') -> "Read(/foo/bar.py)"
    - ("Edit", '{"file_path": "/x.py", "old": "a"}') -> "Edit(/x.py)"
    """
    if not tool_input:
        return tool_name

    try:
        data = json.loads(tool_input)
    except (json.JSONDecodeError, TypeError):
        return tool_name

    # Extract the most relevant field for matching
    if "command" in data:
        return f"{tool_name}({data['command']})"
    elif "file_path" in data:
        return f"{tool_name}({data['file_path']})"
    elif "path" in data:
        return f"{tool_name}({data['path']})"
    elif "url" in data:
        return f"{tool_name}({data['url']})"

    return tool_name


class RulesEngine:
    """Evaluate auto-approve rules against tool calls."""

    def __init__(self, storage: Storage):
        self.storage = storage

    async def check(self, tool_name: str, tool_input: Optional[str] = None) -> Optional[str]:
        """Check if a tool call matches any rule.

        Returns:
            "approve", "deny", or None if no rule matches
        """
        tool_call = format_tool_call(tool_name, tool_input)

        # Load rules (sorted by priority descending)
        cursor = await self.storage._conn.execute(
            "SELECT pattern, action FROM auto_approve_rules ORDER BY priority DESC"
        )
        rules = await cursor.fetchall()

        for row in rules:
            if matches_pattern(tool_call, row["pattern"]):
                return row["action"]

        return None

    async def add_rule(
        self,
        pattern: str,
        action: str = "approve",
        priority: int = 0,
        created_via: str = "cli",
    ) -> int:
        """Add a new rule."""
        if action not in ("approve", "deny"):
            raise ValueError(f"Invalid action: {action}")
        if not pattern:
            raise ValueError("Pattern cannot be empty")

        cursor = await self.storage._conn.execute(
            """
            INSERT INTO auto_approve_rules (pattern, action, priority, created_via, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (pattern, action, priority, created_via, time.time()),
        )
        await self.storage._conn.commit()
        return cursor.lastrowid

    async def remove_rule(self, rule_id: int) -> bool:
        """Remove a rule by ID."""
        cursor = await self.storage._conn.execute(
            "DELETE FROM auto_approve_rules WHERE id = ?", (rule_id,)
        )
        await self.storage._conn.commit()
        return cursor.rowcount > 0

    async def list_rules(self) -> list[dict]:
        """List all rules."""
        cursor = await self.storage._conn.execute(
            "SELECT * FROM auto_approve_rules ORDER BY priority DESC, id"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
