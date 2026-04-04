# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "requests",
#     "beautifulsoup4",
#     "rapidfuzz",
#     "sphobjinv",
# ]
# ///

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from heapq import merge as heapq_merge
from itertools import chain, islice
from urllib.parse import urljoin

from fetchers import (
    MODULES_URL,
    gather_groups_for_source,
    get_all_groups,
    get_doxygen_members,
    get_genindex_entries,
    get_inventory_stats,
    get_sphinx_groups,
    resolve_inventory_url,
)
from registry import DEFAULT_REGISTRY_PATH, load_registry
from scoring import filter_groups


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


def format_list_row(
    name, url, role="", domain="", source="", score=None, matched_keyword=""
):
    """Format a single --list TSV row with consistent column layout."""
    line = f"{name}\t{url}\t{role}\t{domain}\t{source}"
    if score is not None:
        line += f"\t{score}\t{matched_keyword}"
    return line


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
