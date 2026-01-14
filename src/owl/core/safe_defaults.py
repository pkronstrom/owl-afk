"""Safe defaults installation."""

from importlib import resources
from pathlib import Path

from owl.core.storage import Storage
from owl.utils.config import get_owl_dir


def get_defaults_path() -> Path:
    """Get user's safe defaults file path."""
    return get_owl_dir() / "safe_defaults.txt"


def parse_defaults_file(path: Path) -> list[str]:
    """Parse defaults file, return list of patterns."""
    if not path.exists():
        return []

    patterns = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)

    return list(dict.fromkeys(patterns))  # dedupe, preserve order


def ensure_defaults_file() -> Path:
    """Create defaults file from template if it doesn't exist."""
    path = get_defaults_path()
    if not path.exists():
        template = resources.files("owl.data").joinpath("safe_defaults.txt")
        path.write_text(template.read_text())
    return path


async def install_safe_defaults(storage: Storage) -> tuple[int, int]:
    """Install safe defaults from config file.

    Returns: (added_count, skipped_count)
    """
    path = ensure_defaults_file()
    patterns = parse_defaults_file(path)

    added, skipped = 0, 0
    for pattern in patterns:
        existing = await storage.get_rule_by_pattern(pattern, "approve")
        if existing:
            skipped += 1
        else:
            await storage.add_rule(
                pattern, "approve", priority=0, created_via="safe_defaults"
            )
            added += 1

    return added, skipped
