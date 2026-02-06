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


# --- Tests for heredoc handling ---


def test_split_chain_heredoc_with_single_quoted_delimiter():
    """split_chain should not split on operators inside single-quoted heredocs."""
    parser = CommandParser()
    cmd = """set -a; source .env; set +a; uv run python << 'EOF'
data.filter(pl.col("a") > 0 | pl.col("b") < 0)
EOF"""

    result = parser.split_chain(cmd)

    assert len(result) == 4
    assert result[0] == "set -a"
    assert result[1] == "source .env"
    assert result[2] == "set +a"
    # The heredoc content should be kept intact with the | preserved
    assert "| pl.col" in result[3]
    assert result[3].startswith("uv run python << 'EOF'")


def test_split_chain_heredoc_with_double_quoted_delimiter():
    """split_chain should not split on operators inside double-quoted heredocs."""
    parser = CommandParser()
    cmd = '''echo start; cat << "END"
line with | pipe and ; semicolon && and
END'''

    result = parser.split_chain(cmd)

    assert len(result) == 2
    assert result[0] == "echo start"
    assert "| pipe" in result[1]
    assert "; semicolon" in result[1]
    assert "&& and" in result[1]


def test_split_chain_heredoc_with_unquoted_delimiter():
    """split_chain should not split on operators inside unquoted heredocs."""
    parser = CommandParser()
    cmd = """cmd1; cat << MARKER
content with | and ; and && operators
MARKER"""

    result = parser.split_chain(cmd)

    assert len(result) == 2
    assert result[0] == "cmd1"
    assert "| and" in result[1]


def test_split_chain_heredoc_with_dash():
    """split_chain should handle <<- heredocs (tab stripping variant)."""
    parser = CommandParser()
    cmd = """cmd1; cat <<- EOF
	content with | pipe
	EOF"""

    result = parser.split_chain(cmd)

    assert len(result) == 2
    assert result[0] == "cmd1"
    assert "| pipe" in result[1]


def test_split_chain_multiple_heredocs():
    """split_chain should handle multiple heredocs in a chain."""
    parser = CommandParser()
    cmd = """cat << 'A'
first | content
A
cat << 'B'
second | content
B"""

    result = parser.split_chain(cmd)

    # Both heredocs are separate newline-separated statements, but split_chain
    # doesn't split on newlines alone - the newline after EOF A triggers continuation
    # Actually, after the first EOF, we're no longer in heredoc and newline isn't a split
    assert len(result) == 1  # Newlines alone don't split


def test_split_chain_heredoc_followed_by_chain():
    """split_chain should correctly split after heredoc ends."""
    parser = CommandParser()
    cmd = """cat << 'EOF'
heredoc content with | pipe
EOF
&& echo done"""

    result = parser.split_chain(cmd)

    assert len(result) == 2
    assert "| pipe" in result[0]  # pipe preserved in heredoc
    assert result[1] == "echo done"


def test_split_chain_single_redirect_not_heredoc():
    """split_chain should not treat single < as heredoc."""
    parser = CommandParser()
    result = parser.split_chain("grep pattern < file | sort")

    assert len(result) == 2
    assert result[0] == "grep pattern < file"
    assert result[1] == "sort"


def test_split_chain_real_world_python_heredoc():
    """Test with real-world Python code containing Polars expressions."""
    parser = CommandParser()
    cmd = """set -a; source .env; set +a; uv run python << 'EOF'
import polars as pl

df = pl.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
result = df.filter(
    (pl.col("a") > 1) | (pl.col("b") < 6)
).select([
    pl.col("a"),
    pl.col("b")
])
print(result)
EOF"""

    result = parser.split_chain(cmd)

    assert len(result) == 4
    assert result[0] == "set -a"
    assert result[1] == "source .env"
    assert result[2] == "set +a"
    # All the Python code with | operators should be in the last command
    assert "(pl.col(\"a\") > 1) | (pl.col(\"b\") < 6)" in result[3]


# --- Tests for compound commands (for/while/if/subshell) ---


