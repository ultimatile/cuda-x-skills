# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "requests",
#     "beautifulsoup4",
# ]
# ///

import re
import requests
from bs4 import BeautifulSoup, NavigableString
import sys
import argparse
import os


def fetch_content(source):
    if os.path.exists(source):
        with open(source, "r", encoding="utf-8") as f:
            return f.read()
    else:
        try:
            response = requests.get(source, timeout=30)
            response.raise_for_status()
            return response.content
        except Exception as e:
            print(f"Error fetching {source}: {e}", file=sys.stderr)
            return None


def is_noise(text):
    """Check if text is noise (punctuation only, very short, etc.)."""
    if not text:
        return True
    stripped = text.strip()
    # Single punctuation or very short meaningless tokens
    if stripped in {
        "#",
        ",",
        ".",
        "(",
        ")",
        "[",
        "]",
        ";",
        ":",
        "*",
        "&",
        "–",
        "-",
        "",
    }:
        return True
    # Only whitespace
    if not stripped:
        return True
    return False


def format_output(text):
    """Clean up the final output."""
    # Normalize whitespace (but preserve newlines for structure)
    lines = text.split("\n")
    result = []
    for line in lines:
        # Collapse multiple spaces to one
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            result.append(line)
    return "\n".join(result)


def html_to_brace_tree(element, depth=0):
    """Convert HTML element to brace-delimited text tree.

    Output format:
        text content {
          child content {
            nested content
          }
        }
    """
    # Skip unwanted tags
    skip_tags = {
        "script",
        "style",
        "nav",
        "footer",
        "header",
        "meta",
        "link",
        "noscript",
        "svg",
        "img",
    }
    if hasattr(element, "name") and element.name in skip_tags:
        return ""

    # Handle text nodes
    if isinstance(element, NavigableString):
        text = str(element).strip()
        # Skip empty or whitespace-only
        if not text or text == "\n":
            return ""
        return text

    # For inline elements, just get text content directly
    inline_tags = {"span", "a", "code", "em", "strong", "b", "i", "pre"}
    if hasattr(element, "name") and element.name in inline_tags:
        text = element.get_text(" ", strip=True)
        if is_noise(text):
            return ""
        return text

    # Get direct text content (not from children)
    direct_text = ""
    for child in element.children:
        if isinstance(child, NavigableString):
            t = str(child).strip()
            if t and t != "\n":
                direct_text += t + " "
    direct_text = direct_text.strip()

    # Process children (non-text)
    child_results = []
    for child in element.children:
        if isinstance(child, NavigableString):
            continue
        result = html_to_brace_tree(child, depth + 1)
        if result and not is_noise(result):
            child_results.append(result)

    # Build output
    if not direct_text and not child_results:
        return ""

    # Clean direct_text
    if is_noise(direct_text):
        direct_text = ""

    if not child_results:
        # Leaf node with only text
        return direct_text

    if not direct_text:
        # No direct text, just children
        if len(child_results) == 1:
            return child_results[0]
        # Join with newlines, add braces only if multiple children
        return "{\n" + "\n".join(child_results) + "\n}"

    # Has both text and children
    return direct_text + " {\n" + "\n".join(child_results) + "\n}"


def extract_section(soup, section_id):
    """Extract a specific section by ID."""
    # Try finding by id attribute
    section = soup.find(id=section_id)
    if section:
        # Go up to find the containing section/div
        parent = section.find_parent(["section", "div", "dl"])
        if parent:
            return parent
        return section

    # Try finding by text content in headings
    for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        if section_id.lower() in heading.get_text().lower():
            # Return the parent section
            parent = heading.find_parent(["section", "div"])
            if parent:
                return parent
            # Return heading and following siblings
            return heading

    return None


def clean_soup(soup):
    """Remove unwanted elements from soup."""
    # Remove script, style, nav, etc.
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()

    # Remove hidden elements
    for tag in soup.find_all(
        attrs={"style": lambda x: x and "display:none" in x.replace(" ", "")}
    ):
        tag.decompose()

    return soup


def main():
    parser = argparse.ArgumentParser(
        description="Structure Extractor: Extract doc content as brace-delimited tree."
    )
    parser.add_argument(
        "--url", required=True, help="Target URL or local file path to extract from"
    )
    parser.add_argument(
        "--section",
        help="Extract only a specific section (by ID or heading text)",
    )
    parser.add_argument(
        "--main-only",
        action="store_true",
        help="Extract only the main content area",
    )

    args = parser.parse_args()

    content = fetch_content(args.url)
    if not content:
        sys.exit(1)

    soup = BeautifulSoup(content, "html.parser")
    soup = clean_soup(soup)

    # Find main content area if requested
    if args.main_only:
        main = (
            soup.find("main")
            or soup.find(id="main-content")
            or soup.find(class_="main-content")
        )
        if main:
            soup = main

    # Extract specific section if requested
    if args.section:
        section = extract_section(soup, args.section)
        if section:
            soup = section
        else:
            print(f"Section '{args.section}' not found", file=sys.stderr)
            sys.exit(1)

    # Convert to brace tree and format
    result = html_to_brace_tree(soup)
    result = format_output(result)
    print(result)


if __name__ == "__main__":
    main()
