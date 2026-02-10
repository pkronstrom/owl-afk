"""Tests for language detection utilities."""

from owl.utils.languages import detect_bash_language, detect_file_language


def test_detect_python_command():
    assert detect_bash_language("python train.py") == "python"


def test_detect_python3_command():
    assert detect_bash_language("python3 -m pytest") == "python"


def test_detect_node_command():
    assert detect_bash_language("node server.js") == "javascript"


def test_detect_cargo_command():
    assert detect_bash_language("cargo build --release") == "rust"


def test_detect_go_command():
    assert detect_bash_language("go test ./...") == "go"


def test_detect_plain_git():
    assert detect_bash_language("git status") == "bash"


def test_detect_plain_ls():
    assert detect_bash_language("ls -la") == "bash"


def test_detect_sudo_prefix():
    assert detect_bash_language("sudo python3 app.py") == "python"


def test_detect_env_prefix():
    assert detect_bash_language("env python train.py") == "python"


def test_detect_empty_command():
    assert detect_bash_language("") == "bash"


def test_detect_file_python():
    assert detect_file_language("/path/to/file.py") == "python"


def test_detect_file_typescript():
    assert detect_file_language("src/app.ts") == "typescript"


def test_detect_file_json():
    assert detect_file_language("config.json") == "json"


def test_detect_file_unknown():
    assert detect_file_language("Makefile") is None


def test_detect_file_yaml():
    assert detect_file_language("docker-compose.yml") == "yaml"
