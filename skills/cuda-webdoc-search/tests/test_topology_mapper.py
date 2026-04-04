"""Tests for topology_mapper.py — pure logic functions."""

import pytest

from topology_mapper import (
    _parse_query_groups,
    _score_entry,
    _tokenize_name,
    filter_groups,
    format_list_row,
    get_doxygen_members,
    get_genindex_entries,
    get_library_config,
    parse_domains,
)


# -- _tokenize_name ----------------------------------------------------------


class TestTokenizeName:
    def test_camel_case(self):
        assert _tokenize_name("cudaMemcpy") == ["cuda", "memcpy"]

    def test_underscore(self):
        assert _tokenize_name("CUTENSOR_ALGO_SVD") == ["cutensor", "algo", "svd"]

    def test_mixed_camel(self):
        assert _tokenize_name("cutensornetTensorSVD") == [
            "cutensornet",
            "tensor",
            "svd",
        ]

    def test_all_upper_segments(self):
        assert _tokenize_name("SVD") == ["svd"]

    def test_consecutive_upper_then_lower(self):
        # "cuBLAS" -> ['cu', 'blas'] or similar
        result = _tokenize_name("cuBLAS")
        assert result[-1] == "blas"

    def test_empty(self):
        assert _tokenize_name("") == []

    def test_colons(self):
        assert _tokenize_name("std::vector") == ["std", "vector"]

    def test_hyphens(self):
        assert _tokenize_name("cusolverdn-lt-t-gt-gesvd") == [
            "cusolverdn",
            "lt",
            "t",
            "gt",
            "gesvd",
        ]


# -- _score_entry ------------------------------------------------------------


class TestScoreEntry:
    def test_exact_match(self):
        assert _score_entry("cudaMemcpy", "cudaMemcpy") == 100.0

    def test_exact_case_insensitive(self):
        assert _score_entry("CUDAMEMCPY", "cudaMemcpy") == 100.0

    def test_segment_exact(self):
        # "svd" matches segment "svd" in "cutensornetTensorSVD"
        assert _score_entry("SVD", "cutensornetTensorSVD") == 97.0

    def test_segment_prefix(self):
        # "mem" matches start of segment "memcpy"
        assert _score_entry("mem", "cudaMemcpy") == 94.0

    def test_boundary_contained(self):
        # "ensor" is a substring but not a segment match
        assert _score_entry("ensor", "cutensornetTensorSVD") == 88.0

    def test_fuzzy_capped(self):
        # Something that doesn't match any tier but fuzzy matches somewhat
        score = _score_entry("mempcy", "cudaMemcpy")
        assert score <= 82.0

    def test_no_match(self):
        score = _score_entry("zzzzz", "cudaMemcpy")
        assert score < 60.0

    def test_precomputed_segments(self):
        segs = ["cuda", "memcpy"]
        assert _score_entry("memcpy", "cudaMemcpy", segments=segs) == 97.0

    def test_doxygen_signature_exact(self):
        # Bare name "cudaFree" should score exact against signature
        assert _score_entry("cudaFree", "cudaFree ( void* devPtr )") == 100.0

    def test_doxygen_signature_segment(self):
        # Segment match against bare name portion of signature
        score = _score_entry("Free", "cudaFree ( void* devPtr )")
        assert score == 97.0


# -- filter_groups with role adjustment --------------------------------------


SAMPLE_GROUPS_WITH_ROLES = [
    {
        "group": "cutensornetTensorSVD",
        "url": "https://example.com/svd-func",
        "role": "function",
        "domain": "cpp",
        "source": "cuquantum",
    },
    {
        "group": "CUTENSORNET_TENSOR_SVD_ALGO_GESVD",
        "url": "https://example.com/svd-enum",
        "role": "enumerator",
        "domain": "cpp",
        "source": "cuquantum",
    },
]


class TestRoleAdjustedScoring:
    def test_function_ranks_above_enumerator(self):
        """Function with segment-exact SVD should outrank enumerator with segment-exact SVD."""
        result = filter_groups(
            SAMPLE_GROUPS_WITH_ROLES, ["SVD"], use_fuzzy=True, threshold=50.0
        )
        assert len(result) == 2
        assert result[0]["role"] == "function"
        assert result[1]["role"] == "enumerator"
        assert result[0]["score"] > result[1]["score"]


