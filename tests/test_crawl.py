"""tests/test_crawl.py — site crawl: discovery, robots, dedup, extraction, emit."""

from __future__ import annotations

import requests
from bs4 import BeautifulSoup

from mcp_agent_docparser.crawl import (
    _dedup,
    _norm_key,
    _origin,
    _parse_sitemap,
    crawl_site,
    discover_urls,
)

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def _sitemap_xml(urlset: bool, locs: list[str]) -> bytes:
    """Build a urlset (or sitemapindex) XML body from a list of <loc> values."""
    tag = "urlset" if urlset else "sitemapindex"
    child = "url" if urlset else "sitemap"
    items = "".join(f"<{child}><loc>{loc}</loc></{child}>" for loc in locs)
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><{tag} xmlns="{SITEMAP_NS}">{items}</{tag}>'
    ).encode()


def _fake_get(*bodies: tuple[str, bytes]):
    """Return a requests.get patch mapping url → xml body (200) or None (404)."""

    table = dict(bodies)

    def fake_get(url, headers=None, timeout=None):
        resp = requests.Response()
        body = table.get(url)
        if body is None:
            resp.status_code = 404
            resp._content = b""
        else:
            resp.status_code = 200
            resp._content = body
        resp.encoding = "utf-8"
        return resp

    return fake_get


def _patch_robots(monkeypatch, body: str | None, origin: str = "https://ex.com"):
    monkeypatch.setattr(
        "mcp_agent_docparser.crawl._fetch_robots",
        lambda url: (body, f"{origin}/robots.txt"),
    )


class TestUrlHelpers:
    def test_origin(self):
        assert _origin("https://docs.example.com/a/b") == "https://docs.example.com"
        assert _origin("http://ex.com/x") == "http://ex.com"

    def test_norm_key_strips_fragment_and_trailing_slash(self):
        assert _norm_key("https://ex.com/docs/") == "https://ex.com/docs"
        assert _norm_key("https://ex.com/docs/#anchor") == _norm_key("https://ex.com/docs")
        assert _norm_key("https://ex.com/") == "https://ex.com/"

    def test_dedup_preserves_order_and_filters_origin(self):
        urls = [
            "https://ex.com/b",
            "https://ex.com/a",
            "https://ex.com/a",
            "https://other.dev/c",
        ]
        deduped = _dedup(urls, "https://ex.com")
        assert deduped == ["https://ex.com/b", "https://ex.com/a"]


class TestParseSitemap:
    def test_urlset_returns_pages(self, monkeypatch):

        monkeypatch.setattr(
            "mcp_agent_docparser.crawl.requests.get",
            _fake_get(("https://ex.com/sitemap.xml", _sitemap_xml(True, ["https://ex.com/a"]))),
        )
        pages, nested = _parse_sitemap("https://ex.com/sitemap.xml")
        assert pages == ["https://ex.com/a"]
        assert nested == []

    def test_sitemapindex_returns_nested(self, monkeypatch):

        monkeypatch.setattr(
            "mcp_agent_docparser.crawl.requests.get",
            _fake_get(("https://ex.com/index.xml", _sitemap_xml(False, ["https://ex.com/a.xml"]))),
        )
        pages, nested = _parse_sitemap("https://ex.com/index.xml")
        assert pages == []
        assert nested == ["https://ex.com/a.xml"]

    def test_missing_sitemap_yields_nothing(self, monkeypatch):

        monkeypatch.setattr("mcp_agent_docparser.crawl.requests.get", _fake_get())
        assert _parse_sitemap("https://ex.com/nope.xml") == ([], [])


