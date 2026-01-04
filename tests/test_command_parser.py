"""Tests for command parser module."""

import pytest

from pyafk.core.command_parser import CommandNode, CommandParser, CommandType


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