# -- _parse_query_groups -----------------------------------------------------


class TestParseQueryGroups:
    def test_single_term(self):
        assert _parse_query_groups(["SVD"]) == [["SVD"]]

    def test_and_terms(self):
        assert _parse_query_groups(["SVD", "QR"]) == [["SVD", "QR"]]

    def test_or_separated(self):
        assert _parse_query_groups(["SVD", "|", "QR"]) == [["SVD"], ["QR"]]

    def test_or_quoted(self):
        assert _parse_query_groups(["SVD | QR"]) == [["SVD"], ["QR"]]

    def test_mixed_and_or(self):
        assert _parse_query_groups(["a", "b", "|", "c"]) == [["a", "b"], ["c"]]

    def test_leading_pipe_ignored(self):
        assert _parse_query_groups(["|", "SVD"]) == [["SVD"]]

    def test_trailing_pipe_ignored(self):
        assert _parse_query_groups(["SVD", "|"]) == [["SVD"]]

    def test_consecutive_pipes(self):
        assert _parse_query_groups(["a", "|", "|", "b"]) == [["a"], ["b"]]

    def test_empty(self):
        assert _parse_query_groups([]) == []

    def test_pipe_only(self):
        """Pipe-only input yields empty groups."""
        assert _parse_query_groups(["|"]) == []


class TestFilterGroupsEmptyQuery:
    def test_pipe_only_returns_empty(self):
        """keywords='|' should return no matches, not all groups."""
        result = filter_groups(SAMPLE_GROUPS, ["|"])
        assert result == []


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
        {"name": "cublas", "doc_type": "sphinx", "tags": ["cuBLAS", "cuBLASLt"]},
        {
            "name": "cccl",
            "doc_type": "sphinx",
            "tags": ["thrust", "cub", "libcudacxx"],
            "match_threshold": 70.0,
        },
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

    def test_tag_match(self):
        lib = get_library_config(SAMPLE_REGISTRY, "thrust")
        assert lib is not None
        assert lib["name"] == "cccl"

    def test_tag_case_insensitive(self):
        lib = get_library_config(SAMPLE_REGISTRY, "cuBLASLt")
        assert lib is not None
        assert lib["name"] == "cublas"

    def test_name_takes_priority_over_tag(self):
        """Exact name match wins even if another library has a matching tag."""
        lib = get_library_config(SAMPLE_REGISTRY, "cublas")
        assert lib is not None
        assert lib["name"] == "cublas"

    def test_tag_no_match(self):
        assert get_library_config(SAMPLE_REGISTRY, "nonexistent_tag") is None


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

    def test_multiple_keywords_and(self):
        """Space-separated keywords use AND: both must match."""
        result = filter_groups(SAMPLE_GROUPS, ["cuda", "Mem"])
        # Only cudaMemcpy contains both "cuda" AND "Mem" (cudaMalloc has no "Mem")
        names = {g["group"] for g in result}
        assert names == {"cudaMemcpy"}

    def test_multiple_keywords_or(self):
        """Pipe-separated keywords use OR."""
        result = filter_groups(SAMPLE_GROUPS, ["Memcpy", "|", "Free"])
        names = {g["group"] for g in result}
        assert names == {"cudaMemcpy", "cudaFree"}

    def test_or_quoted(self):
        """Quoted pipe also works."""
        result = filter_groups(SAMPLE_GROUPS, ["Memcpy | Free"])
        names = {g["group"] for g in result}
        assert names == {"cudaMemcpy", "cudaFree"}

    def test_no_duplicates(self):
        result = filter_groups(SAMPLE_GROUPS, ["cuda", "|", "Mem"])
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

    def test_fuzzy_case_insensitive(self):
        """Uppercase keywords match mixed-case group names case-insensitively."""
        result = filter_groups(
            SAMPLE_GROUPS, ["MEMCPY"], use_fuzzy=True, threshold=60.0
        )
        assert any(g["group"] == "cudaMemcpy" for g in result)

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

    def test_fuzzy_or(self):
        """Fuzzy OR: 'Memcpy | Free' should match both."""
        result = filter_groups(
            SAMPLE_GROUPS, ["Memcpy", "|", "Free"], use_fuzzy=True, threshold=60.0
        )
        names = {g["group"] for g in result}
        assert "cudaMemcpy" in names
        assert "cudaFree" in names

    def test_fuzzy_mixed_and_or(self):
        """Fuzzy mixed: 'cuda Stream | Memcpy' = (cuda AND Stream) OR Memcpy."""
        result = filter_groups(
            SAMPLE_GROUPS,
            ["cuda", "Stream", "|", "Memcpy"],
            use_fuzzy=True,
            threshold=60.0,
        )
        names = {g["group"] for g in result}
        assert "cudaStreamCreate" in names
        assert "cudaMemcpy" in names


