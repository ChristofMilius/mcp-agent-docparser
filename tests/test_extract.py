"""tests/test_extract.py — HTML → markdown extraction."""
from __future__ import annotations

from bs4 import BeautifulSoup

from mcp_agent_docparser.extract import extract_content


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


class TestExtract:
    def test_first_matching_selector_wins(self):
        html = """
        <html><body>
          <nav><a href="http://x">nav</a></nav>
          <div id="content"><h1>Hello</h1><p>World</p></div>
          <article><p>ignored</p></article>
        </body></html>
        """
        md = extract_content(_soup(html), {
            "language": "text", "selectors": ["#content", "article", "body"],
            "strip_tags": [], "section": None, "markdown_passthrough": False,
        })
        assert "Hello" in md
        assert "ignored" not in md

    def test_falls_back_to_next_selector(self):
        html = "<html><body><article><p>alpha</p></article></body></html>"
        md = extract_content(_soup(html), {
            "language": "text", "selectors": ["#content", "article", "main"],
            "strip_tags": [], "section": None, "markdown_passthrough": False,
        })
        assert "alpha" in md

    def test_no_match_returns_placeholder(self):
        md = extract_content(_soup("<html><body><p>x</p></body></html>"), {
            "language": "text", "selectors": ["#content", ".prose", "[role=main]"],
            "strip_tags": [], "section": None, "markdown_passthrough": False,
        })
        assert "No content block matched" in md

    def test_strip_tags_removes_noise(self):
        html = """
        <div id="content">
          <script>var noise = 1;</script>
          <h1>Real Title</h1>
          <footer>junk footer</footer>
        </div>
        """
        md = extract_content(_soup(html), {
            "language": "text", "selectors": ["#content"],
            "strip_tags": ["script", "footer"], "section": None,
            "markdown_passthrough": False,
        })
        assert "Real Title" in md
        assert "noise" not in md
        assert "junk footer" not in md

    def test_markdown_passthrough_uses_pre(self):
        html = "<div><pre>**already markdown**\n- item\n</pre></div>"
        md = extract_content(_soup(html), {
            "language": "python", "selectors": ["body"],
            "strip_tags": [], "section": None, "markdown_passthrough": True,
        })
        assert "**already markdown**" in md
        assert "- item" in md

    def test_code_language_emitted_for_code_blocks(self):
        html = '<div id="content"><pre><code>print("hi")</code></pre></div>'
        md = extract_content(_soup(html), {
            "language": "python", "selectors": ["#content"],
            "strip_tags": [], "section": None, "markdown_passthrough": False,
        })
        assert "python" in md

    def test_section_restriction(self):
        html = """
        <div id="content">
          <h2>Intro</h2>
          <p>first part</p>
          <h2>Installation</h2>
          <p>pip install thing</p>
          <h2>Usage</h2>
          <p>later part</p>
        </div>
        """
        md = extract_content(_soup(html), {
            "language": "bash", "selectors": ["#content"],
            "strip_tags": [], "section": "Installation", "markdown_passthrough": False,
        })
        assert "pip install thing" in md
        assert "first part" not in md
        assert "later part" not in md