def test_parse_for_loop():
    """parse_single_command should detect for loops and extract body."""
    from owl.core.command_parser import CompoundType

    parser = CommandParser()
    node = parser.parse_single_command("for f in *.txt; do rm $f; done")

    assert node.type == CommandType.COMPOUND
    assert node.name == "for"
    assert node.compound is not None
    assert node.compound.compound_type == CompoundType.FOR_LOOP
    assert node.compound.variable == "f"
    assert node.compound.iterator == "*.txt"
    assert node.compound.body == "rm $f"
    assert len(node.compound.body_commands) == 1
    assert node.compound.body_commands[0].name == "rm"


def test_parse_for_loop_with_chain_body():
    """For loop body with multiple chained commands."""
    from owl.core.command_parser import CompoundType

    parser = CommandParser()
    node = parser.parse_single_command("for x in a b c; do echo $x && touch $x; done")

    assert node.type == CommandType.COMPOUND
    assert node.compound.compound_type == CompoundType.FOR_LOOP
    assert node.compound.variable == "x"
    assert node.compound.iterator == "a b c"
    # Body has chain: "echo $x && touch $x" splits to 2 commands
    assert len(node.compound.body_commands) == 2
    assert node.compound.body_commands[0].name == "echo"
    assert node.compound.body_commands[1].name == "touch"


def test_parse_while_loop():
    """parse_single_command should detect while loops."""
    from owl.core.command_parser import CompoundType

    parser = CommandParser()
    node = parser.parse_single_command("while true; do sleep 1; done")

    assert node.type == CommandType.COMPOUND
    assert node.name == "while"
    assert node.compound is not None
    assert node.compound.compound_type == CompoundType.WHILE_LOOP
    assert node.compound.condition == "true"
    assert node.compound.body == "sleep 1"
    assert len(node.compound.body_commands) == 1
    assert node.compound.body_commands[0].name == "sleep"


def test_parse_while_with_condition():
    """While loop with a test condition."""
    from owl.core.command_parser import CompoundType

    parser = CommandParser()
    node = parser.parse_single_command('while [ -f /tmp/lock ]; do sleep 5; done')

    assert node.type == CommandType.COMPOUND
    assert node.compound.compound_type == CompoundType.WHILE_LOOP
    assert node.compound.condition == "[ -f /tmp/lock ]"
    assert node.compound.body_commands[0].name == "sleep"


def test_parse_until_loop():
    """parse_single_command should detect until loops."""
    from owl.core.command_parser import CompoundType

    parser = CommandParser()
    node = parser.parse_single_command("until false; do echo waiting; done")

    assert node.type == CommandType.COMPOUND
    assert node.compound.compound_type == CompoundType.UNTIL_LOOP
    assert node.compound.condition == "false"
    assert len(node.compound.body_commands) == 1
    assert node.compound.body_commands[0].name == "echo"


def test_parse_if_simple():
    """parse_single_command should detect simple if statements."""
    from owl.core.command_parser import CompoundType

    parser = CommandParser()
    node = parser.parse_single_command("if [ -f file ]; then cat file; fi")

    assert node.type == CommandType.COMPOUND
    assert node.name == "if"
    assert node.compound is not None
    assert node.compound.compound_type == CompoundType.IF_STATEMENT
    assert node.compound.condition == "[ -f file ]"
    assert node.compound.body == "cat file"
    assert len(node.compound.body_commands) == 1
    assert node.compound.body_commands[0].name == "cat"
    assert node.compound.else_commands == []


def test_parse_if_else():
    """parse_single_command should detect if-else statements."""
    from owl.core.command_parser import CompoundType

    parser = CommandParser()
    node = parser.parse_single_command("if [ -d dir ]; then ls dir; else mkdir dir; fi")

    assert node.type == CommandType.COMPOUND
    assert node.compound.compound_type == CompoundType.IF_STATEMENT
    assert node.compound.condition == "[ -d dir ]"
    assert len(node.compound.body_commands) == 1
    assert node.compound.body_commands[0].name == "ls"
    assert len(node.compound.else_commands) == 1
    assert node.compound.else_commands[0].name == "mkdir"


