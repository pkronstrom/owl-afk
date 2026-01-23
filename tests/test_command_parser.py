"""Tests for command parser module."""

import pytest

from owl.core.command_parser import CommandNode, CommandParser, CommandType


def test_command_node_simple_command():
    """CommandNode should handle simple commands."""
    node = CommandNode(
        type=CommandType.GENERIC,
        name="echo",
        full_cmd="echo hello",
    )

    assert node.type == CommandType.GENERIC
    assert node.name == "echo"
    assert node.args == []
    assert node.params == {}
    assert node.nested is None
    assert node.full_cmd == "echo hello"


def test_command_node_with_nested():
    """CommandNode should handle nested commands in wrappers."""
    nested = CommandNode(
        type=CommandType.GENERIC,
        name="bash",
        args=["script.sh"],
        full_cmd="bash script.sh",
    )

    wrapper = CommandNode(
        type=CommandType.WRAPPER,
        name="ssh",
        args=["user@host"],
        params={"port": "2222"},
        nested=nested,
        full_cmd="ssh -p 2222 user@host bash script.sh",
    )

    assert wrapper.type == CommandType.WRAPPER
    assert wrapper.name == "ssh"
    assert wrapper.args == ["user@host"]
    assert wrapper.params == {"port": "2222"}
    assert wrapper.nested is not None
    assert wrapper.nested.name == "bash"
    assert wrapper.full_cmd == "ssh -p 2222 user@host bash script.sh"


def test_split_chain_single_command():
    """CommandParser should handle single commands."""
    parser = CommandParser()
    result = parser.split_chain("git log")
    assert len(result) == 1
    assert result[0] == "git log"


def test_split_chain_multiple_commands():
    """CommandParser should split multiple commands joined by &&."""
    parser = CommandParser()
    result = parser.split_chain("cd ~/project && npm test && git log")
    assert len(result) == 3
    assert result[0] == "cd ~/project"
    assert result[1] == "npm test"
    assert result[2] == "git log"


def test_split_chain_ignores_operators_in_quotes():
    """CommandParser should ignore operators inside quotes."""
    parser = CommandParser()
    result = parser.split_chain('ssh aarni "cd ~/p && git log"')
    assert len(result) == 1
    assert result[0] == 'ssh aarni "cd ~/p && git log"'


def test_split_chain_pipe_semicolon():
    """CommandParser should split on pipe and semicolon operators."""
    parser = CommandParser()
    result = parser.split_chain("cat file | grep pattern; echo done")
    assert len(result) == 3


def test_parse_wrapper_ssh():
    """CommandParser should detect ssh wrapper with host parameter."""
    parser = CommandParser()
    node = parser.parse_single_command("ssh aarni git log")

    assert node.type == CommandType.WRAPPER
    assert node.name == "ssh"
    assert node.params.get("host") == "aarni"
    assert node.nested is not None
    assert node.nested.name == "git"
    assert node.nested.type == CommandType.VCS


def test_parse_wrapper_docker():
    """CommandParser should detect docker wrapper with action and container params."""
    parser = CommandParser()
    node = parser.parse_single_command("docker exec mycontainer npm test")

    assert node.type == CommandType.WRAPPER
    assert node.name == "docker"
    assert node.params.get("action") == "exec"
    assert node.params.get("container") == "mycontainer"
    assert node.nested is not None
    assert node.nested.name == "npm"
    assert node.nested.type == CommandType.GENERIC


def test_detect_file_op():
    """CommandParser should detect file operation commands."""
    parser = CommandParser()
    node = parser.parse_single_command("rm file.txt")

    assert node.type == CommandType.FILE_OP
    assert node.name == "rm"
    assert node.args == ["file.txt"]
    assert node.nested is None


def test_detect_vcs_git():
    """CommandParser should detect git version control commands."""
    parser = CommandParser()
    node = parser.parse_single_command("git log")

    assert node.type == CommandType.VCS
    assert node.name == "git"
    assert node.args == ["log"]
    assert node.nested is None


def test_parse_single_command_simple():
    """parse() should parse simple commands into a single-element list."""
    parser = CommandParser()
    result = parser.parse("rm file.txt")

    assert len(result) == 1
    assert result[0].type == CommandType.FILE_OP
    assert result[0].name == "rm"
    assert result[0].args == ["file.txt"]


