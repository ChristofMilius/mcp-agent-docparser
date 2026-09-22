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

    def test_strip_tags_none_means_noop(self):
        # receipt_add stores strip_tags=None when omitted; must not crash
        html = '<div id="content"><script>s</script><p>keep me</p></div>'
        md = extract_content(_soup(html), {
            "language": "text", "selectors": ["#content"],
            "strip_tags": None, "section": None, "markdown_passthrough": False,
        })
        assert "keep me" in md

    def test_markdown_passthrough_uses_pre(self):
        html = "<div><pre>**already markdown**\n- item\n</pre></div>"
        md = extract_content(_soup(html), {
            "language": "python", "selectors": ["body"],
            "strip_tags": [], "section": None, "markdown_passthrough": True,
        })
        assert "**already markdown**" in md
        assert "- item" in md

    def test_passthrough_cleans_crlf_hash_tokens(self):
        html = (
            "<div><pre>Use a skill [#use-a-skill]\r\n"
            "Skills give Bionic reusable guidance.\r\n"
            "Create a skill [#create-a-skill]\r\n"
            "Ask Bionic.\r\n"
            "## Tips [#tips]\r\n"
            "Short advice.\r\n</pre></div>"
        )
        md = extract_content(_soup(html), {
            "language": "english", "selectors": ["body"],
            "strip_tags": [], "section": None, "markdown_passthrough": True,
        })
        assert "Use a skill" in md
        assert "[#use-a-skill]" not in md
        assert "## Tips" in md
        assert "[#tips]" not in md
        assert "\r" not in md

    def test_passthrough_keeps_unrelated_bracketed_tokens(self):
        # a trailing [?] is not an anchor slug, and a hash link in prose stays
        html = "<div><pre>Docs [#docs] and [other]\n[Keep me](#anchor)\n</pre></div>"
        md = extract_content(_soup(html), {
            "language": "english", "selectors": ["body"],
            "strip_tags": [], "section": None, "markdown_passthrough": True,
        })
        assert "Docs and [other]" in md or "Docs" in md
        assert "[Keep me](#anchor)" in md

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


class TestCodeFenceLanguage:
    def test_human_language_does_not_taint_fence(self):
        # "english" is a human language, not a code fence tag
        html = '<div id="content"><pre><code>{"a": 1}\n{"b": 2}\n</code></pre></div>'
        md = extract_content(_soup(html), {
            "language": "english", "selectors": ["#content"],
            "strip_tags": [], "section": None, "markdown_passthrough": False,
        })
        assert "```english" not in md
        assert "```\n" in md
        assert "\"a\": 1" in md

    def test_language_that_looks_like_code_used_for_fence(self):
        html = '<div id="content"><pre><code>print("hi")</code></pre></div>'
        md = extract_content(_soup(html), {
            "language": "python", "selectors": ["#content"],
            "strip_tags": [], "section": None, "markdown_passthrough": False,
        })
        assert "```python" in md

    def test_data_language_hint_wins_over_fallback(self):
        html = '<div id="content"><pre data-language="json"><code>x</code></pre></div>'
        md = extract_content(_soup(html), {
            "language": "english", "selectors": ["#content"],
            "strip_tags": [], "section": None, "markdown_passthrough": False,
        })
        assert "```json" in md

    def test_language_class_hint_wins_over_fallback(self):
        html = '<div id="content"><pre><code class="language-typescript">x</code></pre></div>'
        md = extract_content(_soup(html), {
            "language": "english", "selectors": ["#content"],
            "strip_tags": [], "section": None, "markdown_passthrough": False,
        })
        assert "```typescript" in md

    def test_explicit_code_language_overrides_page(self):
        html = '<div id="content"><pre data-language="json"><code>x</code></pre></div>'
        md = extract_content(_soup(html), {
            "language": "english", "code_language": "yaml",
            "selectors": ["#content"],
            "strip_tags": [], "section": None, "markdown_passthrough": False,
        })
        assert "```yaml" in md
        assert "```json" not in md


class TestCodeBlockCollapse:
    def test_ec_line_blocks_collapse_to_single_fence(self):
        # expressive-code wraps every line in its own div — must not blank-line-separate
        html = (
            '<div id="content"><pre data-language="json"><code>'
            '<div class="ec-line"><div class="code"><span>{</span></div></div>'
            '<div class="ec-line"><div class="code"><span>"a": 1</span></div></div>'
            '<div class="ec-line"><div class="code"><span>}</span></div></div>'
            "</code></pre></div>"
        )
        md = extract_content(_soup(html), {
            "language": "english", "selectors": ["#content"],
            "strip_tags": [], "section": None, "markdown_passthrough": False,
        })
        assert "```json\n{\n\"a\": 1\n}\n```" in md

    def test_plain_pre_untouched(self):
        html = '<div id="content"><pre><code>a\nb\nc\n</code></pre></div>'
        md = extract_content(_soup(html), {
            "language": "english", "selectors": ["#content"],
            "strip_tags": [], "section": None, "markdown_passthrough": False,
        })
        assert "```\na\nb\nc\n```" in md


class TestHeadingAnchorStrip:
    def test_sphinx_pilcrow_anchor_removed(self):
        html = '<div id="content"><h2>Make a Request<a href="#make-a-request" title="Link to this heading">¶</a></h2></div>'
        md = extract_content(_soup(html), {
            "language": "text", "selectors": ["#content"],
            "strip_tags": [], "section": None, "markdown_passthrough": False,
        })
        assert "## Make a Request" in md
        assert "¶" not in md
        assert "Link to this heading" not in md

    def test_docusaurus_zwsp_heading_anchor_removed(self):
        # Docusaurus marks heading anchors with a zero-width space (U+200B).
        html = '<div id="content"><h2>Using Skills<a href="#using-skills" title="Direct link to Using Skills">\u200b</a></h2></div>'
        md = extract_content(_soup(html), {
            "language": "text", "selectors": ["#content"],
            "strip_tags": [], "section": None, "markdown_passthrough": False,
        })
        assert "## Using Skills" in md
        assert "\u200b" not in md
        assert "#using-skills" not in md

    def test_self_linking_heading_unwrapped(self):
        html = '<div id="content"><h2><a href="#use-a-plugin">Use a plugin</a></h2><p>body</p></div>'
        md = extract_content(_soup(html), {
            "language": "text", "selectors": ["#content"],
            "strip_tags": [], "section": None, "markdown_passthrough": False,
        })
        assert "## Use a plugin" in md
        assert "#use-a-plugin" not in md
        assert "body" in md
