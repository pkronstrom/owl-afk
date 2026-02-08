"""Pattern generation utilities for rule creation."""

import json
import os
from typing import Optional

from owl.core.command_parser import CommandParser


def strip_leading_comments(cmd: str) -> str:
    """Strip leading comment lines from a command.

    Bash commands can have comment lines at the start for documentation:
        # Check a sell signal's category scores
        sqlite3 data/store.db "SELECT ..."

    This strips leading lines that start with # so patterns are generated
    from the actual command, not the comments.

    Args:
        cmd: The command string, potentially with leading comments.

    Returns:
        The command with leading comment lines removed.
    """
    lines = cmd.split("\n")
    # Find first non-comment, non-empty line
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            # Return from this line onwards
            return "\n".join(lines[i:])
    # All lines are comments or empty - return original
    return cmd


def generate_rule_patterns(
    tool_name: str,
    tool_input: Optional[str],
    project_path: Optional[str] = None,
) -> list[tuple[str, str]]:
    """Generate rule pattern options with labels.

    Args:
        tool_name: Name of the tool (Bash, Edit, Read, etc.)
        tool_input: JSON string of tool input
        project_path: Optional project path for directory-scoped patterns

    Returns:
        List of (pattern, label) tuples for rule creation UI.
    """
    patterns: list[tuple[str, str]] = []

    if not tool_input:
        return [(f"{tool_name}(*)", f"Any {tool_name}")]

    try:
        data = json.loads(tool_input)
    except (json.JSONDecodeError, TypeError):
        return [(f"{tool_name}(*)", f"Any {tool_name}")]

    # For Bash commands - use CommandParser for rich pattern generation
    if tool_name == "Bash" and "command" in data:
        cmd = data["command"].strip()

        # Strip leading comment lines so patterns are based on actual commands
        cmd = strip_leading_comments(cmd)

        try:
            # Parse the command using CommandParser
            parser = CommandParser()
            nodes = parser.parse(cmd)

            # Generate patterns from all parsed nodes
            all_patterns = []
            for node in nodes:
                node_patterns = parser.generate_patterns(node)
                all_patterns.extend(node_patterns)

            # Convert raw patterns to (pattern, label) tuples with Bash() wrapping
            for pattern in all_patterns:
                if pattern:  # Skip empty patterns
                    # Create a label based on whether it's an exact command or wildcard
                    if pattern.endswith("*"):
                        label = f"~ {pattern}"
                    elif " " in pattern:
                        label = f"· {pattern[:50]}"  # Truncate long commands for label
                    else:
                        label = f"· {pattern}"

                    patterns.append((f"Bash({pattern})", label))

            if patterns:
                # Remove duplicates while preserving order
                seen: set[str] = set()
                unique: list[tuple[str, str]] = []
                for pattern, label in patterns:
                    if pattern not in seen:
                        seen.add(pattern)
                        unique.append((pattern, label))
                return unique
        except Exception:
            # Fallback to basic pattern if parsing fails
            pass

        # Fallback if parsing fails or no patterns generated
        return [
            (f"Bash({cmd})", "· This exact command"),
            ("Bash(*)", "~ Any Bash"),
        ]

    # For Edit/Write - file patterns
    if tool_name in ("Edit", "Write") and "file_path" in data:
        path = os.path.expanduser(data["file_path"])
        filename = path.rsplit("/", 1)[-1] if "/" in path else path

        patterns.append((f"{tool_name}({path})", f"· {filename}"))

        if "." in path:
            ext = path.rsplit(".", 1)[-1]
            patterns.append((f"{tool_name}(*.{ext})", f"· Any *.{ext}"))

        if "/" in path:
            dir_path = path.rsplit("/", 1)[0]
            short_dir = dir_path.split("/")[-1] or dir_path
            # Use wildcard prefix so pattern works across worktrees/machines
            patterns.append(
                (f"{tool_name}(*/{short_dir}/*)", f"/ Any in .../{short_dir}/")
            )
            # Also add pattern for relative paths (without leading */)
            # This matches paths like "dodo/file.txt" where there's no / before the dir
            if not path.startswith("/"):
                patterns.append(
                    (f"{tool_name}({short_dir}/*)", f"/ Any in {short_dir}/")
                )

        # Add project-scoped pattern if project_path is available
        if project_path and path.startswith(project_path):
            project_name = project_path.rstrip("/").split("/")[-1]
            if "." in path:
                ext = path.rsplit(".", 1)[-1]
                patterns.append(
                    (
                        f"{tool_name}(*/{project_name}/*.{ext})",
                        f"/ Any *.{ext} in {project_name}/",
                    )
                )
            # Use wildcard prefix so pattern works across worktrees/machines
            patterns.append(
                (f"{tool_name}(*/{project_name}/*)", f"/ Any in {project_name}/")
            )

        patterns.append((f"{tool_name}(*)", f"* Any {tool_name}"))

    # For Read - directory patterns
    elif tool_name == "Read" and "file_path" in data:
        path = os.path.expanduser(data["file_path"])
        filename = path.rsplit("/", 1)[-1] if "/" in path else path

        patterns.append((f"Read({path})", f"· {filename}"))

        if "/" in path:
            dir_path = path.rsplit("/", 1)[0]
            short_dir = dir_path.split("/")[-1] or dir_path
            # Use wildcard prefix so pattern works across worktrees/machines
            patterns.append((f"Read(*/{short_dir}/*)", f"/ Any in .../{short_dir}/"))

        # Add project-scoped pattern if project_path is available
        if project_path and path.startswith(project_path):
            project_name = project_path.rstrip("/").split("/")[-1]
            # Use wildcard prefix so pattern works across worktrees/machines
            patterns.append((f"Read(*/{project_name}/*)", f"/ Any in {project_name}/"))

        patterns.append(("Read(*)", "* Any Read"))

    # For Glob/Search and other tools using 'path' field
    elif "path" in data:
        path = os.path.expanduser(data["path"])

        if "/" in path:
            short_dir = path.rstrip("/").split("/")[-1] or path
            # Use wildcard prefix so pattern works across worktrees/machines
            patterns.append(
                (f"{tool_name}(*/{short_dir}/*)", f"/ Any in .../{short_dir}/")
            )

        # Add project-scoped pattern if project_path is available
        if project_path and path.startswith(project_path):
            project_name = project_path.rstrip("/").split("/")[-1]
            patterns.append(
                (f"{tool_name}(*/{project_name}/*)", f"/ Any in {project_name}/")
            )

        patterns.append((f"{tool_name}(*)", f"* Any {tool_name}"))

    # For other tools
    else:
        patterns.append((f"{tool_name}(*)", f"* Any {tool_name}"))

    # Remove duplicates while preserving order (by pattern)
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for pattern, label in patterns:
        if pattern not in seen:
            seen.add(pattern)
            unique.append((pattern, label))

    return unique