class TestDiscovery:
    def test_sitemap_walk_applies_robots_prefix_and_dedup(self, monkeypatch):
        robots_body = (
            "User-agent: *\n"
            "Disallow: /private/\n"
            "Crawl-delay: 1.5\n"
            "Sitemap: https://ex.com/index.xml\n"
        )
        _patch_robots(monkeypatch, robots_body)

        monkeypatch.setattr(
            "mcp_agent_docparser.crawl.requests.get",
            _fake_get(
                ("https://ex.com/index.xml", _sitemap_xml(False, ["https://ex.com/a.xml"])),
                (
                    "https://ex.com/a.xml",
                    _sitemap_xml(
                        True,
                        [
                            "https://ex.com/public/a",
                            "https://ex.com/private/secret",
                            "https://elsewhere.dev/x",
                            "https://ex.com/public/a",
                            "https://ex.com/private/x",
                        ],
                    ),
                ),
            ),
        )

        result = discover_urls("https://ex.com/docs/", max_pages=100)
        assert result["source"] == "sitemap"
        assert result["urls"] == ["https://ex.com/public/a"]
        assert result["robots_denied"] == 2  # both /private/ URLs
        assert result["crawl_delay"] == 1.5

    def test_xml_seed_parsed_directly(self, monkeypatch):
        _patch_robots(monkeypatch, None)

        monkeypatch.setattr(
            "mcp_agent_docparser.crawl.requests.get",
            _fake_get(
                (
                    "https://ex.com/sitemap.xml",
                    _sitemap_xml(True, ["https://ex.com/b", "https://ex.com/a"]),
                )
            ),
        )
        result = discover_urls("https://ex.com/sitemap.xml")
        assert result["source"] == "seed"
        assert result["urls"] == ["https://ex.com/a", "https://ex.com/b"]

    def test_link_walk_fallback_when_sitemap_empty(self, monkeypatch):
        _patch_robots(monkeypatch, None)

        monkeypatch.setattr(
            "mcp_agent_docparser.crawl.requests.get",
            _fake_get(),
        )
        page_html = (
            "<html><body>"
            '<a href="/docs/one">one</a>'
            '<a href="https://ex.com/docs/two">two</a>'
            '<a href="https://other.dev/x">external</a>'
            '<a href="https://ex.com/docs/one">dup</a>'
            "</body></html>"
        )
        soup = BeautifulSoup(page_html, "html.parser")
        monkeypatch.setattr("mcp_agent_docparser.crawl.fetch_static", lambda url: soup)

        result = discover_urls("https://ex.com/docs/", max_pages=10)
        assert result["source"] == "link_walk"
        assert result["urls"] == [
            "https://ex.com/docs/",
            "https://ex.com/docs/one",
            "https://ex.com/docs/two",
        ]

    def test_max_pages_caps_sitemap_result(self, monkeypatch):
        _patch_robots(monkeypatch, None)

        many = [f"https://ex.com/p{i:03d}" for i in range(50)]
        monkeypatch.setattr(
            "mcp_agent_docparser.crawl.requests.get",
            _fake_get(("https://ex.com/sitemap.xml", _sitemap_xml(True, many))),
        )
        result = discover_urls("https://ex.com/docs/", max_pages=10)
        # URLs are sorted lexicographically before capping, so only the count is stable.
        assert len(result["urls"]) == 10
        assert set(result["urls"]) <= set(many)


