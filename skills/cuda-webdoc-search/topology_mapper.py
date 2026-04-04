# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "requests",
#     "beautifulsoup4",
#     "rapidfuzz",
#     "sphobjinv",
# ]
# ///

import re
import requests
from bs4 import BeautifulSoup
import json
import sys
import argparse
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from heapq import merge as heapq_merge
from itertools import chain, islice
from urllib.parse import urljoin
from rapidfuzz import fuzz

import sphobjinv as soi

from registry import DEFAULT_REGISTRY_PATH, load_registry

BASE_URL = "https://docs.nvidia.com/cuda/cuda-runtime-api/"
MODULES_URL = urljoin(BASE_URL, "modules.html")


def probe_inventory_url(url, timeout=10):
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        return response.url
    except Exception:
        return None


def resolve_inventory_url(inventory_urls, base_urls, env_override=None):
    if env_override:
        resolved = probe_inventory_url(env_override)
        if resolved:
            return resolved

    for url in inventory_urls:
        resolved = probe_inventory_url(url)
        if resolved:
            return resolved

    for base_url in base_urls:
        try:
            response = requests.get(base_url, timeout=10)
            response.raise_for_status()
            base = urljoin(response.url, "./")
            candidate = urljoin(base, "objects.inv")
            resolved = probe_inventory_url(candidate)
            if resolved:
                return resolved
        except Exception:
            continue
    return None


def fetch_soup(url, description=""):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return BeautifulSoup(response.content, "html.parser")
    except Exception as e:
        print(f"Error fetching {url}: {e}", file=sys.stderr)
        return None


def get_inventory_stats(inv_url):
    """Fetch domain statistics from a Sphinx inventory file.

    Args:
        inv_url: URL to the Sphinx objects.inv file

    Returns:
        dict with 'total' count and 'domains' mapping domain->count
    """
    try:
        inv = soi.Inventory(url=inv_url)  # type: ignore[call-arg]  # sphobjinv lacks type stubs
        domains = {}
        for obj in inv.objects:
            domains[obj.domain] = domains.get(obj.domain, 0) + 1
        return {"total": len(inv.objects), "domains": domains}
    except Exception as e:
        print(f"Error fetching/parsing Sphinx inventory: {e}", file=sys.stderr)
        return {"total": 0, "domains": {}}


def get_sphinx_groups(inv_url, source_name, domains=None):
    """Fetch API groups from a Sphinx inventory file.

    Args:
        inv_url: URL to the Sphinx objects.inv file
        source_name: Name of the source library for tagging results
        domains: Set of domains to include, or None for all domains
    """
    try:
        # Let sphobjinv handle fetching/parsing to avoid API incompatibilities
        inv = soi.Inventory(url=inv_url)  # type: ignore[call-arg]  # sphobjinv lacks type stubs

        groups = []
        for obj in inv.objects:
            # Filter by domain if specified
            if domains is not None and obj.domain not in domains:
                continue

            # Sphinx inventory uses $ as placeholder for name
            raw_uri = obj.uri
            if "$" in raw_uri:
                final_url = urljoin(inv_url, raw_uri.replace("$", obj.name))
            else:
                final_url = urljoin(inv_url, raw_uri)

            groups.append(
                {
                    "group": obj.name,  # Function/Class name
                    "url": final_url,
                    "role": obj.role,
                    "domain": obj.domain,
                    "source": source_name,
                }
            )
        return groups
    except Exception as e:
        print(f"Error fetching/parsing Sphinx inventory: {e}", file=sys.stderr)
        return []


def get_all_groups(modules_url, source_name="cuda_runtime"):
    soup = fetch_soup(modules_url, "Modules Index")
    if not soup:
        return []

    groups = []
    seen_pages = set()
    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        if "group__" in href and "modules" not in href:
            full_url = urljoin(modules_url, href)
            page_url = full_url.split("#")[0]

            if page_url in seen_pages:
                continue
            seen_pages.add(page_url)

            group_name = a.get_text(strip=True)

            groups.append({"group": group_name, "url": full_url, "source": source_name})
    return groups