def test_parse_command_chain():
    """parse() should split command chains into separate CommandNode objects."""
    parser = CommandParser()
    result = parser.parse("cd ~/project && npm test && git log")

    assert len(result) == 3
    assert result[0].name == "cd"
    assert result[0].type == CommandType.GENERIC
    assert result[0].args == ["~/project"]

    assert result[1].name == "npm"
    assert result[1].type == CommandType.GENERIC
    assert result[1].args == ["test"]

    assert result[2].name == "git"
    assert result[2].type == CommandType.VCS
    assert result[2].args == ["log"]


def test_parse_ssh_with_chain():
    """parse() should handle ssh wrapper with nested chain as single node."""
    parser = CommandParser()
    result = parser.parse('ssh aarni "cd ~/p && git log"')

    assert len(result) == 1
    assert result[0].type == CommandType.WRAPPER
    assert result[0].name == "ssh"
    assert result[0].params.get("host") == "aarni"
    assert result[0].nested is not None
    assert result[0].nested.name == "cd"


def test_parse_pipe_command():
    """parse() should split piped commands into separate CommandNode objects."""
    parser = CommandParser()
    result = parser.parse("cat file | grep pattern")

    assert len(result) == 2
    assert result[0].name == "cat"
    assert result[0].type == CommandType.FILE_OP
    assert result[0].args == ["file"]

    assert result[1].name == "grep"
    assert result[1].type == CommandType.FILE_OP
    assert result[1].args == ["pattern"]


def test_generate_patterns_simple_command():
    """generate_patterns should create patterns from specific to general for simple commands."""
    parser = CommandParser()
    node = parser.parse_single_command("rm file.txt")

    patterns = parser.generate_patterns(node)

    # Simplified: exact, "rm file.txt *", "rm *"
    assert len(patterns) == 3
    assert patterns[0] == "rm file.txt"
    assert patterns[1] == "rm file.txt *"
    assert patterns[2] == "rm *"


def test_generate_patterns_file_op():
    """generate_patterns should handle file operations with multiple arguments."""
    parser = CommandParser()
    node = parser.parse_single_command("cp file1 file2")

    patterns = parser.generate_patterns(node)

    # Should generate: exact, "cp file1 *", "cp *"
    assert len(patterns) == 3
    assert patterns[0] == "cp file1 file2"
    assert patterns[1] == "cp file1 *"
    assert patterns[2] == "cp *"


def test_generate_patterns_vcs():
    """generate_patterns should handle VCS commands."""
    parser = CommandParser()
    node = parser.parse_single_command("git log")

    patterns = parser.generate_patterns(node)

    # Simplified: exact, "git log *", "git *"
    assert len(patterns) == 3
    assert patterns[0] == "git log"
    assert patterns[1] == "git log *"
    assert patterns[2] == "git *"


def test_generate_patterns_generic():
    """generate_patterns should handle generic commands."""
    parser = CommandParser()
    node = parser.parse_single_command("npm test")

    patterns = parser.generate_patterns(node)

    # Simplified: exact, "npm test *", "npm *"
    assert len(patterns) == 3
    assert patterns[0] == "npm test"
    assert patterns[1] == "npm test *"
    assert patterns[2] == "npm *"


def test_generate_patterns_wrapper_ssh():
    """generate_patterns should handle ssh wrapper with nested command."""
    parser = CommandParser()
    node = parser.parse_single_command("ssh aarni git log")

    patterns = parser.generate_patterns(node)

    # Simplified wrappers: exact, full chain + *, outer + *
    assert len(patterns) == 3
    assert patterns[0] == "ssh aarni git log"
    assert patterns[1] == "ssh aarni git log *"
    assert patterns[2] == "ssh aarni *"


def test_generate_patterns_wrapper_docker():
    """generate_patterns should handle docker wrapper with nested command."""
    parser = CommandParser()
    node = parser.parse_single_command("docker exec myapp npm test")

    patterns = parser.generate_patterns(node)

    # Simplified wrappers: exact, full chain + *, outer + *
    assert len(patterns) == 3
    assert patterns[0] == "docker exec myapp npm test"
    assert patterns[1] == "docker exec myapp npm test *"
    assert patterns[2] == "docker exec myapp *"


