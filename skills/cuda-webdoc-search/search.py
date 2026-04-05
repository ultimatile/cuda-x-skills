"""Search CUDA-X library documentation for API symbols."""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from heapq import merge as heapq_merge
from itertools import chain, islice
from typing import Annotated, Optional
from urllib.parse import urljoin

import typer

import fetchers
import registry
import scoring


class OutputFormat(str, Enum):
    json = "json"
    tsv = "tsv"


def get_library_config(reg, name):
    """Look up a library by exact name, then by tag match."""
    libraries = reg.get("library", [])
    for lib in libraries:
        if lib.get("name") == name:
            return lib
    name_lower = name.lower()
    for lib in libraries:
        if any(t.lower() == name_lower for t in lib.get("tags", [])):
            return lib
    return None


def parse_domains(domains_str):
    """Parse comma-separated domain string into a set.

    Returns:
        Set of domain strings, or None if 'all'
    """
    if domains_str is None or domains_str.lower() == "all":
        return None
    return set(d.strip() for d in domains_str.split(",") if d.strip())


def format_list_row(
    name, url, role="", domain="", source="", score=None, matched_keyword=""
):
    """Format a single TSV row with consistent column layout."""
    line = f"{name}\t{url}\t{role}\t{domain}\t{source}"
    if score is not None:
        line += f"\t{score}\t{matched_keyword}"
    return line


def search(
    sources: Annotated[
        Optional[list[str]],
        typer.Argument(help="Documentation source(s). Defaults to cuda_runtime."),
    ] = None,
    keywords: Annotated[
        Optional[str],
        typer.Option(
            help=(
                "Filter keywords (quote the value). "
                "Space-separated=AND, '|'=OR. "
                "Examples: --keywords 'SVD batch', --keywords 'SVD | QR'"
            )
        ),
    ] = None,
    format: Annotated[
        OutputFormat, typer.Option("--format", help="Output format")
    ] = OutputFormat.json,
    fuzzy: Annotated[bool, typer.Option("--fuzzy", help="Use fuzzy matching")] = False,
    threshold: Annotated[
        Optional[float],
        typer.Option(help="Fuzzy match threshold (0-100)"),
    ] = None,
    registry_path: Annotated[
        str,
        typer.Option("--registry", help="Registry TOML path"),
    ] = registry.DEFAULT_REGISTRY_PATH,
    domains: Annotated[
        str, typer.Option(help="Comma-separated domains or 'all'")
    ] = "all",
    stats: Annotated[
        bool, typer.Option("--stats", help="Show domain statistics")
    ] = False,
    limit: Annotated[
        Optional[int], typer.Option(help="Maximum number of results (>= 1)")
    ] = None,
):
    """Discover API groups matching keywords across CUDA-X libraries."""
    if not sources:
        sources = ["cuda_runtime"]

    if limit is not None and limit < 1:
        print("Error: --limit must be >= 1", file=sys.stderr)
        raise typer.Exit(1)
    if stats and len(sources) > 1:
        print("Error: --stats requires a single source", file=sys.stderr)
        raise typer.Exit(1)

    domains_filter = parse_domains(domains)
    keywords_list = keywords.split() if keywords else None
    use_list = format == OutputFormat.tsv

    reg = registry.load_registry(registry_path)
    if isinstance(reg, str):
        print(f"Error: {reg}", file=sys.stderr)
        raise typer.Exit(1)

    if len(sources) == 1:
        _search_single(
            sources[0],
            reg,
            domains_filter,
            keywords_list,
            use_list,
            fuzzy,
            threshold,
            stats,
            limit,
            domains,
        )
    else:
        _search_multi(
            sources,
            reg,
            domains_filter,
            keywords_list,
            use_list,
            fuzzy,
            threshold,
            limit,
            domains,
        )


