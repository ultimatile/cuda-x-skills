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
            response = requests.get(source)
            response.raise_for_status()
            return response.content
        except Exception as e:
            print(f"Error fetching {source}: {e}", file=sys.stderr)
            return None

def extract_api_items(soup):
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
            # Skip malformed items but continue processing
            continue
            
    return api_items

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
