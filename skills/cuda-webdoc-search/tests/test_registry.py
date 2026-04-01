"""Tests for registry.py — shared registry loading."""

import os
import sys
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

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX chmod semantics")
    def test_read_error_permission(self, tmp_path):
        no_read = tmp_path / "noperm.toml"
        no_read.write_bytes(b"")
        no_read.chmod(0o000)
        result = load_registry(str(no_read))
        assert isinstance(result, str)
        assert "failed to read" in result
        no_read.chmod(0o644)  # cleanup
