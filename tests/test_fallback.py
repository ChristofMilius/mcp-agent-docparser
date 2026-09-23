"""tests/test_fallback.py — score-based content fallback (selectors all miss)."""
from __future__ import annotations

from bs4 import BeautifulSoup

from mcp_agent_docparser.extract import css_hint, extract_content, select_best_content
from mcp_agent_docparser.probe import _analyse_probe_soup


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


#: A receipt whose selectors match nothing on purpose — forces the fallback.
MISSING_SELECTORS = {
    "language": "text",
    "selectors": ["#content", ".prose", "[role='main']"],
    "strip_tags": [],
    "section": None,
    "markdown_passthrough": False,
}


class TestSelectBestContent:
    def test_picks_semantic_tag_over_small_divs(self):
        soup = _soup(
            "<html><body>"
            "<div><p>tiny</p></div>"
            "<article><h1>Docs</h1><p>" + "x" * 400 + "</p></article>"
            "</body></html>"
        )
        best = select_best_content(soup)
        assert best is not None
        assert best.name == "article"

    def test_rejects_pure_link_box(self):
        links = "".join(f'<a href="https://e.com/{i}">entry number {i}</a>' for i in range(30))
        soup = _soup(f"<html><body><div class='nav'>{links}</div></body></html>")
        # Everyone is all-links with no prose — score ≤ 0, nothing qualifies.
        assert select_best_content(soup) is None

    def test_no_candidate_on_small_page(self):
        assert select_best_content(_soup("<html><body><p>x</p></body></html>")) is None

    def test_css_hint(self):
        soup = _soup("<div id='c' class='x'>hi</div><section class='y'>text</section><p>x</p>")
        assert css_hint(soup.find(id="c")) == "#c"
        assert css_hint(soup.find("section")) == "section.y"
        assert css_hint(soup.find("p")) == "p"


class TestFallbackInExtract:
    def test_replaces_placeholder_with_recovered_content(self):
        html = """
        <html><body>
          <nav><a href="https://x">Jonathan</a><a href="https://y">Martha</a></nav>
          <div class="article-core">
            <h1>Real Docs</h1>
            <p>""" + "substantive prose " * 60 + """</p>
            <pre><code>pip install thing</code></pre>
          </div>
        </body></html>
        """
        md = extract_content(_soup(html), dict(MISSING_SELECTORS))
        assert "No content block matched" not in md
        assert "Real Docs" in md
        assert "substantive prose" in md
        assert "pip install thing" in md

    def test_noise_block_loses_to_clean_text(self):
        # Box A: thousands of chars but almost all anchor text. Box B: plain prose.
        links = "".join(f'<a href="https://e.com/{i}">{i * "link "}</a>' for i in range(40))
        html = f"""
        <html><body>
          <div class="index">{links}</div>
          <div class="prose-body"><p>{"real documentation content " * 80}</p></div>
        </body></html>
        """
        md = extract_content(_soup(html), dict(MISSING_SELECTORS))
        assert "real documentation content" in md
        assert "No content block matched" not in md

    def test_still_placeholder_when_everything_is_noise(self):
        links = "".join(f'<a href="https://e.com/{i}">link {i}</a>' for i in range(20))
        html = f"<html><body><aside>{links}</aside></body></html>"
        md = extract_content(_soup(html), dict(MISSING_SELECTORS))
        assert "No content block matched" in md

    def test_tiny_page_keeps_placeholder(self):
        md = extract_content(_soup("<html><body><p>tiny</p></body></html>"), dict(MISSING_SELECTORS))
        assert "No content block matched" in md


class TestProbeScoredHint:
    def test_probe_reports_scored_selector_when_none_match(self):
        html = (
            "<html><body><div class='engine-body'><h1>T</h1>"
            "<p>" + "prose " * 120 + "</p></div></body></html>"
        )
        findings = _analyse_probe_soup(BeautifulSoup(html, "html.parser"))
        assert findings["best_selector"] is None
        assert findings["scored_selector"] == "div.engine-body"

    def test_probe_scored_selector_none_on_empty_page(self):
        findings = _analyse_probe_soup(BeautifulSoup("<html><body><p>x</p></body></html>", "html.parser"))
        assert findings["best_selector"] is None
        assert findings["scored_selector"] is None

    def test_probe_scored_selector_unset_when_selector_hits(self):
        html = '<main><h1>Docs</h1><p>body</p></main>'
        findings = _analyse_probe_soup(BeautifulSoup(html, "html.parser"))
        assert findings["best_selector"] == "main"
        assert findings["scored_selector"] is None