def test_parse_subshell():
    """parse_single_command should detect subshells."""
    from owl.core.command_parser import CompoundType

    parser = CommandParser()
    node = parser.parse_single_command("( cd /tmp && ls )")

    assert node.type == CommandType.COMPOUND
    assert node.name == "subshell"
    assert node.compound is not None
    assert node.compound.compound_type == CompoundType.SUBSHELL
    assert len(node.compound.body_commands) == 2
    assert node.compound.body_commands[0].name == "cd"
    assert node.compound.body_commands[1].name == "ls"


def test_parse_brace_group():
    """parse_single_command should detect brace groups."""
    from owl.core.command_parser import CompoundType

    parser = CommandParser()
    node = parser.parse_single_command("{ echo start; do_work; echo end; }")

    assert node.type == CommandType.COMPOUND
    assert node.name == "brace_group"
    assert node.compound is not None
    assert node.compound.compound_type == CompoundType.BRACE_GROUP
    assert len(node.compound.body_commands) == 3
    assert node.compound.body_commands[0].name == "echo"
    assert node.compound.body_commands[1].name == "do_work"
    assert node.compound.body_commands[2].name == "echo"


def test_generate_patterns_for_loop():
    """generate_patterns should include patterns for inner commands."""
    parser = CommandParser()
    node = parser.parse_single_command("for f in *.log; do rm $f; done")

    patterns = parser.generate_patterns(node)

    # Should include exact match and inner command patterns
    assert "for f in *.log; do rm $f; done" in patterns
    assert "rm $f" in patterns
    assert "rm *" in patterns


def test_generate_patterns_if_else():
    """generate_patterns should include patterns for both branches."""
    parser = CommandParser()
    node = parser.parse_single_command("if [ -f x ]; then cat x; else touch x; fi")

    patterns = parser.generate_patterns(node)

    # Should have exact match + patterns from both branches
    assert "if [ -f x ]; then cat x; else touch x; fi" in patterns
    assert "cat x" in patterns
    assert "cat *" in patterns
    assert "touch x" in patterns
    assert "touch *" in patterns


def test_compound_display_info_for_loop():
    """get_compound_display_info should return structured info for UI."""
    parser = CommandParser()
    node = parser.parse_single_command("for f in *.txt; do rm $f; done")

    info = parser.get_compound_display_info(node)

    assert info is not None
    assert info["type"] == "for"
    assert info["description"] == "for f in *.txt"
    assert info["body_commands"] == ["rm $f"]


def test_compound_display_info_while():
    """get_compound_display_info should return info for while loops."""
    parser = CommandParser()
    node = parser.parse_single_command("while true; do sleep 1; done")

    info = parser.get_compound_display_info(node)

    assert info is not None
    assert info["type"] == "while"
    assert info["description"] == "while true"
    assert info["body_commands"] == ["sleep 1"]


def test_compound_display_info_if_else():
    """get_compound_display_info should include else commands."""
    parser = CommandParser()
    node = parser.parse_single_command("if [ -f x ]; then cat x; else touch x; fi")

    info = parser.get_compound_display_info(node)

    assert info is not None
    assert info["type"] == "if"
    assert "if [ -f x ]" in info["description"]
    assert info["body_commands"] == ["cat x"]
    assert info["else_commands"] == ["touch x"]


def test_compound_in_chain():
    """Compound commands should work within chains."""
    parser = CommandParser()
    nodes = parser.parse("echo start && for f in *.txt; do rm $f; done && echo end")

    assert len(nodes) == 3
    assert nodes[0].name == "echo"
    assert nodes[1].type == CommandType.COMPOUND
    assert nodes[1].compound.compound_type.value == "for"
    assert nodes[2].name == "echo"


def test_non_compound_not_detected():
    """Regular commands should not be detected as compound."""
    parser = CommandParser()

    # These look similar but aren't compound commands
    node1 = parser.parse_single_command("fortune")
    assert node1.type != CommandType.COMPOUND

    node2 = parser.parse_single_command("while-game --level 5")
    assert node2.type != CommandType.COMPOUND

    node3 = parser.parse_single_command("if-then-else arg1 arg2")
    assert node3.type != CommandType.COMPOUND
