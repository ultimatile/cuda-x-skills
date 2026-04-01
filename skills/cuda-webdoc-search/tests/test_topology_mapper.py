"""Tests for topology_mapper.py — pure logic functions."""

import pytest

from topology_mapper import filter_groups, get_library_config, parse_domains


# -- fixtures ----------------------------------------------------------------

SAMPLE_GROUPS = [
    {"group": "cudaMemcpy", "url": "https://example.com/memcpy", "source": "cuda_runtime"},
    {"group": "cudaMalloc", "url": "https://example.com/malloc", "source": "cuda_runtime"},
    {"group": "cudaFree", "url": "https://example.com/free", "source": "cuda_runtime"},
    {"group": "cudaStreamCreate", "url": "https://example.com/stream", "source": "cuda_runtime"},
]

SAMPLE_REGISTRY = {
    "library": [
        {"name": "cuda_runtime", "doc_type": "doxygen"},
        {"name": "cublas", "doc_type": "sphinx"},
    ]
}


# -- parse_domains -----------------------------------------------------------

class TestParseDomains:
    def test_none_returns_none(self):
        assert parse_domains(None) is None

    def test_all_returns_none(self):
        assert parse_domains("all") is None

    def test_all_case_insensitive(self):
        assert parse_domains("ALL") is None
        assert parse_domains("All") is None

    def test_single_domain(self):
        assert parse_domains("cpp") == {"cpp"}

    def test_multiple_domains(self):
        assert parse_domains("cpp,c,std") == {"cpp", "c", "std"}

    def test_strips_whitespace(self):
        assert parse_domains(" cpp , c ") == {"cpp", "c"}

    def test_empty_segments_ignored(self):
        assert parse_domains("cpp,,c,") == {"cpp", "c"}


# -- get_library_config ------------------------------------------------------

class TestGetLibraryConfig:
    def test_found(self):
        lib = get_library_config(SAMPLE_REGISTRY, "cublas")
        assert lib["name"] == "cublas"
        assert lib["doc_type"] == "sphinx"

    def test_not_found(self):
        assert get_library_config(SAMPLE_REGISTRY, "nonexistent") is None

    def test_empty_registry(self):
        assert get_library_config({}, "cublas") is None

    def test_no_library_key(self):
        assert get_library_config({"other": []}, "cublas") is None


# -- filter_groups (non-fuzzy) -----------------------------------------------

class TestFilterGroupsNonFuzzy:
    def test_no_keywords_returns_all(self):
        result = filter_groups(SAMPLE_GROUPS, None)
        assert result is SAMPLE_GROUPS

    def test_empty_keywords_returns_all(self):
        result = filter_groups(SAMPLE_GROUPS, [])
        assert result is SAMPLE_GROUPS

    def test_single_keyword_match(self):
        result = filter_groups(SAMPLE_GROUPS, ["Memcpy"])
        assert len(result) == 1
        assert result[0]["group"] == "cudaMemcpy"

    def test_case_insensitive(self):
        result = filter_groups(SAMPLE_GROUPS, ["memcpy"])
        assert len(result) == 1

    def test_partial_match(self):
        result = filter_groups(SAMPLE_GROUPS, ["cuda"])
        assert len(result) == 4

    def test_no_match(self):
        result = filter_groups(SAMPLE_GROUPS, ["nonexistent"])
        assert len(result) == 0

    def test_multiple_keywords(self):
        result = filter_groups(SAMPLE_GROUPS, ["Memcpy", "Free"])
        assert len(result) == 2
        names = {g["group"] for g in result}
        assert names == {"cudaMemcpy", "cudaFree"}

    def test_no_duplicates(self):
        result = filter_groups(SAMPLE_GROUPS, ["cuda", "Mem"])
        # "cudaMemcpy" and "cudaMalloc" match "cuda"; "cudaMemcpy" also matches "Mem"
        groups = [g["group"] for g in result]
        assert len(groups) == len(set(groups))


# -- filter_groups (fuzzy) ---------------------------------------------------

class TestFilterGroupsFuzzy:
    def test_fuzzy_match(self):
        result = filter_groups(SAMPLE_GROUPS, ["memcpy"], use_fuzzy=True, threshold=60.0)
        assert any(g["group"] == "cudaMemcpy" for g in result)
        assert all("score" in g for g in result)
        assert all("matched_keyword" in g for g in result)

    def test_fuzzy_sorted_by_score(self):
        result = filter_groups(SAMPLE_GROUPS, ["mem"], use_fuzzy=True, threshold=50.0)
        scores = [g["score"] for g in result]
        assert scores == sorted(scores, reverse=True)

    def test_fuzzy_high_threshold_filters(self):
        result = filter_groups(SAMPLE_GROUPS, ["xyz"], use_fuzzy=True, threshold=99.0)
        assert len(result) == 0

    def test_fuzzy_deduplicates_by_url(self):
        result = filter_groups(SAMPLE_GROUPS, ["cuda", "Mem"], use_fuzzy=True, threshold=50.0)
        urls = [g["url"] for g in result]
        assert len(urls) == len(set(urls))


# -- main() output branches for non-searchable sources ----------------------

class TestNonSearchableOutput:
    """Test that main() handles --list / --keywords combinations for pdf/sphinx_noinv."""

    @pytest.fixture
    def run_mapper(self):
        """Run topology_mapper.main() with given args and capture stdout/stderr."""
        import io
        from unittest.mock import patch

        from topology_mapper import main

        def _run(args):
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch("sys.argv", ["topology_mapper.py"] + args), \
                 patch("sys.stdout", stdout), \
                 patch("sys.stderr", stderr):
                try:
                    main()
                except SystemExit as e:
                    if e.code != 0:
                        raise
            return stdout.getvalue(), stderr.getvalue()

        return _run

    def test_list_mode(self, run_mapper):
        out, _ = run_mapper(["--source", "amgx", "--list"])
        assert "[PDF manual]" in out
        assert "AMGX" in out

    def test_json_mode(self, run_mapper):
        import json
        out, _ = run_mapper(["--source", "amgx"])
        data = json.loads(out)
        assert data["doc_type"] == "pdf"
        assert data["source"] == "amgx"
        assert data["total_found"] == 0

    def test_keywords_json_mode(self, run_mapper):
        import json
        out, _ = run_mapper(["--source", "amgx", "--keywords", "solver"])
        data = json.loads(out)
        assert data["doc_type"] == "pdf"
        assert data["filtered_count"] == 0

    def test_keywords_list_mode(self, run_mapper):
        """Regression: --keywords --list previously produced no output."""
        out, _ = run_mapper(["--source", "amgx", "--keywords", "solver", "--list"])
        assert "[PDF manual]" in out