# --- Tests for ENV variable prefixes ---


def test_parse_command_with_single_env_var():
    """parse_single_command should skip leading env var and identify actual command."""
    parser = CommandParser()
    node = parser.parse_single_command("FOO=bar uv run python script.py")

    assert node.type == CommandType.GENERIC
    assert node.name == "uv"
    assert node.args == ["run", "python", "script.py"]
    assert node.full_cmd == "FOO=bar uv run python script.py"


def test_parse_command_with_multiple_env_vars():
    """parse_single_command should skip multiple leading env vars."""
    parser = CommandParser()
    node = parser.parse_single_command(
        "REPORT_SERVER_PORT=8099 ARTIFACTS_DIR=./artifacts DATA_DIR=./data uv run python scripts/server.py"
    )

    assert node.type == CommandType.GENERIC
    assert node.name == "uv"
    assert node.args == ["run", "python", "scripts/server.py"]


def test_parse_env_var_with_wrapper():
    """parse_single_command should handle env vars before wrapper commands."""
    parser = CommandParser()
    node = parser.parse_single_command("MY_VAR=test ssh host git status")

    assert node.type == CommandType.WRAPPER
    assert node.name == "ssh"
    assert node.params.get("host") == "host"
    assert node.nested is not None
    assert node.nested.name == "git"
    assert node.nested.type == CommandType.VCS


def test_generate_patterns_with_env_var():
    """generate_patterns should work correctly when command has env var prefix."""
    parser = CommandParser()
    node = parser.parse_single_command("FOO=bar git status")

    patterns = parser.generate_patterns(node)

    # Should generate patterns for git, not FOO=bar
    assert len(patterns) == 3
    assert patterns[0] == "FOO=bar git status"  # exact match still includes env vars
    assert patterns[1] == "git status *"
    assert patterns[2] == "git *"


def test_parse_env_var_only():
    """parse_single_command should handle commands that are only env vars."""
    parser = CommandParser()
    node = parser.parse_single_command("FOO=bar BAZ=qux")

    # All tokens are env vars - no actual command
    assert node.type == CommandType.GENERIC
    assert node.name == ""
    assert node.args == []


def test_is_env_assignment():
    """_is_env_assignment should correctly identify env var patterns."""
    parser = CommandParser()

    # Valid env var assignments
    assert parser._is_env_assignment("FOO=bar") is True
    assert parser._is_env_assignment("_VAR=value") is True
    assert parser._is_env_assignment("MY_VAR_123=test") is True
    assert parser._is_env_assignment("A=b") is True
    assert parser._is_env_assignment("PATH+=:/usr/local/bin") is True  # Append syntax

    # Not env var assignments
    assert parser._is_env_assignment("git") is False
    assert parser._is_env_assignment("123=bad") is False  # Can't start with digit
    assert parser._is_env_assignment("=value") is False  # No name
    assert parser._is_env_assignment("ssh") is False


# --- Tests for bash comments ---


def test_parse_comment_only():
    """parse_single_command should handle comment-only lines."""
    parser = CommandParser()
    node = parser.parse_single_command("# this is a comment")

    assert node.type == CommandType.GENERIC
    assert node.name == ""
    assert node.full_cmd == "# this is a comment"


def test_parse_comment_with_whitespace():
    """parse_single_command should handle comments with leading whitespace after strip."""
    parser = CommandParser()
    node = parser.parse_single_command("  # indented comment  ")

    assert node.type == CommandType.GENERIC
    assert node.name == ""


def test_split_chain_preserves_newlines():
    """split_chain does not split on newlines (only &&, ||, ;, |).

    Note: Newlines in bash are statement separators, but split_chain only
    handles explicit chain operators. Comment handling happens in parse().
    """
    parser = CommandParser()
    result = parser.split_chain("# comment\ngit status")

    # Newlines are NOT chain separators in split_chain
    assert len(result) == 1


def test_parse_chain_with_semicolon_comment():
    """parse() should handle chains that include comments."""
    parser = CommandParser()
    # "true" is often used to start a chain that has comments
    result = parser.parse("true; # just a comment; git status")

    assert len(result) == 3
    assert result[0].name == "true"
    assert result[1].name == ""  # comment
    assert result[2].name == "git"
