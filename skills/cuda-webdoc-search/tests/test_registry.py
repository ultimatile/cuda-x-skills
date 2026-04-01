"""Tests for registry.py — shared registry loading."""

import os
from pathlib import Path

import pytest

from registry import DEFAULT_REGISTRY_PATH, load_registry

SKILL_DIR = Path(__file__).resolve().parent.parent


class TestDefaultRegistryPath:
    def test_points_to_existing_file(self):
        assert os.path.isfile(DEFAULT_REGISTRY_PATH)

    def test_resolves_to_skill_directory(self):
        assert Path(DEFAULT_REGISTRY_PATH).parent == SKILL_DIR


class TestLoadRegistry:
    def test_success(self):
        result = load_registry(DEFAULT_REGISTRY_PATH)
        assert isinstance(result, dict)
        assert "library" in result

    def test_file_not_found(self, tmp_path):
        result = load_registry(str(tmp_path / "nonexistent.toml"))
        assert isinstance(result, str)
        assert "registry not found" in result

    def test_parse_error(self, tmp_path):
        bad = tmp_path / "bad.toml"
        bad.write_text("invalid {{{")
        result = load_registry(str(bad))
        assert isinstance(result, str)
        assert "failed to parse" in result

    def test_read_error_directory(self, tmp_path):
        result = load_registry(str(tmp_path))
        assert isinstance(result, str)
        assert "failed to read" in result

    def test_read_error_permission(self, tmp_path, monkeypatch):
        target = tmp_path / "noperm.toml"
        target.write_bytes(b"")
        monkeypatch.setattr(
            "builtins.open",
            lambda *a, **kw: (_ for _ in ()).throw(PermissionError("mocked")),
        )
        result = load_registry(str(target))
        assert isinstance(result, str)
        assert "failed to read" in result
