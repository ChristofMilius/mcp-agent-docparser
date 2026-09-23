"""tests/test_probe.py — probe layer (selector discovery, noise candidates)."""

from __future__ import annotations

from bs4 import BeautifulSoup

from mcp_agent_docparser.probe import _NOISE_SELECTORS, _analyse_probe_soup


def test_analyse_report_noise_candidates():
    html = """
    <html><body>
      <main>
        <h1>Docs</h1>
        <select><option>English</option><option>Deutsch</option></select>
        <nav><a href="https://x">crumb</a></nav>
        <footer>© 2026 Anomaly</footer>
        <div class="pagination"><a href="https://x">next</a></div>
      </main>
    </body></html>
    """
    findings = _analyse_probe_soup(BeautifulSoup(html, "html.parser"))
    assert findings["best_selector"] == "main"
    selectors = {item["selector"] for item in findings["noise_candidates"]}
    assert "footer" in selectors
    assert "select" in selectors
    assert "nav" in selectors
    assert ".pagination" in selectors
    for item in findings["noise_candidates"]:
        assert item["count"] >= 1


def test_noise_selectors_are_real_css():
    # every entry must be a usable CSS selector (bs4 will raise on junk)
    for sel in _NOISE_SELECTORS:
        BeautifulSoup(f"<main>{sel}</main>", "html.parser").select(sel)


def test_analyse_no_match_no_noise():
    findings = _analyse_probe_soup(
        BeautifulSoup("<html><body><p>x</p></body></html>", "html.parser")
    )
    assert findings["best_selector"] is None
    assert findings["noise_candidates"] == []
