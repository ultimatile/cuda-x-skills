# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "requests",
#     "beautifulsoup4",
# ]
# ///

import requests
from bs4 import BeautifulSoup
import json
import sys
import argparse
import os

def fetch_content(source):
    if os.path.exists(source):
        with open(source, 'r', encoding='utf-8') as f:
            return f.read()
    else:
        try:
            response = requests.get(source, timeout=10)
            response.raise_for_status()
            return response.content
        except Exception as e:
            print(f"Error fetching {source}: {e}", file=sys.stderr)
            return None

def extract_sphinx_items(soup):
    """Extraction logic for Sphinx-generated docs (CCCL)"""
    api_items = []
    # Sphinx typically uses <dl> for definitions
    # Look for dl with class "cpp function" or similar, or just check dt with sig-object
    
    definitions = soup.find_all("dl")
    for dl in definitions:
        # Sphinx puts multiple <dt> items before a <dd> if there are overloads
        # Or sometimes interleaved. We need to handle dt/dd pairing carefully.
        # But commonly in standard docs: dt, dt, dd
        
        # Collect all signatures in this dl block
        current_description = ""
        dd = dl.find("dd")
        if dd:
            current_description = dd.get_text(" ", strip=True)
            current_description = current_description[:300] + "..." if len(current_description) > 300 else current_description

        dts = dl.find_all("dt")
        for dt in dts:
            try:
                if "sig-object" not in dt.get("class", []):
                     # Newer sphinx might strictly use sig-object, or check parent class
                     # For now, if it's in a dl.cpp/function block, assume it's relevant
                     # But check if it really looks like a signature
                     if not dt.get("id"):
                         continue

                # Signature extraction
                # Remove headerlink if present - duplicate soup to not destroy original if shared?
                # Actually soup modification is fine here
                for a in dt.find_all("a", class_="headerlink"):
                    a.decompose()
                signature = dt.get_text(" ", strip=True)
                
                # Name extraction (prefer human-readable descname, fallback to id)
                name = "Unknown"
                descname = dt.find(class_="descname")
                if descname:
                    name = descname.get_text(strip=True)
                elif dt.get("id"):
                    name = dt.get("id")
                
                api_items.append({
                    "api_type": "function", 
                    "name": name,
                    "signature": signature,
                    "description": current_description,
                    "parameters": []
                })
                
            except Exception as e:
                print(f"Error parsing Sphinx item: {e}", file=sys.stderr)
                continue
            
    return api_items

def extract_api_items(soup):
    # Detect doc type
    if soup.find("dl", class_="cpp"):
        return extract_sphinx_items(soup)
    elif soup.find(class_="memitem") or soup.find("dt", class_="description"):
        # Existing Doxygen logic (Standard & New NVIDIA format)
        api_items = []
        
        # Strategy 1: Look for .memitem (Older Doxygen)
        mem_items = soup.find_all(class_="memitem")
        if mem_items:
            for item in mem_items:
                try:
                    memproto = item.find(class_="memproto")
                    if not memproto: continue
                    memname = item.find(class_="memname")
                    name = memname.get_text(strip=True) if memname else "Unknown"
                    signature = memproto.get_text(" ", strip=True)
                    memdoc = item.find(class_="memdoc")
                    description = memdoc.get_text(" ", strip=True) if memdoc else ""
                    params = []
                    if memdoc:
                        param_table = memdoc.find(class_="params")
                        if param_table:
                            rows = param_table.find_all("tr")
                            for row in rows:
                                cols = row.find_all("td")
                                if len(cols) >= 2:
                                    p_name = cols[0].get_text(strip=True)
                                    p_desc = cols[1].get_text(" ", strip=True)
                                    params.append({"name": p_name, "description": p_desc})
                    api_items.append({
                        "api_type": "function",
                        "name": name,
                        "signature": signature,
                        "description": description[:300] + "..." if len(description) > 300 else description,
                        "parameters": params
                    })
                except Exception: continue
        
        # Strategy 2: Look for dt.description/dd.description (Newer NVIDIA format)
        # Note: These are often pairs.
        dt_items = soup.find_all("dt", class_="description")
        for dt in dt_items:
            try:
                # Name can be found in a child span with class 'member_name'
                # or just 'apiItemName' inside?
                # From log: <span class="member_name"><a ...>cudaArrayGetInfo</a>...</span>
                name_span = dt.find(class_="member_name")
                name = name_span.get_text(strip=True) if name_span else "Unknown"
                
                # Signature is the whole dt text (clean up newlines)
                # Remove anchor links from signature extraction if needed ??
                signature = dt.get_text(" ", strip=True)
                
                # Find corresponding dd
                dd = dt.find_next_sibling("dd", class_="description")
                if not dd:
                    continue
                
                # Description: direct text of dd or div.section inside
                # From log: <div class="section">Gets...</div>
                desc_div = dd.find("div", class_="section")
                if desc_div:
                    description = desc_div.get_text(" ", strip=True)
                else:
                    description = dd.get_text(" ", strip=True)
                
                # Parameters: dl.table-display-params
                params = []
                param_dl = dd.find("dl", class_="table-display-params")
                if param_dl:
                     # pairs of dt (name) dd (desc)
                     p_dts = param_dl.find_all("dt")
                     for p_dt in p_dts:
                         p_dd = p_dt.find_next_sibling("dd")
                         p_name = p_dt.get_text(strip=True)
                         p_desc = p_dd.get_text(" ", strip=True) if p_dd else ""
                         params.append({"name": p_name, "description": p_desc})

                api_items.append({
                    "api_type": "function",
                    "name": name,
                    "signature": signature,
                    "description": description[:300] + "..." if len(description) > 300 else description,
                    "parameters": params
                })

            except Exception as e:
                print(f"Error parsing NVIDIA item: {e}", file=sys.stderr)
                continue
                
        return api_items
    else:
        # Fallback or generic
        return []

def main():
    parser = argparse.ArgumentParser(description="Structure Extractor: Mine API data from a specific NVIDIA doc page.")
    parser.add_argument("--url", required=True, help="Target URL or local file path to extract from")
    
    args = parser.parse_args()
    
    content = fetch_content(args.url)
    if not content:
        sys.exit(1)
        
    soup = BeautifulSoup(content, 'html.parser')
    items = extract_api_items(soup)
    
    print(json.dumps(items, indent=2))

if __name__ == "__main__":
    main()
