"""tests/test_cache.py — fetch-level HTML cache: keying, TTL, clear, integration."""

from __future__ import annotations

import time

import pytest
from bs4 import BeautifulSoup

from mcp_agent_docparser import cache
from mcp_agent_docparser import fetch as fetch_mod


@pytest.fixture
def cache_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCPARSER_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("DOCPARSER_CACHE_TTL_SECONDS", raising=False)
    monkeypatch.delenv("DOCPARSER_CACHE_DISABLED", raising=False)
    return tmp_path / "cache"


class TestKeying:
    def test_static_and_js_render_never_share_a_key(self):
        url = "https://docs.example.com/overview"
        assert cache._key(url, False) != cache._key(url, True)

    def test_key_is_stable_and_url_sensitive(self):
        assert cache._key("https://a.dev/x", False) == cache._key("https://a.dev/x", False)
        assert cache._key("https://a.dev/x", False) != cache._key("https://a.dev/y", False)


class TestPutGet:
    def test_roundtrip(self, cache_env):
        html = "<article><h1>Docs</h1><p>body</p></article>"
        cache.cache_put("https://a.dev/x", False, html)
        got = cache.cache_get("https://a.dev/x", False)
        assert got == html

    def test_miss_returns_none(self, cache_env):
        assert cache.cache_get("https://a.dev/never-seen", False) is None

    def test_variant_insulated(self, cache_env):
        cache.cache_put("https://a.dev/x", True, "<div>js</div>")
        assert cache.cache_get("https://a.dev/x", False) is None
        assert cache.cache_get("https://a.dev/x", True) == "<div>js</div>"

    def test_empty_html_is_not_cached(self, cache_env):
        assert cache.cache_put("https://a.dev/x", False, "") is None
        assert cache.cache_get("https://a.dev/x", False) is None

    def test_entry_metadata_roundtrips(self, cache_env):
        cache.cache_put("https://a.dev/x", True, "<div>js</div>")
        (path,) = cache_env.iterdir()  # exactly one entry written
        import json

        entry = json.loads(path.read_text(encoding="utf-8"))
        assert entry["url"] == "https://a.dev/x"
        assert entry["variant"] == "js"
        assert entry["html"] == "<div>js</div>"
        assert entry["fetched_at"] > 0


class TestTTL:
    def test_expired_entry_is_not_served_and_removed(self, cache_env, monkeypatch):
        monkeypatch.setenv("DOCPARSER_CACHE_TTL_SECONDS", "10")
        cache.cache_put("https://a.dev/x", False, "<p>body</p>")
        (path,) = cache_env.iterdir()

        # Backdate the entry past any TTL.
        import json

        entry = json.loads(path.read_text(encoding="utf-8"))
        entry["fetched_at"] = time.time() - 60
        path.write_text(json.dumps(entry), encoding="utf-8")

        assert cache.cache_get("https://a.dev/x", False) is None
        assert not path.exists()

    def test_fresh_entry_served_within_ttl(self, cache_env, monkeypatch):
        monkeypatch.setenv("DOCPARSER_CACHE_TTL_SECONDS", "60")
        cache.cache_put("https://a.dev/x", False, "<p>body</p>")
        assert cache.cache_get("https://a.dev/x", False) == "<p>body</p>"

    @pytest.mark.parametrize("raw", ["0", "junk", "-5"])
    def test_ttl_junk_or_zero_means_never_expire(self, cache_env, monkeypatch, raw):
        cache.cache_put("https://a.dev/x", False, "<p>body</p>")
        (path,) = cache_env.iterdir()

        import json

        entry = json.loads(path.read_text(encoding="utf-8"))
        entry["fetched_at"] = time.time() - 3600  # an hour old
        path.write_text(json.dumps(entry), encoding="utf-8")

        monkeypatch.setenv("DOCPARSER_CACHE_TTL_SECONDS", raw)
        assert cache.cache_get("https://a.dev/x", False) == "<p>body</p>"


class TestDisabled:
    def test_disabled_get_is_miss(self, cache_env, monkeypatch):
        cache.cache_put("https://a.dev/x", False, "<p>body</p>")
        monkeypatch.setenv("DOCPARSER_CACHE_DISABLED", "1")
        assert cache.cache_get("https://a.dev/x", False) is None

    def test_disabled_put_writes_nothing(self, cache_env, monkeypatch):
        monkeypatch.setenv("DOCPARSER_CACHE_DISABLED", "true")
        assert cache.cache_put("https://a.dev/x", False, "<p>body</p>") is None
        # The dir is never even created while disabled.
        assert not cache_env.exists()


class TestClear:
    def test_clear_removes_all_and_reports_count(self, cache_env):
        cache.cache_put("https://a.dev/x", False, "<p>1</p>")
        cache.cache_put("https://a.dev/y", True, "<div>2</div>")
        cache.cache_put("https://a.dev/z", False, "<p>3</p>")
        assert cache.cache_clear() == 3
        assert list(cache_env.iterdir()) == []

    def test_clear_missing_dir_is_zero(self, cache_env):
        assert cache.cache_clear() == 0


class TestFetchIntegration:
    def test_second_fetch_served_from_cache_no_network(self, cache_env, monkeypatch):
        calls = []

        def fake_fetch_static(url):
            calls.append(url)
            return BeautifulSoup(
                "<article><h1>Docs</h1><p>cached body</p></article>", "html.parser"
            )

        monkeypatch.setattr(fetch_mod, "fetch_static", fake_fetch_static)
        monkeypatch.setenv("DOCPARSER_CACHE_DIR", str(cache_env))

        first = fetch_mod.fetch("https://a.dev/x", js_render=False)
        second = fetch_mod.fetch("https://a.dev/x", js_render=False)

        assert calls == ["https://a.dev/x"]  # network hit only once
        assert first.get_text() == second.get_text()
        assert second.get_text() == "Docscached body"

    def test_js_and_static_fetches_do_not_share_cache(self, cache_env, monkeypatch):
        was_js = []

        def fake_fetch_static(url):
            return BeautifulSoup("<article>static</article>", "html.parser")

        def fake_fetch_js(url, js_settle_ms=None):
            was_js.append(url)
            return BeautifulSoup("<div><pre>js blob</pre></div>", "html.parser")

        monkeypatch.setattr(fetch_mod, "fetch_static", fake_fetch_static)
        monkeypatch.setattr(fetch_mod, "fetch_js", fake_fetch_js)

        fetch_mod.fetch("https://a.dev/x", js_render=False)
        fetch_mod.fetch("https://a.dev/x", js_render=True)
        fetch_mod.fetch("https://a.dev/x", js_render=False)  # static cache hit
        fetch_mod.fetch("https://a.dev/x", js_render=True)  # js cache hit

        assert was_js == ["https://a.dev/x"]  # js fetched exactly once
        assert len(list(cache_env.iterdir())) == 2  # one static + one js entry