# -- --limit option ----------------------------------------------------------


LIMIT_TEST_GROUPS = [
    {
        "group": "cutensornetTensorSVD",
        "url": "https://example.com/svd1",
        "role": "function",
        "domain": "cpp",
        "source": "cuquantum",
    },
    {
        "group": "cutensornetTensorSVDConfig",
        "url": "https://example.com/svd2",
        "role": "function",
        "domain": "cpp",
        "source": "cuquantum",
    },
    {
        "group": "CUTENSORNET_TENSOR_SVD_ALGO",
        "url": "https://example.com/svd3",
        "role": "enumerator",
        "domain": "cpp",
        "source": "cuquantum",
    },
]


class TestLimitOption:
    @pytest.fixture
    def run_mapper(self, monkeypatch):
        import io
        from unittest.mock import patch

        import topology_mapper

        monkeypatch.setattr(topology_mapper, "load_registry", lambda _: SAMPLE_REGISTRY)
        monkeypatch.setattr(
            topology_mapper,
            "resolve_inventory_url",
            lambda *a, **kw: "https://example.com/objects.inv",
        )
        monkeypatch.setattr(
            topology_mapper,
            "get_sphinx_groups",
            lambda *a, **kw: LIMIT_TEST_GROUPS,
        )

        def _run(args):
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                patch("sys.argv", ["topology_mapper.py"] + args),
                patch("sys.stdout", stdout),
                patch("sys.stderr", stderr),
            ):
                try:
                    topology_mapper.main()
                except SystemExit as e:
                    if e.code not in (0, None):
                        raise
            return stdout.getvalue(), stderr.getvalue()

        return _run

    def test_limit_truncates(self, run_mapper):
        import json

        out, _ = run_mapper(
            ["--source", "cccl", "--keywords", "SVD", "--fuzzy", "--limit", "1"]
        )
        data = json.loads(out)
        # candidates truncated but filtered_count reflects pre-limit total
        assert len(data["candidates"]) == 1
        assert data["filtered_count"] >= 1

    def test_filtered_count_preserves_pre_limit(self, run_mapper):
        import json

        out, _ = run_mapper(["--source", "cccl", "--limit", "1"])
        data = json.loads(out)
        assert len(data["candidates"]) == 1
        # 3 items in LIMIT_TEST_GROUPS, filtered_count should be 3
        assert data["filtered_count"] == 3

    def test_limit_zero_errors(self):
        """--limit 0 should cause an argparse error."""
        import io
        from unittest.mock import patch

        from topology_mapper import main

        with pytest.raises(SystemExit):
            with (
                patch(
                    "sys.argv",
                    ["topology_mapper.py", "--source", "cccl", "--limit", "0"],
                ),
                patch("sys.stdout", io.StringIO()),
                patch("sys.stderr", io.StringIO()),
            ):
                main()


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


# -- get_doxygen_members -----------------------------------------------------

