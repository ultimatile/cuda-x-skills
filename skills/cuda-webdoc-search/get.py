"""Extract documentation content as brace-delimited text tree."""

import os
import re
import sys
from typing import Annotated, Optional

import requests
import typer
from bs4 import BeautifulSoup, NavigableString


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
    if not stripped:
        return True
    return False


def format_output(text):
    """Clean up the final output."""
    lines = text.split("\n")
    result = []
    for line in lines:
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            result.append(line)
    return "\n".join(result)


def html_to_brace_tree(element, depth=0):
    """Convert HTML element to brace-delimited text tree."""
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

    if isinstance(element, NavigableString):
        text = str(element).strip()
        if not text or text == "\n":
            return ""
        return text

    inline_tags = {"span", "a", "code", "em", "strong", "b", "i", "pre"}
    if hasattr(element, "name") and element.name in inline_tags:
        text = element.get_text(" ", strip=True)
        if is_noise(text):
            return ""
        return text

    direct_text = ""
    for child in element.children:
        if isinstance(child, NavigableString):
            t = str(child).strip()
            if t and t != "\n":
                direct_text += t + " "
    direct_text = direct_text.strip()

    child_results = []
    for child in element.children:
        if isinstance(child, NavigableString):
            continue
        result = html_to_brace_tree(child, depth + 1)
        if result and not is_noise(result):
            child_results.append(result)

    if not direct_text and not child_results:
        return ""

    if is_noise(direct_text):
        direct_text = ""

    if not child_results:
        return direct_text

    if not direct_text:
        if len(child_results) == 1:
            return child_results[0]
        return "{\n" + "\n".join(child_results) + "\n}"

    return direct_text + " {\n" + "\n".join(child_results) + "\n}"


def extract_section(soup, section_id):
    """Extract a specific section by ID."""
    section = soup.find(id=section_id)
    if section:
        parent = section.find_parent(["section", "div", "dl"])
        if parent:
            return parent
        return section

    for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        if section_id.lower() in heading.get_text().lower():
            parent = heading.find_parent(["section", "div"])
            if parent:
                return parent
            return heading

    return None


def clean_soup(soup):
    """Remove unwanted elements from soup."""
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()

    for tag in soup.find_all(
        attrs={"style": lambda x: x and "display:none" in x.replace(" ", "")}
    ):
        tag.decompose()

    return soup


def get_doc(
    url: Annotated[str, typer.Argument(help="Target URL or local file path")],
    section: Annotated[
        Optional[str],
        typer.Option(help="Extract only a specific section (by ID or heading text)"),
    ] = None,
    main_only: Annotated[
        bool,
        typer.Option("--main-only", help="Extract only the main content area"),
    ] = False,
):
    """Extract doc content as brace-delimited tree."""
    content = fetch_content(url)
    if not content:
        raise typer.Exit(1)

    soup = BeautifulSoup(content, "html.parser")
    soup = clean_soup(soup)

    if main_only:
        main = (
            soup.find("main")
            or soup.find(id="main-content")
            or soup.find(class_="main-content")
        )
        if main:
            soup = main

    if section:
        sec = extract_section(soup, section)
        if sec:
            soup = sec
        else:
            print(f"Section '{section}' not found", file=sys.stderr)
            raise typer.Exit(1)

    result = html_to_brace_tree(soup)
    result = format_output(result)
    print(result)
