"""Tests for structure_extractor.py — HTML parsing and tree conversion."""

import pytest
from bs4 import BeautifulSoup

from structure_extractor import (
    clean_soup,
    extract_section,
    format_output,
    html_to_brace_tree,
    is_noise,
)


def _soup(html):
    return BeautifulSoup(html, "html.parser")


# -- is_noise ----------------------------------------------------------------

class TestIsNoise:
    @pytest.mark.parametrize("text", [None, "", "   ", "\t"])
    def test_empty_or_whitespace(self, text):
        assert is_noise(text) is True

    @pytest.mark.parametrize("text", ["#", ",", ".", "(", ")", "[", "]", ";", ":", "*", "&", "–", "-"])
    def test_single_punctuation(self, text):
        assert is_noise(text) is True

    @pytest.mark.parametrize("text", ["hello", "cudaMemcpy", "int x", "a"])
    def test_real_content(self, text):
        assert is_noise(text) is False


# -- format_output -----------------------------------------------------------

class TestFormatOutput:
    def test_collapses_spaces(self):
        assert format_output("hello   world") == "hello world"

    def test_collapses_tabs(self):
        assert format_output("hello\t\tworld") == "hello world"

    def test_strips_lines(self):
        assert format_output("  hello  \n  world  ") == "hello\nworld"

    def test_removes_blank_lines(self):
        assert format_output("hello\n\n\nworld") == "hello\nworld"

    def test_empty_input(self):
        assert format_output("") == ""


# -- html_to_brace_tree ------------------------------------------------------

class TestHtmlToBraceTree:
    def test_plain_text(self):
        result = html_to_brace_tree(_soup("<p>Hello world</p>"))
        assert "Hello world" in result

    def test_skips_script(self):
        result = html_to_brace_tree(_soup("<div><script>var x=1;</script><p>content</p></div>"))
        assert "var x" not in result
        assert "content" in result

    def test_skips_style(self):
        result = html_to_brace_tree(_soup("<div><style>.x{}</style><p>content</p></div>"))
        assert ".x{}" not in result
        assert "content" in result

    def test_skips_nav_footer_header(self):
        html = "<div><nav>nav text</nav><footer>foot</footer><header>head</header><p>content</p></div>"
        result = html_to_brace_tree(_soup(html))
        assert "nav text" not in result
        assert "foot" not in result
        assert "head" not in result
        assert "content" in result

    def test_inline_elements(self):
        result = html_to_brace_tree(_soup("<p><code>cudaMalloc</code></p>"))
        assert "cudaMalloc" in result

    def test_nested_structure(self):
        html = "<div><h2>Title</h2><p>Body text</p></div>"
        result = html_to_brace_tree(_soup(html))
        assert "Title" in result
        assert "Body text" in result

    def test_noise_filtered(self):
        html = "<div><span>#</span><p>real content</p></div>"
        result = html_to_brace_tree(_soup(html))
        assert "real content" in result

    def test_empty_element(self):
        result = html_to_brace_tree(_soup("<div></div>"))
        assert result == ""

    def test_brace_wrapping_for_children(self):
        html = "<div><p>first</p><p>second</p></div>"
        result = html_to_brace_tree(_soup(html))
        assert "{" in result
        assert "first" in result
        assert "second" in result


# -- extract_section ---------------------------------------------------------

class TestExtractSection:
    def test_by_id(self):
        html = '<div><section id="api-ref"><h2>API Reference</h2><p>Details</p></section></div>'
        soup = _soup(html)
        section = extract_section(soup, "api-ref")
        assert section is not None
        assert "Details" in section.get_text()

    def test_by_heading_text(self):
        html = "<div><section><h2>Memory Management</h2><p>Details</p></section></div>"
        soup = _soup(html)
        section = extract_section(soup, "memory management")
        assert section is not None
        assert "Details" in section.get_text()

    def test_heading_case_insensitive(self):
        html = "<div><section><h3>CUDA Runtime</h3><p>Info</p></section></div>"
        soup = _soup(html)
        assert extract_section(soup, "cuda runtime") is not None

    def test_not_found(self):
        html = "<div><p>Nothing here</p></div>"
        soup = _soup(html)
        assert extract_section(soup, "nonexistent") is None


# -- clean_soup --------------------------------------------------------------

class TestCleanSoup:
    def test_removes_script_and_style(self):
        html = "<div><script>x</script><style>.y{}</style><p>content</p></div>"
        soup = clean_soup(_soup(html))
        assert soup.find("script") is None
        assert soup.find("style") is None
        assert "content" in soup.get_text()

    def test_removes_nav_footer_header(self):
        html = "<div><nav>n</nav><footer>f</footer><header>h</header><p>ok</p></div>"
        soup = clean_soup(_soup(html))
        assert soup.find("nav") is None
        assert soup.find("footer") is None
        assert soup.find("header") is None

    def test_removes_hidden_elements(self):
        html = '<div><p style="display:none">hidden</p><p>visible</p></div>'
        soup = clean_soup(_soup(html))
        text = soup.get_text()
        assert "hidden" not in text
        assert "visible" in text

    def test_preserves_content(self):
        html = "<div><p>keep this</p></div>"
        soup = clean_soup(_soup(html))
        assert "keep this" in soup.get_text()