# Matches Doxygen member anchors like #group__HOST_1g56ff... within group pages
_DOXYGEN_MEMBER_RE = re.compile(r"^#(group__\w+_1\w+)")

# Map Doxygen section headings to Sphinx-compatible role names
_DOXYGEN_SECTION_ROLE = {
    "functions": "function",
    "typedefs": "type",
    "enumerations": "enum",
    "defines": "macro",
    "variables": "data",
}

# Split identifiers on CamelCase boundaries, underscores, colons, and hyphens
_SEGMENT_RE = re.compile(r"[_:\-]+|(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

# Role-based score adjustments applied to the base tier score
_ROLE_SCORE_ADJUST = {
    "function": 4,
    "type": 1,
    "enum": -3,
    "macro": 0,
    "enumerator": -8,
    "data": -3,
    "label": -10,
    "": -5,
}


def _tokenize_name(name):
    """Split an identifier into lowercase segments.

    >>> _tokenize_name('cutensornetTensorSVD')
    ['cutensornet', 'tensor', 'svd']
    >>> _tokenize_name('CUTENSOR_ALGO_SVD')
    ['cutensor', 'algo', 'svd']
    >>> _tokenize_name('cudaMemcpy')
    ['cuda', 'memcpy']
    """
    return [s.lower() for s in _SEGMENT_RE.split(name) if s]


def _score_entry(query, target, segments=None):
    """Score a query term against a target name using tiered matching.

    Tiers (base score before role adjustment):
      100 — full exact match (case-insensitive)
       97 — query matches a segment exactly
       94 — a segment starts with query
       88 — query is a substring of the full name
      ≤82 — rapidfuzz partial_ratio (capped)

    Args:
        query: Search term (will be lowercased)
        target: Candidate name (will be lowercased)
        segments: Pre-computed segments from _tokenize_name, or None
    """
    q = query.lower()
    t = target.lower()

    # For Doxygen signatures like "cudaFree ( void* devPtr )", extract the
    # bare name before lowering so CamelCase segmentation works correctly.
    bare_raw = target.split("(")[0].split(" (")[0].strip()
    bare = bare_raw.lower()

    if q == t or q == bare:
        return 100.0

    if segments is None:
        segments = _tokenize_name(target)

    # Tokenize the original-case bare name for accurate segment splitting
    bare_segments = _tokenize_name(bare_raw) if bare != t else segments

    for seg in bare_segments:
        if q == seg:
            return 97.0

    for seg in bare_segments:
        if seg.startswith(q):
            return 94.0

    if q in t or q in bare:
        return 88.0

    return min(fuzz.partial_ratio(q, t), 82.0)


def _extract_member_name(a_tag):
    """Extract a disambiguated member name from Doxygen HTML.

    Doxygen member summary rows typically have structure:
      <td class="memItemLeft">return_type</td>
      <td class="memItemRight"><a href="...">name</a> (params)</td>
    The parent <td> text includes the parameter list, which disambiguates
    overloaded functions like curand(curandStateXORWOW_t*) vs curand(curandStateMtgp32_t*).
    """
    bare_name = a_tag.get_text(strip=True)

    # Try parent <td> (summary table layout)
    for tag_name in ("td", "dt"):
        parent = a_tag.find_parent(tag_name)
        if parent:
            full_text = re.sub(r"\s+", " ", parent.get_text(" ", strip=True)).strip()
            if full_text and full_text != bare_name:
                return full_text

    return bare_name


def _get_section_role(tag):
    """Find the nearest preceding Doxygen section heading and return its role."""
    heading = tag.find_previous("h3", class_="member_header")
    if heading is None:
        return ""
    return _DOXYGEN_SECTION_ROLE.get(heading.get_text(strip=True).lower(), "")


def _resolve_doxygen_domain(page_url, library):
    """Determine domain for a Doxygen group page using registry config."""
    default_domain = library.get("default_domain", "")
    for pattern in library.get("cpp_groups", []):
        if pattern in page_url:
            return "cpp"
    return default_domain


def _parse_doxygen_page(page_url, source_name, library):
    """Fetch and parse a single Doxygen group page into member entries."""
    soup = fetch_soup(page_url, "Doxygen group page")
    if not soup:
        return []

    domain = _resolve_doxygen_domain(page_url, library)
    entries = []
    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        m = _DOXYGEN_MEMBER_RE.match(href)
        if not m:
            continue
        name = _extract_member_name(a)
        if not name:
            continue
        role = _get_section_role(a)
        entries.append(
            {
                "group": name,
                "url": page_url + href,
                "role": role,
                "domain": domain,
                "source": source_name,
            }
        )
    return entries


def get_doxygen_members(group_urls, source_name, library=None, max_workers=4):
    """Discover member-level entries from Doxygen group pages.

    Fetches group pages in parallel and extracts Doxygen member anchors
    (functions, typedefs, enums, defines, variables). Returns entries
    with inferred role and domain metadata.
    """
    from concurrent.futures import ThreadPoolExecutor

    if library is None:
        library = {}

    # Deduplicate page URLs (strip fragment)
    unique_pages = list(dict.fromkeys(url.split("#")[0] for url in group_urls))
    if not unique_pages:
        return []

    with ThreadPoolExecutor(max_workers=min(max_workers, len(unique_pages))) as pool:
        page_results = pool.map(
            lambda url: _parse_doxygen_page(url, source_name, library),
            unique_pages,
        )

    # Flatten and deduplicate by URL
    members = []
    seen = set()
    for entries in page_results:
        for entry in entries:
            if entry["url"] not in seen:
                seen.add(entry["url"])
                members.append(entry)
    return members


# Matches genindex entry text like "cutensorCreate (C++ function)"
_GENINDEX_ROLE_RE = re.compile(r"^(.+?)\s+\((\w+(?:\+\+)?)\s+(\w+)\)$")


def get_genindex_entries(genindex_url, source_name, domains=None):
    """Build a synthetic inventory from a Sphinx genindex.html page.

    Parses entries like ``cutensorCreate (C++ function)`` into structured
    dicts compatible with get_sphinx_groups() output format.
    """
    soup = fetch_soup(genindex_url, "genindex")
    if not soup:
        return []

    entries = []
    for table in soup.find_all("table", class_="indextable"):
        for li in table.find_all("li"):
            a = li.find("a", href=True)
            if not a:
                continue
            text = a.get_text(strip=True)
            m = _GENINDEX_ROLE_RE.match(text)
            if not m:
                continue
            name, lang, role = m.group(1), m.group(2), m.group(3)
            # Normalize language label to Sphinx domain name
            domain = {"C++": "cpp", "C": "c", "Python": "py"}.get(lang, lang.lower())
            if domains is not None and domain not in domains:
                continue
            full_url = urljoin(genindex_url, str(a["href"]))
            entries.append(
                {
                    "group": name,
                    "url": full_url,
                    "role": role,
                    "domain": domain,
                    "source": source_name,
                    "origin": "genindex",
                }
            )
    return entries


def format_list_row(
    name, url, role="", domain="", source="", score=None, matched_keyword=""
):
    """Format a single --list TSV row with consistent column layout."""
    line = f"{name}\t{url}\t{role}\t{domain}\t{source}"
    if score is not None:
        line += f"\t{score}\t{matched_keyword}"
    return line


def _parse_query_groups(keywords):
    """Split keyword tokens into OR-groups of AND-terms (fzf-subset syntax).

    Handles both shell-separated tokens and quoted strings:
      ['SVD', 'QR']        -> [['SVD', 'QR']]            # AND
      ['SVD', '|', 'QR']   -> [['SVD'], ['QR']]           # OR
      ['SVD | QR']          -> [['SVD'], ['QR']]           # OR (quoted)
      ['a', 'b', '|', 'c'] -> [['a', 'b'], ['c']]         # (a AND b) OR c
    """
    all_tokens = " ".join(keywords).split()
    groups = []
    current = []
    for token in all_tokens:
        if token == "|":
            if current:
                groups.append(current)
            current = []
        else:
            current.append(token)
    if current:
        groups.append(current)
    return [g for g in groups if g]


def filter_groups(groups, keywords, use_fuzzy=False, threshold=60.0):
    if not keywords:
        return groups

    query_groups = _parse_query_groups(keywords)
    if not query_groups:
        return []

    if use_fuzzy:
        segments_cache = [_tokenize_name(g["group"]) for g in groups]

        best_matches = {}
        for index, g in enumerate(groups):
            role = g.get("role", "")
            adjust = _ROLE_SCORE_ADJUST.get(role, 0)

            best_group_score = None
            best_group_terms = None

            for or_group in query_groups:
                # AND: entry must pass threshold for every term in the group
                term_scores = []
                for term in or_group:
                    base = _score_entry(term, g["group"], segments_cache[index])
                    # Threshold on text-match quality only (before role adjust)
                    if base < threshold:
                        break
                    term_scores.append(base)
                else:
                    # All terms matched — score is min (weakest link)
                    group_score = min(term_scores)
                    # Apply role adjustment for ranking only
                    ranked_score = max(0.0, min(group_score + adjust, 100.0))
                    if best_group_score is None or ranked_score > best_group_score:
                        best_group_score = ranked_score
                        best_group_terms = or_group

            if best_group_score is not None:
                key = g["url"]
                if (
                    key not in best_matches
                    or best_group_score > best_matches[key]["score"]
                ):
                    item_copy = g.copy()
                    item_copy["score"] = best_group_score
                    item_copy["matched_keyword"] = ",".join(best_group_terms)
                    best_matches[key] = item_copy

        filtered = list(best_matches.values())
        filtered.sort(key=lambda x: -x["score"])
        return filtered

    # Non-fuzzy fallback with AND/OR
    filtered = []
    seen = set()
    for or_group in query_groups:
        for g in groups:
            key = g.get("url", id(g))
            if key in seen:
                continue
            name_lower = g["group"].lower()
            if all(term.lower() in name_lower for term in or_group):
                filtered.append(g)
                seen.add(key)

    return filtered


def get_library_config(registry, name):
    """Look up a library by exact name, then by tag match."""
    libraries = registry.get("library", [])
    for lib in libraries:
        if lib.get("name") == name:
            return lib
    # Fall back to case-insensitive tag lookup
    name_lower = name.lower()
    for lib in libraries:
        if any(t.lower() == name_lower for t in lib.get("tags", [])):
            return lib
    return None


@dataclass
class GatherResult:
    """Result of gathering groups from a single source."""

    requested_source: str
    canonical_source: str
    groups: list = field(default_factory=list)
    skipped_reason: str | None = None
    doc_url: str | None = None
    warnings: list = field(default_factory=list)


def gather_groups_for_source(requested_source, library, domains_filter):
    """Gather all searchable groups from a single library source.

    Returns a GatherResult with groups and any warnings.
    This function records warnings on the result for the caller to handle,
    but underlying helper functions may still emit errors to stderr.
    """
    source_name = library["name"]
    doc_type = library.get("doc_type")
    result = GatherResult(
        requested_source=requested_source, canonical_source=source_name
    )

    try:
        return _gather_groups_impl(result, library, doc_type, domains_filter)
    except Exception as e:
        result.warnings.append(f"'{requested_source}': fetch failed ({e}), skipping")
        result.skipped_reason = "fetch error"
        return result


def _gather_groups_impl(result, library, doc_type, domains_filter):
    """Inner implementation of gather — separated so caller can catch exceptions."""
    requested_source = result.requested_source
    source_name = result.canonical_source

    if doc_type == "sphinx":
        inventory_urls = library.get("inventory_urls", [])
        base_urls = library.get("base_urls", [])
        env_override = os.getenv("CCCL_INV_URL") if library["name"] == "cccl" else None
        inv_url = resolve_inventory_url(
            inventory_urls, base_urls, env_override=env_override
        )
        if not inv_url:
            result.warnings.append(
                f"'{requested_source}': no valid objects.inv found, skipping"
            )
            result.skipped_reason = "no inventory"
            return result
        result.groups = get_sphinx_groups(inv_url, source_name, domains_filter)

    elif doc_type == "doxygen":
        index_url = library.get("index_url", MODULES_URL)
        top_groups = get_all_groups(index_url, source_name=source_name)
        group_urls = [g["url"] for g in top_groups]
        members = get_doxygen_members(
            group_urls, source_name=source_name, library=library
        )
        if domains_filter is not None:
            members = [m for m in members if m.get("domain") in domains_filter]
        result.groups = top_groups + members

    elif doc_type == "sphinx_noinv":
        index_url = library.get("index_url", "")
        genindex_url = urljoin(index_url.rstrip("/") + "/", "genindex.html")
        all_groups = get_genindex_entries(genindex_url, source_name)
        if not all_groups:
            result.doc_url = index_url
            result.warnings.append(
                f"'{requested_source}' ({doc_type}): no genindex available, skipping"
            )
            result.skipped_reason = "no genindex"
            return result
        if domains_filter is not None:
            all_groups = [g for g in all_groups if g.get("domain") in domains_filter]
        result.groups = all_groups

    elif doc_type == "pdf":
        result.doc_url = library.get("doc_url") or library.get("index_url", "")
        result.warnings.append(
            f"'{requested_source}' (pdf) does not support symbol search, skipping"
        )
        result.skipped_reason = "pdf"

    else:
        result.warnings.append(
            f"'{requested_source}': unsupported doc_type '{doc_type}', skipping"
        )
        result.skipped_reason = f"unsupported doc_type: {doc_type}"

    # Normalize source field to requested name for consistent output
    if requested_source != source_name:
        for g in result.groups:
            g["source"] = requested_source

    return result


def parse_domains(domains_str):
    """Parse comma-separated domain string into a set.

    Args:
        domains_str: Comma-separated domains (e.g. 'cpp,c,std') or 'all'

    Returns:
        Set of domain strings, or None if 'all'
    """
    if domains_str is None or domains_str.lower() == "all":
        return None
    return set(d.strip() for d in domains_str.split(",") if d.strip())


def main():
    parser = argparse.ArgumentParser(
        description="Topology Mapper: Discover API groups matching keywords."
    )
    parser.add_argument(
        "--keywords",
        nargs="+",
        help=(
            "Keywords to filter API groups. Space-separated terms are AND; "
            "use '|' for OR (requires shell quoting). "
            "Example: --keywords SVD batch  (AND), --keywords 'SVD | QR'  (OR)"
        ),
    )
    parser.add_argument(
        "--json", action="store_true", help="Output in JSON format (default)"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Output in TSV format (name\\turl\\trole\\tdomain\\tsource[\\tscore\\tmatched_keyword]) for fzf",
    )
    parser.add_argument(
        "--fuzzy", action="store_true", help="Use fuzzy matching (requires rapidfuzz)"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Fuzzy match threshold (0-100); defaults to registry match_threshold or 60.0",
    )
    parser.add_argument(
        "--source",
        nargs="+",
        default=["cuda_runtime"],
        help="Documentation source(s). Specify multiple to search across libraries.",
    )
    parser.add_argument(
        "--registry", default=DEFAULT_REGISTRY_PATH, help="Registry TOML path"
    )
    parser.add_argument(
        "--domains",
        default="all",
        help="Comma-separated domains to include (e.g. 'cpp,c,std') or 'all' (default: all)",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show domain statistics for the inventory instead of searching",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of results to return (must be >= 1)",
    )

    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be >= 1")
    if args.stats and len(args.source) > 1:
        parser.error("--stats requires a single --source")
    domains_filter = parse_domains(args.domains)

    registry = load_registry(args.registry)
    if isinstance(registry, str):
        print(f"Error: {registry}", file=sys.stderr)
        sys.exit(1)

    # --- Single-source path (preserves existing behavior exactly) ---
    if len(args.source) == 1:
        _main_single_source(args, registry, domains_filter)
    else:
        _main_multi_source(args, registry, domains_filter)


def _main_single_source(args, registry, domains_filter):
    """Original single-source path — kept unchanged for backward compatibility."""
    source = args.source[0]

    library = get_library_config(registry, source)
    if not library:
        print(f"Error: source '{source}' not found in registry", file=sys.stderr)
        sys.exit(1)

    # Resolve fuzzy threshold: CLI flag > registry match_threshold > 60.0
    if args.threshold is None:
        args.threshold = library.get("match_threshold", 60.0)

    # Resolve inventory URL for sphinx sources
    inv_url = None
    doc_type = library.get("doc_type")
    if doc_type == "sphinx":
        inventory_urls = library.get("inventory_urls", [])
        base_urls = library.get("base_urls", [])
        env_override = os.getenv("CCCL_INV_URL") if library["name"] == "cccl" else None
        inv_url = resolve_inventory_url(
            inventory_urls, base_urls, env_override=env_override
        )

    # Handle --stats option
    if args.stats:
        if inv_url:
            stats = get_inventory_stats(inv_url)
            sorted_domains = sorted(stats["domains"].items(), key=lambda x: -x[1])
            output = {
                "source": source,
                "inventory_url": inv_url,
                "total": stats["total"],
                "domains": {d: c for d, c in sorted_domains},
            }
        elif doc_type == "sphinx":
            print(
                "Error: could not resolve Sphinx inventory for --stats",
                file=sys.stderr,
            )
            sys.exit(1)
        elif doc_type == "doxygen":
            index_url = library.get("index_url", MODULES_URL)
            top_groups = get_all_groups(index_url, source_name=source)
            group_urls = [g["url"] for g in top_groups]
            members = get_doxygen_members(
                group_urls, source_name=source, library=library
            )
            domains = {}
            for m in members:
                d = m.get("domain", "")
                domains[d] = domains.get(d, 0) + 1
            sorted_domains = sorted(domains.items(), key=lambda x: -x[1])
            output = {
                "source": source,
                "total": len(members),
                "domains": {d: c for d, c in sorted_domains},
            }
        else:
            print(
                f"Error: --stats is not supported for doc_type '{doc_type}'",
                file=sys.stderr,
            )
            sys.exit(1)
        print(json.dumps(output, indent=2))
        return

    # 1. Gather all candidates
    if doc_type == "sphinx":
        if not inv_url:
            print(
                "Error fetching/parsing Sphinx inventory: no valid objects.inv found",
                file=sys.stderr,
            )
            all_groups = []
        else:
            all_groups = get_sphinx_groups(inv_url, source, domains_filter)
    elif doc_type == "doxygen":
        index_url = library.get("index_url", MODULES_URL)
        top_groups = get_all_groups(index_url, source_name=source)
        group_urls = [g["url"] for g in top_groups]
        members = get_doxygen_members(group_urls, source_name=source, library=library)
        if domains_filter is not None:
            members = [m for m in members if m.get("domain") in domains_filter]
        all_groups = top_groups + members
    elif doc_type == "sphinx_noinv":
        index_url = library.get("index_url", "")
        genindex_url = urljoin(index_url.rstrip("/") + "/", "genindex.html")
        all_groups = get_genindex_entries(genindex_url, source)
        if not all_groups:
            doc_url = index_url
            label = "docs (no inventory)"
            message = (
                f"'{source}' has no Sphinx inventory for symbol search. "
                "Browse the documentation directly."
            )
            if args.list:
                print(format_list_row(f"[{label}]", doc_url, source=source))
            else:
                output = {
                    "source": source,
                    "total_found": 0,
                    "filtered_count": 0,
                    "domains_filter": args.domains,
                    "candidates": [],
                    "doc_type": doc_type,
                    "doc_url": doc_url,
                    "message": message,
                }
                print(json.dumps(output, indent=2))
            return
        if domains_filter is not None:
            all_groups = [g for g in all_groups if g.get("domain") in domains_filter]
    elif doc_type == "pdf":
        doc_url = library.get("doc_url") or library.get("index_url", "")
        label = "PDF manual"
        message = (
            f"'{source}' is distributed as a PDF manual only. "
            "Symbol search is not available. "
            "Download the PDF to read the documentation."
        )
        if args.list:
            print(format_list_row(f"[{label}]", doc_url, source=source))
        else:
            output = {
                "source": source,
                "total_found": 0,
                "filtered_count": 0,
                "domains_filter": args.domains,
                "candidates": [],
                "doc_type": doc_type,
                "doc_url": doc_url,
                "message": message,
            }
            print(json.dumps(output, indent=2))
        return
    else:
        print(
            f"Error: unsupported doc_type '{doc_type}' for source '{source}'",
            file=sys.stderr,
        )
        sys.exit(1)

    # 2. Apply filter
    if args.keywords:
        candidates = filter_groups(
            all_groups, args.keywords, use_fuzzy=args.fuzzy, threshold=args.threshold
        )
    else:
        candidates = all_groups

    filtered_count = len(candidates)
    if args.limit is not None:
        candidates = candidates[: args.limit]

    # 3. Output results
    if args.list:
        for c in candidates:
            print(
                format_list_row(
                    c["group"],
                    c["url"],
                    role=c.get("role", ""),
                    domain=c.get("domain", ""),
                    source=c.get("source", ""),
                    score=c.get("score"),
                    matched_keyword=c.get("matched_keyword", ""),
                )
            )
    else:
        output = {
            "source": source,
            "total_found": len(all_groups),
            "filtered_count": filtered_count,
            "domains_filter": args.domains,
            "candidates": candidates,
        }
        print(json.dumps(output, indent=2))


def _main_multi_source(args, registry, domains_filter):
    """Multi-source search: parallel fetch, per-source filter, merged output."""
    # Validate all sources and dedupe by canonical name before fetching
    seen = {}
    libraries = []
    for name in args.source:
        lib = get_library_config(registry, name)
        if not lib:
            print(f"Error: source '{name}' not found in registry", file=sys.stderr)
            sys.exit(1)
        canonical = lib["name"]
        if canonical not in seen:
            seen[canonical] = name
            libraries.append((name, lib))

    # Parallel fetch
    max_workers = min(8, len(libraries))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        gather_results = list(
            pool.map(
                lambda item: gather_groups_for_source(item[0], item[1], domains_filter),
                libraries,
            )
        )

    # Collect warnings and print in source order
    for gr in gather_results:
        for w in gr.warnings:
            print(f"Warning: {w}", file=sys.stderr)

    # Per-source filtering with per-source threshold
    per_source_filtered = []
    total_found_per_source = {}
    for gr in gather_results:
        total_found_per_source[gr.requested_source] = len(gr.groups)
        if gr.skipped_reason:
            continue
        if args.keywords:
            threshold = args.threshold
            if threshold is None:
                lib = get_library_config(registry, gr.canonical_source)
                threshold = lib.get("match_threshold", 60.0) if lib else 60.0
            filtered = filter_groups(
                gr.groups,
                args.keywords,
                use_fuzzy=args.fuzzy,
                threshold=threshold,
            )
        else:
            filtered = gr.groups
        per_source_filtered.append(filtered)

    # Merge: k-way merge for fuzzy (score-sorted), concatenation for non-fuzzy
    if args.fuzzy and args.keywords:
        merged = heapq_merge(*per_source_filtered, key=lambda g: -g.get("score", 0))
    else:
        merged = chain(*per_source_filtered)

    filtered_count = sum(len(r) for r in per_source_filtered)
    if args.limit is not None:
        candidates = list(islice(merged, args.limit))
    else:
        candidates = list(merged)

    # Output
    requested_sources = [gr.requested_source for gr in gather_results]
    if args.list:
        for c in candidates:
            print(
                format_list_row(
                    c["group"],
                    c["url"],
                    role=c.get("role", ""),
                    domain=c.get("domain", ""),
                    source=c.get("source", ""),
                    score=c.get("score"),
                    matched_keyword=c.get("matched_keyword", ""),
                )
            )
        # Emit fallback rows for skipped sources so fzf users can still reach docs
        for gr in gather_results:
            if gr.skipped_reason and gr.doc_url:
                label = (
                    "[PDF manual]"
                    if gr.skipped_reason == "pdf"
                    else "[docs (no inventory)]"
                )
                print(format_list_row(label, gr.doc_url, source=gr.requested_source))
    else:
        output = {
            "sources": requested_sources,
            "total_found": total_found_per_source,
            "filtered_count": filtered_count,
            "domains_filter": args.domains,
            "candidates": candidates,
        }
        # Include browse URLs for skipped sources so users can still reach docs
        skipped = {
            gr.requested_source: gr.doc_url
            for gr in gather_results
            if gr.skipped_reason and gr.doc_url
        }
        if skipped:
            output["skipped_sources"] = skipped
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