def _search_single(
    source,
    reg,
    domains_filter,
    keywords_list,
    use_list,
    fuzzy,
    threshold,
    stats,
    limit,
    domains_str,
):
    """Single-source search path."""
    library = get_library_config(reg, source)
    if not library:
        print(f"Error: source '{source}' not found in registry", file=sys.stderr)
        raise typer.Exit(1)

    if threshold is None:
        threshold = library.get("match_threshold", 60.0)

    inv_url = None
    doc_type = library.get("doc_type")
    if doc_type == "sphinx":
        inventory_urls = library.get("inventory_urls", [])
        base_urls = library.get("base_urls", [])
        env_override = os.getenv("CCCL_INV_URL") if library["name"] == "cccl" else None
        inv_url = fetchers.resolve_inventory_url(
            inventory_urls, base_urls, env_override=env_override
        )

    # Handle --stats
    if stats:
        _handle_stats(source, doc_type, inv_url, library)
        return

    # Gather all candidates
    all_groups = _gather_candidates(
        source, doc_type, library, inv_url, domains_filter, use_list, domains_str
    )
    if all_groups is None:
        return  # Early return paths (pdf, sphinx_noinv fallback) already printed output

    # Apply filter
    if keywords_list:
        candidates = scoring.filter_groups(
            all_groups, keywords_list, use_fuzzy=fuzzy, threshold=threshold
        )
    else:
        candidates = all_groups

    filtered_count = len(candidates)
    if limit is not None:
        candidates = candidates[:limit]

    # Output results
    if use_list:
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
            "domains_filter": domains_str,
            "candidates": candidates,
        }
        print(json.dumps(output, indent=2))


def _handle_stats(source, doc_type, inv_url, library):
    """Handle --stats output for a single source."""
    if inv_url:
        inv_stats = fetchers.get_inventory_stats(inv_url)
        sorted_domains = sorted(inv_stats["domains"].items(), key=lambda x: -x[1])
        output = {
            "source": source,
            "inventory_url": inv_url,
            "total": inv_stats["total"],
            "domains": {d: c for d, c in sorted_domains},
        }
    elif doc_type == "sphinx":
        print(
            "Error: could not resolve Sphinx inventory for --stats",
            file=sys.stderr,
        )
        raise typer.Exit(1)
    elif doc_type == "doxygen":
        index_url = library.get("index_url", fetchers.MODULES_URL)
        top_groups = fetchers.get_all_groups(index_url, source_name=source)
        group_urls = [g["url"] for g in top_groups]
        members = fetchers.get_doxygen_members(
            group_urls, source_name=source, library=library
        )
        domain_counts = {}
        for m in members:
            d = m.get("domain", "")
            domain_counts[d] = domain_counts.get(d, 0) + 1
        sorted_domains = sorted(domain_counts.items(), key=lambda x: -x[1])
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
        raise typer.Exit(1)
    print(json.dumps(output, indent=2))


