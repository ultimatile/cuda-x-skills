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
                
                # Name extraction (best effort from signature or id)
                name = "Unknown"
                if dt.get("id"):
                    name = dt.get("id")
                else:
                    # Try to find the bold descname
                    descname = dt.find(class_="descname")
                    if descname:
                        name = descname.get_text(strip=True)
                
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
    elif soup.find(class_="memitem"):
        # Existing Doxygen logic
        api_items = []
        # NVIDIA docs often wrap API items in .memitem
        mem_items = soup.find_all(class_="memitem")
        
        for item in mem_items:
            try:
                # Extract Name and Signature
                memproto = item.find(class_="memproto")
                if not memproto:
                    continue
                    
                memname = item.find(class_="memname")
                name = memname.get_text(strip=True) if memname else "Unknown"
                
                # Signature extraction
                signature = memproto.get_text(" ", strip=True)
                
                # Extract Description
                memdoc = item.find(class_="memdoc")
                description = memdoc.get_text(" ", strip=True) if memdoc else ""
                
                # Extract Parameters
                params = []
                if memdoc:
                    param_table = memdoc.find(class_="params")
                    if param_table:
                        rows = param_table.find_all("tr")
                        for row in rows:
                            cols = row.find_all("td")
                            if len(cols) >= 2:
                                param_name = cols[0].get_text(strip=True)
                                param_desc = cols[1].get_text(" ", strip=True)
                                params.append({"name": param_name, "description": param_desc})

                api_items.append({
                    "api_type": "function", # Could be detected dynamically
                    "name": name,
                    "signature": signature,
                    "description": description[:300] + "..." if len(description) > 300 else description,
                    "parameters": params
                })
                
            except Exception as e:
                print(f"Error parsing Doxygen item: {e}", file=sys.stderr)
                # Skip malformed items but continue processing
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
