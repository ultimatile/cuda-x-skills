"""Data fetching for Sphinx inventories, Doxygen pages, and genindex."""

import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urljoin

import requests
import sphobjinv as soi
from bs4 import BeautifulSoup

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
        inv = soi.Inventory(url=inv_url)  # type: ignore[call-arg]
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
        inv = soi.Inventory(url=inv_url)  # type: ignore[call-arg]

        groups = []
        for obj in inv.objects:
            if domains is not None and obj.domain not in domains:
                continue

            raw_uri = obj.uri
            if "$" in raw_uri:
                final_url = urljoin(inv_url, raw_uri.replace("$", obj.name))
            else:
                final_url = urljoin(inv_url, raw_uri)

            groups.append(
                {
                    "group": obj.name,
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
    if library is None:
        library = {}

    unique_pages = list(dict.fromkeys(url.split("#")[0] for url in group_urls))
    if not unique_pages:
        return []

    with ThreadPoolExecutor(max_workers=min(max_workers, len(unique_pages))) as pool:
        page_results = pool.map(
            lambda url: _parse_doxygen_page(url, source_name, library),
            unique_pages,
        )

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
    """Inner implementation — separated so caller can catch exceptions."""
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
