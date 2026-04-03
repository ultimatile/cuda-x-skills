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
from urllib.parse import urljoin
from rapidfuzz import process, fuzz

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


def filter_groups(groups, keywords, use_fuzzy=False, threshold=60.0):
    if not keywords:
        return groups

    filtered = []

    # Track best matches by group to avoid duplicates but keep highest score
    best_matches = {}
    group_names_lower = None

    for kw in keywords:
        if use_fuzzy:
            if group_names_lower is None:
                group_names_lower = [g["group"].lower() for g in groups]
            results = process.extract(
                kw.lower(), group_names_lower, scorer=fuzz.partial_ratio, limit=None
            )

            for match, score, index in results:
                if score >= threshold:
                    item = groups[index]
                    key = item["url"]  # Use URL as unique identifier

                    if key not in best_matches or score > best_matches[key]["score"]:
                        # Update if this is a better match
                        item_copy = item.copy()
                        item_copy["score"] = score
                        item_copy["matched_keyword"] = kw
                        best_matches[key] = item_copy

    if use_fuzzy:
        filtered = list(best_matches.values())
        filtered.sort(key=lambda x: x.get("score", 0), reverse=True)
        return filtered

    # Non-fuzzy fallback
    for kw in keywords:
        kw_lower = kw.lower()
        for g in groups:
            if kw_lower in g["group"].lower():
                if g not in filtered:
                    filtered.append(g)

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
        help="Keywords to filter API groups (e.g. 'Memory', 'Stream')",
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
    parser.add_argument("--source", default="cuda_runtime", help="Documentation source")
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

    args = parser.parse_args()
    domains_filter = parse_domains(args.domains)

    registry = load_registry(args.registry)
    if isinstance(registry, str):
        print(f"Error: {registry}", file=sys.stderr)
        sys.exit(1)

    library = get_library_config(registry, args.source)
    if not library:
        print(f"Error: source '{args.source}' not found in registry", file=sys.stderr)
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
        # Use resolved library name for env override (handles aliases like thrust → cccl)
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
                "source": args.source,
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
            top_groups = get_all_groups(index_url, source_name=args.source)
            group_urls = [g["url"] for g in top_groups]
            members = get_doxygen_members(
                group_urls, source_name=args.source, library=library
            )
            domains = {}
            for m in members:
                d = m.get("domain", "")
                domains[d] = domains.get(d, 0) + 1
            sorted_domains = sorted(domains.items(), key=lambda x: -x[1])
            output = {
                "source": args.source,
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
            all_groups = get_sphinx_groups(inv_url, args.source, domains_filter)
    elif doc_type == "doxygen":
        index_url = library.get("index_url", MODULES_URL)
        top_groups = get_all_groups(index_url, source_name=args.source)
        group_urls = [g["url"] for g in top_groups]
        members = get_doxygen_members(
            group_urls, source_name=args.source, library=library
        )
        if domains_filter is not None:
            members = [m for m in members if m.get("domain") in domains_filter]
        all_groups = top_groups + members
    elif doc_type == "sphinx_noinv":
        # Try genindex.html as synthetic inventory fallback
        index_url = library.get("index_url", "")
        genindex_url = urljoin(index_url.rstrip("/") + "/", "genindex.html")
        # Fetch without domain filter first to distinguish "genindex unavailable"
        # from "genindex exists but no entries match the requested domain"
        all_groups = get_genindex_entries(genindex_url, args.source)
        if not all_groups:
            # genindex unavailable or empty — fall back to manual guidance
            doc_url = index_url
            label = "docs (no inventory)"
            message = (
                f"'{args.source}' has no Sphinx inventory for symbol search. "
                "Browse the documentation directly."
            )
            if args.list:
                print(format_list_row(f"[{label}]", doc_url, source=args.source))
            else:
                output = {
                    "source": args.source,
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
        # Apply domain filter after confirming genindex exists
        if domains_filter is not None:
            all_groups = [g for g in all_groups if g.get("domain") in domains_filter]
    elif doc_type == "pdf":
        doc_url = library.get("doc_url") or library.get("index_url", "")
        label = "PDF manual"
        message = (
            f"'{args.source}' is distributed as a PDF manual only. "
            "Symbol search is not available. "
            "Download the PDF to read the documentation."
        )
        if args.list:
            print(format_list_row(f"[{label}]", doc_url, source=args.source))
        else:
            output = {
                "source": args.source,
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
            f"Error: unsupported doc_type '{doc_type}' for source '{args.source}'",
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
            "source": args.source,
            "total_found": len(all_groups),
            "filtered_count": len(candidates),
            "domains_filter": args.domains,
            "candidates": candidates,
        }
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
