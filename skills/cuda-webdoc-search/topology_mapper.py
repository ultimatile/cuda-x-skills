# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "requests",
#     "beautifulsoup4",
#     "rapidfuzz",
#     "sphobjinv",
# ]
# ///

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
DEFAULT_REGISTRY_PATH = "prototype/registry.toml"
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
        return BeautifulSoup(response.content, 'html.parser')
    except Exception as e:
        print(f"Error fetching {url}: {e}", file=sys.stderr)
        return None

def get_cccl_groups(inv_url):
    try:
        # Let sphobjinv handle fetching/parsing to avoid API incompatibilities
        inv = soi.Inventory(url=inv_url)
        
        groups = []
        for obj in inv.objects:
            # Filter for C++ functions/classes/etc useful for mining
            # obj.domain='cpp', obj.role='function' or 'class' might be best
            # For broad mapping, let's take mostcpp items
            if obj.domain == 'cpp':
                # Sphinx inventory uses $ as placeholder for name
                raw_uri = obj.uri
                if "$" in raw_uri:
                    final_url = urljoin(inv_url, raw_uri.replace("$", obj.name))
                else:
                    final_url = urljoin(inv_url, raw_uri)

                groups.append({
                    "group": obj.name, # Function/Class name
                    "url": final_url,
                    "role": obj.role,
                    "source": "cccl"
                })
        return groups
    except Exception as e:
        print(f"Error fetching/parsing Sphinx inventory: {e}", file=sys.stderr)
        return []

def get_all_groups(modules_url):
    soup = fetch_soup(modules_url, "Modules Index")
    if not soup:
        return []

    groups = []
    seen_urls = set()
    for a in soup.find_all('a', href=True):
        href = a['href']
        if "group__" in href and "modules" not in href:
            full_url = urljoin(modules_url, href)
            page_url = full_url.split('#')[0]
            
            if page_url in seen_urls:
                continue
            seen_urls.add(page_url)

            group_name = a.get_text(strip=True)
            
            groups.append({
                "group": group_name,
                "url": page_url,
                "source": "cuda_runtime"
            })
    return groups

def filter_groups(groups, keywords, use_fuzzy=False, threshold=60.0):
    if not keywords:
        return groups

    filtered = []
    
    # Pre-process group names for fuzzy matching
    group_names = [g['group'] for g in groups]
    
    # Track best matches by group to avoid duplicates but keep highest score
    best_matches = {}

    for kw in keywords:
        if use_fuzzy:
            # Use RapidFuzz to find matches
            results = process.extract(kw, group_names, scorer=fuzz.partial_ratio, limit=None)
            
            for match, score, index in results:
                if score >= threshold:
                    item = groups[index]
                    key = item['url'] # Use URL as unique identifier
                    
                    if key not in best_matches or score > best_matches[key]['score']:
                        # Update if this is a better match
                        item_copy = item.copy()
                        item_copy['score'] = score
                        item_copy['matched_keyword'] = kw
                        best_matches[key] = item_copy
    
    if use_fuzzy:
        filtered = list(best_matches.values())
        filtered.sort(key=lambda x: x.get('score', 0), reverse=True)
        return filtered

    # Non-fuzzy fallback
    for kw in keywords:
        kw_lower = kw.lower()
        for g in groups:
            if kw_lower in g['group'].lower():
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

def main():
    parser = argparse.ArgumentParser(description="Topology Mapper: Discover API groups matching keywords.")
    parser.add_argument("--keywords", nargs="+", help="Keywords to filter API groups (e.g. 'Memory', 'Stream')")
    parser.add_argument("--json", action="store_true", help="Output in JSON format (default)")
    parser.add_argument("--list", action="store_true", help="Output in line-oriented format (name\\turl) for fzf")
    parser.add_argument("--fuzzy", action="store_true", help="Use fuzzy matching (requires rapidfuzz)")
    parser.add_argument("--threshold", type=float, default=60.0, help="Fuzzy match threshold (0-100)")
    parser.add_argument("--source", default="cuda_runtime", help="Documentation source")
    parser.add_argument("--registry", default=DEFAULT_REGISTRY_PATH, help="Registry TOML path")
    
    args = parser.parse_args()
    
    registry = load_registry(args.registry)
    library = get_library_config(registry, args.source) if registry else None

    if registry and not library:
        print(f"Error: source '{args.source}' not found in registry", file=sys.stderr)
        sys.exit(1)

    # 1. Gather all candidates
    if library:
        doc_type = library.get("doc_type")
        if doc_type == "sphinx":
            inventory_urls = library.get("inventory_urls", [])
            base_urls = library.get("base_urls", [])
            env_override = os.getenv("CCCL_INV_URL") if args.source == "cccl" else None
            inv_url = resolve_inventory_url(inventory_urls, base_urls, env_override=env_override)
            if not inv_url:
                print("Error fetching/parsing Sphinx inventory: no valid objects.inv found", file=sys.stderr)
                all_groups = []
            else:
                all_groups = get_cccl_groups(inv_url)
        elif doc_type == "doxygen":
            index_url = library.get("index_url", MODULES_URL)
            all_groups = get_all_groups(index_url)
        else:
            print(f"Error: unsupported doc_type '{doc_type}' for source '{args.source}'", file=sys.stderr)
            sys.exit(1)
    else:
        if args.source == "cccl":
            inv_url = resolve_inventory_url(CCCL_INV_CANDIDATES, CCCL_BASE_URLS, env_override=os.getenv("CCCL_INV_URL"))
            if not inv_url:
                print("Error fetching/parsing Sphinx inventory: no valid objects.inv found", file=sys.stderr)
                all_groups = []
            else:
                all_groups = get_cccl_groups(inv_url)
        else:
            all_groups = get_all_groups(MODULES_URL)
    
    # 2. Apply filter
    if args.keywords:
        candidates = filter_groups(all_groups, args.keywords, use_fuzzy=args.fuzzy, threshold=args.threshold)
    else:
        candidates = all_groups
    
    # 3. Output results
    if args.list:
        for c in candidates:
            print(f"{c['group']}\t{c['url']}")
    else:
        output = {
            "source": args.source,
            "total_found": len(all_groups),
            "filtered_count": len(candidates),
            "candidates": candidates
        }
        print(json.dumps(output, indent=2))

if __name__ == "__main__":
    main()
