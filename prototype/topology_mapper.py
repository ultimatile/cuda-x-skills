# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "requests",
#     "beautifulsoup4",
#     "rapidfuzz",
# ]
# ///

import requests
from bs4 import BeautifulSoup
import json
import sys
import argparse
from urllib.parse import urljoin
from rapidfuzz import process, fuzz

BASE_URL = "https://docs.nvidia.com/cuda/cuda-runtime-api/"
MODULES_URL = urljoin(BASE_URL, "modules.html")

def fetch_soup(url, description=""):
    try:
        response = requests.get(url)
        response.raise_for_status()
        return BeautifulSoup(response.content, 'html.parser')
    except Exception as e:
        print(f"Error fetching {url}: {e}", file=sys.stderr)
        return None

def get_all_groups(modules_url):
    soup = fetch_soup(modules_url, "Modules Index")
    if not soup:
        return []

    groups = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        if "group__" in href and "modules" not in href:
            full_url = urljoin(modules_url, href)
            page_url = full_url.split('#')[0]
            group_name = a.get_text(strip=True)
            
            groups.append({
                "group": group_name,
                "url": page_url
            })
    return groups

def filter_groups(groups, keywords, use_fuzzy=False, threshold=60.0):
    if not keywords:
        return groups

    filtered = []
    
    # Pre-process group names for fuzzy matching
    group_names = [g['group'] for g in groups]
    
    for kw in keywords:
        if use_fuzzy:
            # Use RapidFuzz to find matches
            # process.extract returns list of (match, score, index)
            results = process.extract(kw, group_names, scorer=fuzz.partial_ratio, limit=None)
            
            for match, score, index in results:
                if score >= threshold:
                    # Avoid duplicates if multiple keywords match same group
                    item = groups[index]
                    if item not in filtered:
                        # Add score for debugging/ranking
                        item_copy = item.copy()
                        item_copy['score'] = score
                        item_copy['matched_keyword'] = kw
                        filtered.append(item_copy)
        else:
            # Simple substring match
            kw_lower = kw.lower()
            for g in groups:
                 if kw_lower in g['group'].lower():
                     if g not in filtered:
                         filtered.append(g)
            
    # If fuzzy, sort by score descending
    if use_fuzzy:
        filtered.sort(key=lambda x: x.get('score', 0), reverse=True)
        
    return filtered

def main():
    parser = argparse.ArgumentParser(description="Topology Mapper: Discover API groups matching keywords.")
    parser.add_argument("--keywords", nargs="+", help="Keywords to filter API groups (e.g. 'Memory', 'Stream')")
    parser.add_argument("--json", action="store_true", help="Output in JSON format (default)")
    parser.add_argument("--list", action="store_true", help="Output in line-oriented format (name\\turl) for fzf")
    parser.add_argument("--fuzzy", action="store_true", help="Use fuzzy matching (requires rapidfuzz)")
    parser.add_argument("--threshold", type=float, default=60.0, help="Fuzzy match threshold (0-100)")
    
    args = parser.parse_args()
    
    # 1. Gather all candidates
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
            "total_found": len(all_groups),
            "filtered_count": len(candidates),
            "candidates": candidates
        }
        print(json.dumps(output, indent=2))

if __name__ == "__main__":
    main()
