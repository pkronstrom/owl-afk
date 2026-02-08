"""Rule presets - pre-built rulesets at different trust levels."""

from importlib import resources

from owl.core.storage import Storage

PRESETS = [
    {
        "name": "cautious",
        "description": "Read-only tools, git reads, file inspection",
    },
    {
        "name": "standard",
        "description": "+ file writes, git commits, dev tools, testing",
    },
    {
        "name": "permissive",
        "description": "+ git push, docker run, network, runtimes",
    },
]

_PRESET_NAMES = {p["name"] for p in PRESETS}


def list_presets() -> list[dict]:
    """Return available presets with name and description."""
    return list(PRESETS)


def get_preset_patterns(name: str) -> list[str]:
    """Parse a preset file, return deduplicated list of patterns."""
    if name not in _PRESET_NAMES:
        raise ValueError(f"Unknown preset: {name!r}. Available: {sorted(_PRESET_NAMES)}")

    text = resources.files("owl.data.presets").joinpath(f"{name}.txt").read_text()
    patterns = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return list(dict.fromkeys(patterns))  # dedupe, preserve order


async def load_preset(storage: Storage, name: str) -> tuple[int, int]:
    """Load preset rules into DB.

    Returns: (added_count, skipped_count)
    """
    patterns = get_preset_patterns(name)
    created_via = f"preset:{name}"

    added, skipped = 0, 0
    for pattern in patterns:
        existing = await storage.get_rule_by_pattern(pattern, "approve")
        if existing:
            skipped += 1
        else:
            await storage.add_rule(pattern, "approve", priority=0, created_via=created_via)
            added += 1

    return added, skipped