SAMPLE_DOXYGEN_HTML = """\
<html><body>
<h3 class="fake_sectiontitle member_header">Functions</h3>
<dl class="members">
  <dt>
    <span class="member_name">
      <a href="#group__CUDART__MEMORY_1g001">cudaFree</a> ( void* devPtr )
    </span>
  </dt>
</dl>
<h3 class="fake_sectiontitle member_header">Typedefs</h3>
<dl class="members">
  <dt>
    <span class="member_name">
      <a href="#group__CUDART__TYPES_1g002">cudaArray_t</a>
    </span>
  </dt>
</dl>
<h3 class="fake_sectiontitle member_header">Enumerations</h3>
<dl class="members">
  <dt>
    <span class="member_name">
      <a href="#group__CUDART__TYPES_1g003">cudaError</a>
    </span>
  </dt>
</dl>
<h3 class="fake_sectiontitle member_header">Defines</h3>
<dl class="members">
  <dt>
    <span class="member_name">
      <a href="#group__CUDART__DEFINES_1g004">CUDA_VERSION</a>
    </span>
  </dt>
</dl>
<h3 class="fake_sectiontitle member_header">Variables</h3>
<dl class="members">
  <dt>
    <span class="member_name">
      <a href="#group__CUDART__VARS_1g005">cudaDefaultStream</a>
    </span>
  </dt>
</dl>
</body></html>
"""


SAMPLE_DOXYGEN_LIBRARY = {
    "default_domain": "c",
    "cpp_groups": ["HIGHLEVEL"],
}