def _gather_candidates(
    source, doc_type, library, inv_url, domains_filter, use_list, domains_str
):
    """Gather all candidates for a single source.

    Returns list of groups, or None if output was already printed (pdf/sphinx_noinv fallback).
    """
    if doc_type == "sphinx":
        if not inv_url:
            print(
                "Error fetching/parsing Sphinx inventory: no valid objects.inv found",
                file=sys.stderr,
            )
            return []
        return fetchers.get_sphinx_groups(inv_url, source, domains_filter)

    if doc_type == "doxygen":
        index_url = library.get("index_url", fetchers.MODULES_URL)
        top_groups = fetchers.get_all_groups(index_url, source_name=source)
        group_urls = [g["url"] for g in top_groups]
        members = fetchers.get_doxygen_members(
            group_urls, source_name=source, library=library
        )
        if domains_filter is not None:
            members = [m for m in members if m.get("domain") in domains_filter]
        return top_groups + members

    if doc_type == "sphinx_noinv":
        index_url = library.get("index_url", "")
        genindex_url = urljoin(index_url.rstrip("/") + "/", "genindex.html")
        all_groups = fetchers.get_genindex_entries(genindex_url, source)
        if not all_groups:
            doc_url = index_url
            label = "docs (no inventory)"
            message = (
                f"'{source}' has no Sphinx inventory for symbol search. "
                "Browse the documentation directly."
            )
            if use_list:
                print(format_list_row(f"[{label}]", doc_url, source=source))
            else:
                output = {
                    "source": source,
                    "total_found": 0,
                    "filtered_count": 0,
                    "domains_filter": domains_str,
                    "candidates": [],
                    "doc_type": doc_type,
                    "doc_url": doc_url,
                    "message": message,
                }
                print(json.dumps(output, indent=2))
            return None
        if domains_filter is not None:
            all_groups = [g for g in all_groups if g.get("domain") in domains_filter]
        return all_groups

    if doc_type == "pdf":
        doc_url = library.get("doc_url") or library.get("index_url", "")
        label = "PDF manual"
        message = (
            f"'{source}' is distributed as a PDF manual only. "
            "Symbol search is not available. "
            "Download the PDF to read the documentation."
        )
        if use_list:
            print(format_list_row(f"[{label}]", doc_url, source=source))
        else:
            output = {
                "source": source,
                "total_found": 0,
                "filtered_count": 0,
                "domains_filter": domains_str,
                "candidates": [],
                "doc_type": doc_type,
                "doc_url": doc_url,
                "message": message,
            }
            print(json.dumps(output, indent=2))
        return None

    print(
        f"Error: unsupported doc_type '{doc_type}' for source '{source}'",
        file=sys.stderr,
    )
    raise typer.Exit(1)


def _search_multi(
    sources,
    reg,
    domains_filter,
    keywords_list,
    use_list,
    fuzzy,
    threshold,
    limit,
    domains_str,
):
    """Multi-source search: parallel fetch, per-source filter, merged output."""
    seen = {}
    libraries = []
    for name in sources:
        lib = get_library_config(reg, name)
        if not lib:
            print(f"Error: source '{name}' not found in registry", file=sys.stderr)
            raise typer.Exit(1)
        canonical = lib["name"]
        if canonical not in seen:
            seen[canonical] = name
            libraries.append((name, lib))

    max_workers = min(8, len(libraries))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        gather_results = list(
            pool.map(
                lambda item: fetchers.gather_groups_for_source(
                    item[0], item[1], domains_filter
                ),
                libraries,
            )
        )

    for gr in gather_results:
        for w in gr.warnings:
            print(f"Warning: {w}", file=sys.stderr)

    per_source_filtered = []
    total_found_per_source = {}
    for gr in gather_results:
        total_found_per_source[gr.requested_source] = len(gr.groups)
        if gr.skipped_reason:
            continue
        if keywords_list:
            t = threshold
            if t is None:
                lib = get_library_config(reg, gr.canonical_source)
                t = lib.get("match_threshold", 60.0) if lib else 60.0
            filtered = scoring.filter_groups(
                gr.groups,
                keywords_list,
                use_fuzzy=fuzzy,
                threshold=t,
            )
        else:
            filtered = gr.groups
        per_source_filtered.append(filtered)

    if fuzzy and keywords_list:
        merged = heapq_merge(*per_source_filtered, key=lambda g: -g.get("score", 0))
    else:
        merged = chain(*per_source_filtered)

    filtered_count = sum(len(r) for r in per_source_filtered)
    if limit is not None:
        candidates = list(islice(merged, limit))
    else:
        candidates = list(merged)

    requested_sources = [gr.requested_source for gr in gather_results]
    if use_list:
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
            "domains_filter": domains_str,
            "candidates": candidates,
        }
        skipped = {
            gr.requested_source: gr.doc_url
            for gr in gather_results
            if gr.skipped_reason and gr.doc_url
        }
        if skipped:
            output["skipped_sources"] = skipped
        print(json.dumps(output, indent=2))
