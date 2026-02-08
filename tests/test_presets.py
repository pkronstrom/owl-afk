"""Tests for rule presets."""

import pytest

from owl.core.presets import PRESETS, get_preset_patterns, list_presets, load_preset
from owl.core.storage import Storage


class TestListPresets:
    """Tests for list_presets."""

    def test_returns_three_presets(self):
        presets = list_presets()
        assert len(presets) == 3

    def test_preset_names(self):
        presets = list_presets()
        names = [p["name"] for p in presets]
        assert names == ["cautious", "standard", "permissive"]

    def test_presets_have_description(self):
        presets = list_presets()
        for p in presets:
            assert "description" in p
            assert len(p["description"]) > 0


class TestGetPresetPatterns:
    """Tests for get_preset_patterns."""

    def test_cautious_has_patterns(self):
        patterns = get_preset_patterns("cautious")
        assert len(patterns) > 0

    def test_standard_includes_cautious(self):
        cautious = set(get_preset_patterns("cautious"))
        standard = set(get_preset_patterns("standard"))
        assert cautious.issubset(standard)

    def test_permissive_includes_standard(self):
        standard = set(get_preset_patterns("standard"))
        permissive = set(get_preset_patterns("permissive"))
        assert standard.issubset(permissive)

    def test_invalid_preset_raises(self):
        with pytest.raises(ValueError, match="Unknown preset"):
            get_preset_patterns("nonexistent")

    def test_no_duplicate_patterns(self):
        for name in ["cautious", "standard", "permissive"]:
            patterns = get_preset_patterns(name)
            assert len(patterns) == len(set(patterns)), f"Duplicates in {name}"

    def test_comments_excluded(self):
        for name in ["cautious", "standard", "permissive"]:
            patterns = get_preset_patterns(name)
            for p in patterns:
                assert not p.startswith("#"), f"Comment in {name}: {p}"

    def test_cautious_has_read_tool(self):
        patterns = get_preset_patterns("cautious")
        assert "Read(*)" in patterns

    def test_standard_has_edit_tool(self):
        patterns = get_preset_patterns("standard")
        assert "Edit(*)" in patterns

    def test_permissive_has_git_push(self):
        patterns = get_preset_patterns("permissive")
        assert "Bash(git push *)" in patterns

    def test_cautious_lacks_edit(self):
        patterns = get_preset_patterns("cautious")
        assert "Edit(*)" not in patterns

    def test_cautious_lacks_git_push(self):
        patterns = get_preset_patterns("cautious")
        assert "Bash(git push *)" not in patterns


class TestLoadPreset:
    """Tests for load_preset (async, needs DB)."""

    @pytest.fixture
    async def storage(self, tmp_path):
        s = Storage(tmp_path / "test.db")
        await s.connect()
        yield s
        await s.close()

    @pytest.mark.asyncio
    async def test_load_adds_rules(self, storage):
        added, skipped = await load_preset(storage, "cautious")
        assert added > 0
        assert skipped == 0

    @pytest.mark.asyncio
    async def test_load_skips_duplicates(self, storage):
        await load_preset(storage, "cautious")
        added, skipped = await load_preset(storage, "cautious")
        assert added == 0
        assert skipped > 0

    @pytest.mark.asyncio
    async def test_load_tags_created_via(self, storage):
        await load_preset(storage, "standard")
        rules = await storage.get_rules()
        for rule in rules:
            assert rule["created_via"] == "preset:standard"

    @pytest.mark.asyncio
    async def test_load_preserves_existing_rules(self, storage):
        await storage.add_rule("Bash(custom *)", "approve", 0, "cli")
        await load_preset(storage, "cautious")
        rules = await storage.get_rules()
        patterns = [r["pattern"] for r in rules]
        assert "Bash(custom *)" in patterns

    @pytest.mark.asyncio
    async def test_load_invalid_preset_raises(self, storage):
        with pytest.raises(ValueError):
            await load_preset(storage, "nonexistent")
