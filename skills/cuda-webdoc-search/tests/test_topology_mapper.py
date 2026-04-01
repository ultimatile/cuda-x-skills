"""Tests for topology_mapper.py — pure logic functions."""

import pytest

from topology_mapper import (
    filter_groups,
    format_list_row,
    get_genindex_entries,
    get_library_config,
    parse_domains,
)


# -- fixtures ----------------------------------------------------------------

SAMPLE_GROUPS = [
    {
        "group": "cudaMemcpy",
        "url": "https://example.com/memcpy",
        "source": "cuda_runtime",
    },
    {
        "group": "cudaMalloc",
        "url": "https://example.com/malloc",
        "source": "cuda_runtime",
    },
    {"group": "cudaFree", "url": "https://example.com/free", "source": "cuda_runtime"},
    {
        "group": "cudaStreamCreate",
        "url": "https://example.com/stream",
        "source": "cuda_runtime",
    },
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
        assert lib is not None
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
        assert result == SAMPLE_GROUPS

    def test_empty_keywords_returns_all(self):
        result = filter_groups(SAMPLE_GROUPS, [])
        assert result == SAMPLE_GROUPS

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
        result = filter_groups(
            SAMPLE_GROUPS, ["memcpy"], use_fuzzy=True, threshold=60.0
        )
        assert any(g["group"] == "cudaMemcpy" for g in result)
        assert all("score" in g for g in result)
        assert all("matched_keyword" in g for g in result)

    def test_fuzzy_sorted_by_score(self):
        result = filter_groups(SAMPLE_GROUPS, ["mem"], use_fuzzy=True, threshold=50.0)
        assert result
        scores = [g["score"] for g in result]
        assert scores == sorted(scores, reverse=True)

    def test_fuzzy_high_threshold_filters(self):
        result = filter_groups(SAMPLE_GROUPS, ["xyz"], use_fuzzy=True, threshold=99.0)
        assert len(result) == 0

    def test_fuzzy_deduplicates_by_url(self):
        result = filter_groups(
            SAMPLE_GROUPS, ["cuda", "Mem"], use_fuzzy=True, threshold=50.0
        )
        assert result
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
            with (
                patch("sys.argv", ["topology_mapper.py"] + args),
                patch("sys.stdout", stdout),
                patch("sys.stderr", stderr),
            ):
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
        # Fallback rows use same 5-column TSV as normal candidates
        fields = out.strip().split("\t")
        assert len(fields) == 5
        assert fields[4] == "amgx"

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


# -- get_genindex_entries ----------------------------------------------------

SAMPLE_GENINDEX_HTML = """\
<html><body>
<table class="indextable genindextable">
<tr>
<td><ul>
<li><a href="api/cutensor.html#_CPPv414cutensorCreate">cutensorCreate (C++ function)</a></li>
<li><a href="api/types.html#_CPPv416cutensorHandle_t">cutensorHandle_t (C++ type)</a></li>
<li><a href="api/types.html#_CPPv414cutensorAlgo_t">cutensorAlgo_t (C++ enum)</a></li>
</ul></td>
<td><ul>
<li><a href="api/types.html#_CPPv4N14cutensorAlgo_t21CUTENSOR_ALGO_DEFAULTE">cutensorAlgo_t::CUTENSOR_ALGO_DEFAULT (C++ enumerator)</a></li>
<li><a href="api/types.html#_CPPv414cudaDataType_t">cudaDataType_t (C++ enum)</a></li>
</ul></td>
</tr>
</table>
</body></html>
"""


class TestGetGenindexEntries:
    @pytest.fixture(autouse=True)
    def mock_fetch(self, monkeypatch):
        """Mock fetch_soup to return sample HTML without network access."""
        from bs4 import BeautifulSoup

        import topology_mapper

        def _fake_fetch(url, description=""):
            return BeautifulSoup(SAMPLE_GENINDEX_HTML, "html.parser")

        monkeypatch.setattr(topology_mapper, "fetch_soup", _fake_fetch)

    def test_parses_all_entries(self):
        entries = get_genindex_entries("https://example.com/genindex.html", "cutensor")
        assert len(entries) == 5

    def test_entry_structure(self):
        entries = get_genindex_entries("https://example.com/genindex.html", "cutensor")
        func = next(e for e in entries if e["group"] == "cutensorCreate")
        assert func["domain"] == "cpp"
        assert func["role"] == "function"
        assert func["source"] == "cutensor"
        assert func["origin"] == "genindex"
        assert "cutensor.html" in func["url"]

    def test_all_roles_parsed(self):
        entries = get_genindex_entries("https://example.com/genindex.html", "cutensor")
        roles = {e["role"] for e in entries}
        assert roles == {"function", "type", "enum", "enumerator"}

    def test_domain_normalization(self):
        entries = get_genindex_entries("https://example.com/genindex.html", "cutensor")
        assert all(e["domain"] == "cpp" for e in entries)

    def test_domains_filter(self):
        entries = get_genindex_entries(
            "https://example.com/genindex.html", "cutensor", domains={"c"}
        )
        assert len(entries) == 0

    def test_domains_filter_match(self):
        entries = get_genindex_entries(
            "https://example.com/genindex.html", "cutensor", domains={"cpp"}
        )
        assert len(entries) == 5

    def test_scoped_name(self):
        entries = get_genindex_entries("https://example.com/genindex.html", "cutensor")
        scoped = next(e for e in entries if "CUTENSOR_ALGO_DEFAULT" in e["group"])
        assert scoped["group"] == "cutensorAlgo_t::CUTENSOR_ALGO_DEFAULT"
        assert scoped["role"] == "enumerator"

    def test_empty_page(self, monkeypatch):
        from bs4 import BeautifulSoup

        import topology_mapper

        monkeypatch.setattr(
            topology_mapper,
            "fetch_soup",
            lambda url, desc="": BeautifulSoup("<html></html>", "html.parser"),
        )
        entries = get_genindex_entries("https://example.com/genindex.html", "cutensor")
        assert entries == []

    def test_fetch_failure(self, monkeypatch):
        import topology_mapper

        monkeypatch.setattr(topology_mapper, "fetch_soup", lambda url, desc="": None)
        entries = get_genindex_entries("https://example.com/genindex.html", "cutensor")
        assert entries == []


# -- --list TSV output format ------------------------------------------------


SPHINX_GROUPS = [
    {
        "group": "cudaMemcpy",
        "url": "https://example.com/memcpy",
        "role": "function",
        "domain": "cpp",
        "source": "cccl",
    },
    {
        "group": "cudaMalloc",
        "url": "https://example.com/malloc",
        "role": "function",
        "domain": "cpp",
        "source": "cccl",
    },
]

DOXYGEN_GROUPS = [
    {
        "group": "curandGenerate",
        "url": "https://example.com/curand",
        "source": "curand",
    },
]


class TestFormatListRow:
    """Test the format_list_row helper directly."""

    def test_base_fields(self):
        row = format_list_row("cudaMemcpy", "https://ex.com", "function", "cpp", "cccl")
        fields = row.split("\t")
        assert len(fields) == 5
        assert fields == ["cudaMemcpy", "https://ex.com", "function", "cpp", "cccl"]

    def test_empty_metadata(self):
        row = format_list_row("curandGen", "https://ex.com", source="curand")
        fields = row.split("\t")
        assert len(fields) == 5
        assert fields[2:4] == ["", ""]
        assert fields[4] == "curand"

    def test_with_score(self):
        row = format_list_row(
            "cudaMemcpy",
            "https://ex.com",
            "function",
            "cpp",
            "cccl",
            score=85.0,
            matched_keyword="memcpy",
        )
        fields = row.split("\t")
        assert len(fields) == 7
        assert fields[5] == "85.0"
        assert fields[6] == "memcpy"

    def test_score_none_omits_columns(self):
        row = format_list_row("name", "url", score=None)
        assert row.count("\t") == 4


class TestListTsvOutput:
    """Integration tests: --list output through main()."""

    @pytest.fixture
    def run_mapper(self):
        import io
        from unittest.mock import patch

        from topology_mapper import main

        def _run(args):
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                patch("sys.argv", ["topology_mapper.py"] + args),
                patch("sys.stdout", stdout),
                patch("sys.stderr", stderr),
            ):
                try:
                    main()
                except SystemExit as e:
                    if e.code != 0:
                        raise
            return stdout.getvalue(), stderr.getvalue()

        return _run

    def test_sphinx_list_fields(self, run_mapper, monkeypatch):
        """Sphinx --list output has 5 tab-separated fields."""
        import topology_mapper

        monkeypatch.setattr(
            topology_mapper,
            "get_sphinx_groups",
            lambda *a, **kw: SPHINX_GROUPS,
        )
        out, _ = run_mapper(["--source", "cccl", "--keywords", "Memcpy", "--list"])
        line = out.strip().splitlines()[0]
        fields = line.split("\t")
        assert len(fields) == 5
        assert fields[2] == "function"
        assert fields[3] == "cpp"
        assert fields[4] == "cccl"

    def test_doxygen_list_empty_metadata(self, run_mapper, monkeypatch):
        """Doxygen --list output has empty role/domain."""
        import topology_mapper

        monkeypatch.setattr(
            topology_mapper,
            "get_all_groups",
            lambda *a, **kw: DOXYGEN_GROUPS,
        )
        monkeypatch.setattr(
            topology_mapper,
            "get_doxygen_members",
            lambda *a, **kw: DOXYGEN_GROUPS,
        )
        out, _ = run_mapper(
            ["--source", "cuda_runtime", "--keywords", "curand", "--list"]
        )
        line = out.strip().splitlines()[0]
        fields = line.split("\t")
        assert len(fields) == 5
        assert fields[2] == ""
        assert fields[3] == ""

    def test_fuzzy_list_has_score(self, run_mapper, monkeypatch):
        """Fuzzy --list output appends score and matched_keyword."""
        import topology_mapper

        monkeypatch.setattr(
            topology_mapper,
            "get_sphinx_groups",
            lambda *a, **kw: SPHINX_GROUPS,
        )
        out, _ = run_mapper(
            ["--source", "cccl", "--keywords", "memcpy", "--fuzzy", "--list"]
        )
        line = out.strip().splitlines()[0]
        fields = line.split("\t")
        assert len(fields) == 7
        assert float(fields[5]) > 0