class TestCrawlSite:
    def test_dry_run_writes_nothing(self, tmp_path, sample_receipt, monkeypatch):
        _patch_robots(monkeypatch, None)

        monkeypatch.setattr(
            "mcp_agent_docparser.crawl.requests.get",
            _fake_get(("https://ex.com/sitemap.xml", _sitemap_xml(True, ["https://ex.com/a"]))),
        )

        def boom(*a, **kw):
            raise AssertionError("dry run must not fetch pages")

        monkeypatch.setattr("mcp_agent_docparser.crawl.fetch", boom)
        monkeypatch.setattr("mcp_agent_docparser.crawl.fetch_static", boom)

        result = crawl_site(
            sample_receipt, "https://ex.com/docs/", output_dir=tmp_path, dry_run=True
        )
        assert result["status"] == "dry_run"
        assert result["urls"] == ["https://ex.com/a"]
        assert list(tmp_path.glob("*.md")) == []

    def test_full_crawl_emits_combined_file(self, tmp_path, sample_receipt, monkeypatch):
        _patch_robots(monkeypatch, None)

        monkeypatch.setattr(
            "mcp_agent_docparser.crawl.requests.get",
            _fake_get(
                (
                    "https://ex.com/sitemap.xml",
                    _sitemap_xml(True, ["https://ex.com/z", "https://ex.com/a"]),
                )
            ),
        )
        soup = BeautifulSoup(
            "<div><article><h1>Docs</h1><p>page body</p></article></div>",
            "html.parser",
        )
        monkeypatch.setattr(
            "mcp_agent_docparser.crawl.fetch",
            lambda url, js_render=False, js_settle_ms=None: soup,
        )

        result = crawl_site(sample_receipt, "https://ex.com/docs/", output_dir=tmp_path)
        assert result["status"] == "ok"
        assert result["pages_fetched"] == 2
        assert result["sections"][0]["url"] == "https://ex.com/a"  # sorted by url
        assert result["total_chars"] > 0
        assert "page body" in result["markdown"]

        written = list(tmp_path.glob("*.md"))
        assert len(written) == 1
        assert written[0].name == result["output_filename"]
        assert "SOURCE" in written[0].read_text(encoding="utf-8")

    def test_fetch_failures_are_skipped_and_reported(self, tmp_path, sample_receipt, monkeypatch):
        _patch_robots(monkeypatch, None)

        monkeypatch.setattr(
            "mcp_agent_docparser.crawl.requests.get",
            _fake_get(
                (
                    "https://ex.com/sitemap.xml",
                    _sitemap_xml(True, ["https://ex.com/a", "https://ex.com/b"]),
                )
            ),
        )
        soup = BeautifulSoup("<article><p>ok</p></article>", "html.parser")
        monkeypatch.setattr(
            "mcp_agent_docparser.crawl.fetch",
            lambda url, js_render=False, js_settle_ms=None: soup if url.endswith("a") else None,
        )

        result = crawl_site(sample_receipt, "https://ex.com/docs/", output_dir=tmp_path)
        assert result["status"] == "ok"
        assert result["pages_fetched"] == 1
        assert result["pages_failed"] == 1

    def test_all_fetches_fail_reports_error(self, tmp_path, sample_receipt, monkeypatch):
        _patch_robots(monkeypatch, None)

        monkeypatch.setattr(
            "mcp_agent_docparser.crawl.requests.get",
            _fake_get(("https://ex.com/sitemap.xml", _sitemap_xml(True, ["https://ex.com/a"]))),
        )
        monkeypatch.setattr(
            "mcp_agent_docparser.crawl.fetch",
            lambda url, js_render=False, js_settle_ms=None: None,
        )

        result = crawl_site(sample_receipt, "https://ex.com/docs/", output_dir=tmp_path)
        assert result["status"] == "error"

    def test_js_render_template_caps_workers_to_one(self, tmp_path, sample_receipt, monkeypatch):
        """js_render templates serialize to 1 worker so the thread-bound browser is shared."""
        _patch_robots(monkeypatch, None)
        monkeypatch.setattr(
            "mcp_agent_docparser.crawl.requests.get",
            _fake_get(("https://ex.com/sitemap.xml", _sitemap_xml(True, ["https://ex.com/a"]))),
        )
        soup = BeautifulSoup("<article><p>js rendered</p></article>", "html.parser")
        monkeypatch.setattr(
            "mcp_agent_docparser.crawl.fetch",
            lambda url, js_render=False, js_settle_ms=None: soup,
        )

        from concurrent.futures import Future

        seen_workers: dict[str, int] = {}

        class _SyncPool:
            def __init__(self, max_workers):
                seen_workers["max_workers"] = max_workers

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def submit(self, fn, *args, **kwargs):
                fut = Future()
                try:
                    fut.set_result(fn(*args, **kwargs))
                except BaseException as exc:  # noqa: BLE001
                    fut.set_exception(exc)
                return fut

        monkeypatch.setattr("mcp_agent_docparser.crawl.ThreadPoolExecutor", _SyncPool)

        js_template = dict(sample_receipt, js_render=True)
        result = crawl_site(js_template, "https://ex.com/docs/", output_dir=tmp_path, workers=8)
        assert result["status"] == "ok"
        assert seen_workers["max_workers"] == 1