class TestGetDoxygenMembers:
    @pytest.fixture(autouse=True)
    def mock_fetch(self, monkeypatch):
        from bs4 import BeautifulSoup

        import topology_mapper

        def _fake_fetch(url, description=""):
            return BeautifulSoup(SAMPLE_DOXYGEN_HTML, "html.parser")

        monkeypatch.setattr(topology_mapper, "fetch_soup", _fake_fetch)

    def test_extracts_all_members(self):
        members = get_doxygen_members(
            ["https://example.com/group__CUDART__MEMORY.html"],
            "cuda_runtime",
            library=SAMPLE_DOXYGEN_LIBRARY,
        )
        assert len(members) == 5

    def test_function_role(self):
        members = get_doxygen_members(
            ["https://example.com/group__CUDART__MEMORY.html"],
            "cuda_runtime",
            library=SAMPLE_DOXYGEN_LIBRARY,
        )
        func = next(m for m in members if "cudaFree" in m["group"])
        assert func["role"] == "function"
        assert func["domain"] == "c"
        assert func["source"] == "cuda_runtime"

    def test_typedef_role(self):
        members = get_doxygen_members(
            ["https://example.com/group__CUDART__MEMORY.html"],
            "cuda_runtime",
            library=SAMPLE_DOXYGEN_LIBRARY,
        )
        td = next(m for m in members if "cudaArray_t" in m["group"])
        assert td["role"] == "type"
        assert td["domain"] == "c"

    def test_enum_role(self):
        members = get_doxygen_members(
            ["https://example.com/group__CUDART__MEMORY.html"],
            "cuda_runtime",
            library=SAMPLE_DOXYGEN_LIBRARY,
        )
        en = next(m for m in members if "cudaError" in m["group"])
        assert en["role"] == "enum"
        assert en["domain"] == "c"

    def test_define_role(self):
        members = get_doxygen_members(
            ["https://example.com/group__CUDART__MEMORY.html"],
            "cuda_runtime",
            library=SAMPLE_DOXYGEN_LIBRARY,
        )
        d = next(m for m in members if "CUDA_VERSION" in m["group"])
        assert d["role"] == "macro"

    def test_variable_role(self):
        members = get_doxygen_members(
            ["https://example.com/group__CUDART__MEMORY.html"],
            "cuda_runtime",
            library=SAMPLE_DOXYGEN_LIBRARY,
        )
        v = next(m for m in members if "cudaDefaultStream" in m["group"])
        assert v["role"] == "data"

    def test_cpp_group_domain(self):
        """cpp_groups pattern in URL overrides default_domain."""
        members = get_doxygen_members(
            ["https://example.com/group__CUDART__HIGHLEVEL.html"],
            "cuda_runtime",
            library=SAMPLE_DOXYGEN_LIBRARY,
        )
        assert all(m["domain"] == "cpp" for m in members)

    def test_no_library_defaults_empty_domain(self):
        """Without library config, domain falls back to empty string."""
        members = get_doxygen_members(
            ["https://example.com/group__CUDART__MEMORY.html"], "cuda_runtime"
        )
        assert all(m["domain"] == "" for m in members)

    def test_deduplicates_by_url(self):
        members = get_doxygen_members(
            [
                "https://example.com/group__CUDART__MEMORY.html",
                "https://example.com/group__CUDART__MEMORY.html",
            ],
            "cuda_runtime",
            library=SAMPLE_DOXYGEN_LIBRARY,
        )
        assert len(members) == 5

    def test_fetch_failure(self, monkeypatch):
        import topology_mapper

        monkeypatch.setattr(topology_mapper, "fetch_soup", lambda url, desc="": None)
        members = get_doxygen_members(
            ["https://example.com/group__X.html"], "cuda_runtime"
        )
        assert members == []


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
        "role": "function",
        "domain": "c",
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
            "resolve_inventory_url",
            lambda *a, **kw: "https://example.com/objects.inv",
        )
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

    def test_doxygen_list_metadata(self, run_mapper, monkeypatch):
        """Doxygen --list output includes role/domain from member extraction."""
        import topology_mapper

        monkeypatch.setattr(
            topology_mapper,
            "get_all_groups",
            lambda *a, **kw: [],
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
        assert fields[2] == "function"
        assert fields[3] == "c"
        assert fields[4] == "curand"

    def test_fuzzy_list_has_score(self, run_mapper, monkeypatch):
        """Fuzzy --list output appends score and matched_keyword."""
        import topology_mapper

        monkeypatch.setattr(
            topology_mapper,
            "resolve_inventory_url",
            lambda *a, **kw: "https://example.com/objects.inv",
        )
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


# -- threshold resolution ----------------------------------------------------


class TestThresholdResolution:
    """Test that fuzzy threshold resolves as: CLI > registry > 60.0 fallback."""

    @pytest.fixture
    def capture_threshold(self, monkeypatch):
        """Monkeypatch filter_groups to capture the threshold argument."""
        import topology_mapper

        captured = {}

        original_filter = topology_mapper.filter_groups

        def _capture(*args, **kwargs):
            captured["threshold"] = kwargs.get(
                "threshold", args[3] if len(args) > 3 else None
            )
            return original_filter(*args, **kwargs)

        monkeypatch.setattr(topology_mapper, "filter_groups", _capture)
        monkeypatch.setattr(topology_mapper, "load_registry", lambda _: SAMPLE_REGISTRY)
        monkeypatch.setattr(
            topology_mapper,
            "resolve_inventory_url",
            lambda *a, **kw: "https://example.com/objects.inv",
        )
        monkeypatch.setattr(
            topology_mapper,
            "get_sphinx_groups",
            lambda *a, **kw: SPHINX_GROUPS,
        )
        return captured

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

    def test_registry_threshold(self, run_mapper, capture_threshold):
        """Uses registry match_threshold when CLI --threshold not given."""
        run_mapper(["--source", "cccl", "--keywords", "mem", "--fuzzy", "--list"])
        assert capture_threshold["threshold"] == 70.0

    def test_cli_overrides_registry(self, run_mapper, capture_threshold):
        """CLI --threshold takes precedence over registry."""
        run_mapper(
            [
                "--source",
                "cccl",
                "--keywords",
                "mem",
                "--fuzzy",
                "--threshold",
                "85",
                "--list",
            ]
        )
        assert capture_threshold["threshold"] == 85.0

    def test_fallback_default(self, run_mapper, capture_threshold):
        """Falls back to 60.0 when neither CLI nor registry specify threshold."""
        run_mapper(["--source", "cublas", "--keywords", "mem", "--fuzzy", "--list"])
        assert capture_threshold["threshold"] == 60.0


# -- Multi-source tests -------------------------------------------------------


class TestMultiSource:
    """Test multi-source search behavior."""

    @pytest.fixture
    def run_mapper(self):
        """Run topology_mapper.main() with given args and capture stdout/stderr."""
        import io
        from unittest.mock import patch

        from topology_mapper import main

        def _run(args):
            # Default --limit to keep tests bounded when hitting live sources
            normalized = list(args)
            if "--limit" not in normalized:
                normalized.extend(["--limit", "5"])
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                patch("sys.argv", ["topology_mapper.py"] + normalized),
                patch("sys.stdout", stdout),
                patch("sys.stderr", stderr),
            ):
                try:
                    main()
                except SystemExit as e:
                    if e.code not in (0, None):
                        raise
            return stdout.getvalue(), stderr.getvalue()

        return _run

    def test_multi_source_json_has_sources_field(self, run_mapper):
        """Multi-source output uses 'sources' (list) instead of 'source' (string)."""
        import json

        out, _ = run_mapper(["--source", "cccl", "cublas"])
        data = json.loads(out)
        assert "sources" in data
        assert isinstance(data["sources"], list)
        assert "cccl" in data["sources"]
        assert "cublas" in data["sources"]
        # No singular 'source' key in multi-source mode
        assert "source" not in data

    def test_single_source_preserves_source_string(self, run_mapper):
        """Single source still uses 'source' (string), not 'sources'."""
        import json

        out, _ = run_mapper(["--source", "cccl"])
        data = json.loads(out)
        assert "source" in data
        assert isinstance(data["source"], str)
        assert "sources" not in data

    def test_multi_source_total_found_per_source(self, run_mapper):
        """total_found is a per-source dict in multi-source mode."""
        import json

        out, _ = run_mapper(["--source", "cccl", "cublas"])
        data = json.loads(out)
        assert isinstance(data["total_found"], dict)
        assert "cccl" in data["total_found"]
        assert "cublas" in data["total_found"]

    def test_multi_source_candidates_have_source_field(self, run_mapper):
        """Each candidate has a 'source' field identifying its origin."""
        import json

        out, _ = run_mapper(["--source", "cccl", "cublas"])
        data = json.loads(out)
        for c in data["candidates"]:
            assert "source" in c

    def test_multi_source_pdf_warning(self, run_mapper):
        """PDF source in multi-source emits warning on stderr, other results proceed."""
        import json

        out, err = run_mapper(["--source", "cccl", "amgx"])
        data = json.loads(out)
        assert "amgx" in err.lower() or "pdf" in err.lower()
        # cccl results should still be present
        assert data["total_found"]["cccl"] > 0

    def test_multi_source_unknown_source_fails_fast(self):
        """Unknown source in multi-source list causes immediate error."""
        import io
        from unittest.mock import patch

        from topology_mapper import main

        with pytest.raises(SystemExit):
            with (
                patch(
                    "sys.argv",
                    ["topology_mapper.py", "--source", "cccl", "nonexistent"],
                ),
                patch("sys.stdout", io.StringIO()),
                patch("sys.stderr", io.StringIO()),
            ):
                main()

    def test_multi_source_alias_dedup(self, run_mapper):
        """--source cccl thrust dedupes to single fetch (both resolve to cccl)."""
        import json

        out, _ = run_mapper(["--source", "cccl", "thrust"])
        data = json.loads(out)
        # Alias dedup: only one source entry (first requested name) in sources list
        assert data["sources"] == ["cccl"]
        assert "cccl" in data["total_found"]
        assert len(data["total_found"]) == 1

    def test_multi_source_stats_error(self):
        """--stats with multiple sources causes an argparse error."""
        import io
        from unittest.mock import patch

        from topology_mapper import main

        with pytest.raises(SystemExit):
            with (
                patch(
                    "sys.argv",
                    [
                        "topology_mapper.py",
                        "--source",
                        "cccl",
                        "cublas",
                        "--stats",
                    ],
                ),
                patch("sys.stdout", io.StringIO()),
                patch("sys.stderr", io.StringIO()),
            ):
                main()

    def test_multi_source_limit(self, run_mapper):
        """--limit applies to merged results across all sources."""
        import json

        out, _ = run_mapper(["--source", "cccl", "cublas", "--limit", "3"])
        data = json.loads(out)
        assert len(data["candidates"]) <= 3

    def test_multi_source_list_mode(self, run_mapper):
        """--list mode works with multi-source results."""
        out, _ = run_mapper(["--source", "cccl", "cublas", "--list"])
        lines = [line for line in out.strip().split("\n") if line]
        assert len(lines) > 0
        # Each line should be TSV with at least 5 fields
        for line in lines:
            fields = line.split("\t")
            assert len(fields) >= 5
