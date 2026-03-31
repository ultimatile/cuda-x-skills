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
import tomllib
from urllib.parse import urljoin
from rapidfuzz import process, fuzz

import sphobjinv as soi

BASE_URL = "https://docs.nvidia.com/cuda/cuda-runtime-api/"
MODULES_URL = urljoin(BASE_URL, "modules.html")
DEFAULT_REGISTRY_PATH = "registry.toml"
CCCL_INV_URL = "https://nvidia.github.io/cccl/libcudacxx/objects.inv"
CCCL_INV_CANDIDATES = [
    CCCL_INV_URL,
    "https://nvidia.github.io/cccl/objects.inv",
    "https://nvidia.github.io/libcudacxx/objects.inv",
    "https://nvidia.github.io/libcudacxx/latest/objects.inv",
    "https://nvidia.github.io/cccl/libcudacxx/latest/objects.inv",
    "https://docs.nvidia.com/cccl/libcudacxx/objects.inv",
    "https://docs.nvidia.com/cccl/objects.inv",
]
CCCL_BASE_URLS = [
    "https://nvidia.github.io/cccl/libcudacxx/",
    "https://nvidia.github.io/cccl/",
    "https://nvidia.github.io/libcudacxx/",
    "https://docs.nvidia.com/cccl/libcudacxx/",
    "https://docs.nvidia.com/cccl/",
]


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
        inv = soi.Inventory(url=inv_url)
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
        inv = soi.Inventory(url=inv_url)

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
        href = a["href"]
        if "group__" in href and "modules" not in href:
            full_url = urljoin(modules_url, href)
            page_url = full_url.split("#")[0]

            if page_url in seen_pages:
                continue
            seen_pages.add(page_url)

            group_name = a.get_text(strip=True)

            groups.append(
                {"group": group_name, "url": full_url, "source": source_name}
            )
    return groups


# Matches Doxygen member anchors like #group__HOST_1g56ff... within group pages
_DOXYGEN_MEMBER_RE = re.compile(r"^#(group__\w+_1\w+)")


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


def get_doxygen_members(group_urls, source_name):
    """Discover function-level members from Doxygen group pages.

    Fetches each group page and extracts same-page anchor links that point to
    individual API function entries (Doxygen member anchors).
    """
    members = []
    seen = set()
    fetched_pages = set()
    for group_url in group_urls:
        page_url = group_url.split("#")[0]
        if page_url in fetched_pages:
            continue
        fetched_pages.add(page_url)

        soup = fetch_soup(page_url, "Doxygen group page")
        if not soup:
            continue

        for a in soup.find_all("a", href=True):
            href = a["href"]
            m = _DOXYGEN_MEMBER_RE.match(href)
            if not m:
                continue
            full_url = page_url + href
            if full_url in seen:
                continue
            seen.add(full_url)

            name = _extract_member_name(a)
            if not name:
                continue
            members.append(
                {"group": name, "url": full_url, "source": source_name}
            )
    return members


def filter_groups(groups, keywords, use_fuzzy=False, threshold=60.0):
    if not keywords:
        return groups

    filtered = []

    # Pre-process group names for fuzzy matching
    group_names = [g["group"] for g in groups]

    # Track best matches by group to avoid duplicates but keep highest score
    best_matches = {}

    for kw in keywords:
        if use_fuzzy:
            # Use RapidFuzz to find matches
            results = process.extract(
                kw, group_names, scorer=fuzz.partial_ratio, limit=None
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


def load_registry(path):
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"Error reading registry {path}: {e}", file=sys.stderr)
        return None


def get_library_config(registry, name):
    libraries = registry.get("library", [])
    for lib in libraries:
        if lib.get("name") == name:
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
        help="Output in line-oriented format (name\\turl) for fzf",
    )
    parser.add_argument(
        "--fuzzy", action="store_true", help="Use fuzzy matching (requires rapidfuzz)"
    )
    parser.add_argument(
        "--threshold", type=float, default=60.0, help="Fuzzy match threshold (0-100)"
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
    library = get_library_config(registry, args.source) if registry else None

    if registry and not library:
        print(f"Error: source '{args.source}' not found in registry", file=sys.stderr)
        sys.exit(1)

    # Resolve inventory URL for sphinx sources
    inv_url = None
    if library:
        doc_type = library.get("doc_type")
        if doc_type == "sphinx":
            inventory_urls = library.get("inventory_urls", [])
            base_urls = library.get("base_urls", [])
            env_override = os.getenv("CCCL_INV_URL") if args.source == "cccl" else None
            inv_url = resolve_inventory_url(
                inventory_urls, base_urls, env_override=env_override
            )
    elif args.source == "cccl":
        inv_url = resolve_inventory_url(
            CCCL_INV_CANDIDATES,
            CCCL_BASE_URLS,
            env_override=os.getenv("CCCL_INV_URL"),
        )

    # Handle --stats option
    if args.stats:
        if inv_url:
            stats = get_inventory_stats(inv_url)
            # Sort domains by count descending
            sorted_domains = sorted(stats["domains"].items(), key=lambda x: -x[1])
            output = {
                "source": args.source,
                "inventory_url": inv_url,
                "total": stats["total"],
                "domains": {d: c for d, c in sorted_domains},
            }
            print(json.dumps(output, indent=2))
        else:
            print(
                f"Error: --stats requires a sphinx source with valid inventory",
                file=sys.stderr,
            )
            sys.exit(1)
        return

    # 1. Gather all candidates
    # effective_source tracks the actual data source, which may differ from
    # args.source when the registry-miss fallback silently switches to cuda_runtime.
    effective_source = args.source
    if library:
        doc_type = library.get("doc_type")
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
            members = get_doxygen_members(group_urls, source_name=args.source)
            all_groups = top_groups + members
        elif doc_type == "pdf":
            doc_url = library.get("doc_url", "")
            if args.list:
                print(f"[PDF manual]\t{doc_url}")
            else:
                output = {
                    "source": args.source,
                    "doc_type": "pdf",
                    "doc_url": doc_url,
                    "message": f"'{args.source}' is distributed as a PDF manual only. "
                    "Symbol search is not available. "
                    "Download the PDF to read the documentation.",
                }
                print(json.dumps(output, indent=2))
            return
        else:
            print(
                f"Error: unsupported doc_type '{doc_type}' for source '{args.source}'",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        if args.source == "cccl":
            if not inv_url:
                print(
                    "Error fetching/parsing Sphinx inventory: no valid objects.inv found",
                    file=sys.stderr,
                )
                all_groups = []
            else:
                all_groups = get_sphinx_groups(inv_url, "cccl", domains_filter)
        else:
            effective_source = "cuda_runtime"
            top_groups = get_all_groups(MODULES_URL, source_name=effective_source)
            group_urls = [g["url"] for g in top_groups]
            members = get_doxygen_members(group_urls, source_name=effective_source)
            all_groups = top_groups + members

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
            print(f"{c['group']}\t{c['url']}")
    else:
        output = {
            "source": effective_source,
            "total_found": len(all_groups),
            "filtered_count": len(candidates),
            "domains_filter": args.domains,
            "candidates": candidates,
        }
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
