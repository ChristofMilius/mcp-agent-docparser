---
name: docparser-page-fixes
description: Fix noisy or malformed pages fetched by the docparser MCP SDK-doc extractor. Use when an extracted page has wrong code-fence language, blank lines between code lines, leaked navigation/footer noise, heading-anchor junk like "[¶](#…)" or trailing "[#slug]", or CRLF/spacing weirdness in the markdown. Covers the reproduce → isolate → fix → test → restart loop and real symptom/cause/fix cases from the repo's history.
---

# Docparser page extraction fixes

When a page fetched through the docparser MCP tools comes back dirty, this is
the teaching on how to improve the tool itself (or the receipt) so the fix
sticks for everyone.

## Orientation (files)

| Path | Role |
|---|---|
| `src/mcp_agent_docparser/fetch.py` | fetch layer: `fetch_static` (requests) vs `fetch_js` (Playwright, clicks "Copy as Markdown" → clipboard → wraps in `<pre>`) |
| `src/mcp_agent_docparser/extract.py` | extract layer: selector walk, strip_tags, pre-collapse, code language, noise regexes. **Most fixes land here.** |
| `src/mcp_agent_docparser/receipts.py` | receipt schema + validation (auto `section`, `code_language` fields) |
| `src/mcp_agent_docparser/tool_surface/` | MCP tool wrappers (parse/probe/receipts) |
| `receipts.json` | per-site profiles (selectors, strip_tags, js_render, markdown_passthrough, code_language) — never put site specifics in Python |
| `tests/` | offline regression tests, no network needed |
| `doc_output/` | emitted `.md` (gitignored) |

## The failure loop (always follow this order)

1. **Reproduce offline** in `.scratch/` (or a scratch file): feed real HTML or
   clipboard text through `extract_content()` directly. Do NOT iterate on the
   live server — it caches the old module until restart (see Gotchas).
2. **Isolate** the cause: static HTML vs Playwright-rendered vs
   copy-markdown clipboard content behave differently; test each path.
3. **Fix in `extract.py`** first (or the receipt, if it's a per-site tweak).
4. **Add a regression test** in `tests/test_extract.py` that pins the bad
   input → clean output. Real-ish HTML in, exact assertions out.
5. **Verify**: `uv run ruff check .` && `uv run pytest -q`.
6. **Restart opencode** (MCP server subprocess), then re-parse the affected
   receipt to confirm clean output end to end.
7. **Commit** per repo style: `fix: …` for code, `receipts: …` for the JSON.

## Symptom → cause → fix (real cases from this repo)

| Symptom | Root cause | Fix |
|---|---|---|
| ` ```english ` (human language) on code fences, or bare ``` on a JS page | receipt `language` was the human doc language; markdownify ignores `data-language` attrs and `language-*` classes, so detection had no source | `_resolve_code_language()` priority in extract.py: explicit `code_language` > page-detected hints (`_detect_code_language` reads `data-language`/`language-*`) > `language` only if it names a code language (`_TRAILING_CODE_LANGS`) > `""` for a bare fence. Receipts grew a `code_language` field |
| Blank line between **every** code line | docs wrap each code line in wrapper divs; markdownify turns each div into its own paragraph | `_collapse_pre_blocks()` rebuilds such `<pre>` as one `<pre><code>` of joined plain lines, before markdownify runs. Recognizes `.ec-line`/`.line` (Astro expressive-code) **and** `.token-line` (Docusaurus Prism — Mojo, Hermes docs) |
| Fences render as bare ` ``` ` though the page shows `mojo`/`python` (Docusaurus) | Prism puts `language-<lang>` on the `<pre>` element; the detector only looked at `<code>` classes | `_detect_code_language()` also scans the `<pre>` class list (`language-mojo` → ```` ```mojo ````) |
| Footer / nav / language-selector text leaked into content | well-chosen `#id` selector still contains page furniture | `strip_tags` per receipt; `probe` now reports `noise_candidates` (footer/select/nav/…) inside the matched block so the ideal selector is caught up front |
| Headings full of `[¶](#quickstart "Link to this heading")` (Sphinx) or `## [Use a plugin](#use-a-plugin)` (Astro) | markdownify keeps self-referencing heading anchor links | `_HEADING_ANCHOR_RE` strips `[¶](…)` without eating the newline (headers must not glue to the next paragraph); `_HEADING_SELF_LINK_RE` unwraps `[Text](#slug)` → `Text` with `re.MULTILINE` |
| Headings polluted by invisible chars — Docusaurus `## Using Skills[​](#using-skills "Direct link to Using Skills")` | Docusaurus marks its heading anchors with a **zero-width space (U+200B)** as link text | same `_HEADING_ANCHOR_RE`, character class extended to `[¶^\u200b]` |
| Raw copy-markdown page has `\r\n` line endings and trailing `[#use-a-skill]` on headings | Playwright clipboard returns CRLF, and the site ships markdown with anchor-slug tokens | `_clean_passthrough()` → CRLF→LF, rstrip lines, collapse 3+ blank lines, and `_strip_heading_hash_tokens()` drops `[#slug]` **only when** the kebab-case of the line text matches the slug (prose `[#…]` links survive) |
| Mojibake in static fetches — `BokmÃ¥l`, `YouTubeâ€'s` | `requests .text` decodes with its default ISO-8859-1 when the server sends no `charset=` in Content-Type; UTF-8 bytes get misread as Latin-1 | `_decode_body()` in fetch.py: honor a charset **explicitly declared in the header** (parsed via `_CONTENT_CHARSET_RE`, NOT `get_encoding_from_headers`, which itself defaults to ISO-8859-1), else try strict UTF-8, then `apparent_encoding`, then replacement Latin-1 |

## Diagnosis recipe

For a newly broken site: run `doc_probe`/`doc_probe_js`, inspect the emitted
`.md`, then reproduce the failing path offline. To grab the exact
copy-markdown a JS site produces:

```python
# scratch — same flow as fetch.py fetch_js()
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b  = pw.chromium.launch(headless=True)
    ctx = b.new_context(permissions=["clipboard-read", "clipboard-write"])
    pg  = ctx.new_page()
    pg.goto(url, wait_until="networkidle", timeout=45_000)
    pg.wait_for_selector("button:has-text('Markdown')", timeout=12_000)
    pg.click("button:has-text('Markdown')")
    pg.wait_for_timeout(800)
    print(pg.evaluate("navigator.clipboard.readText()"))
    ctx.close(); b.close()
```

Feed that through `extract_content()` with a passthrough receipt and inspect.

## Gotchas (hard-won)

- **Line-anchored `re.sub` regexes need `re.MULTILINE`** — `^…$` anchors are
  whole-string by default. Missed three times in this codebase's history.
- **Anchor-strip regexes must not consume the trailing newline** — a `\s*`
  there glues the heading onto the following paragraph.
- `markdownify(code_language=None)` renders ` ```None ` — pass `""` for a bare
  fence, never `None`.
- **Explicit test-encoding traps:** a hypothetical latin-1 page may not have a
  charset declared; validate against *declared* charsets (header regex), not
  `requests` `.encoding` heuristic, which silently reports ISO-8859-1.
- Windows: `python -c` chokes on `\"` quoting — write scratch files; set
  `$env:PYTHONIOENCODING='utf-8'` before printing Unicode (cp1252 console).
- **MCP server stale module:** the server subprocess loads the package once.
  Edits to `src/` are NOT visible until opencode restarts. A re-parse that
  still shows old behavior after a code change is a restart problem, not a
  logic problem — re-verify once after restart.
- `doc_output/` and `.scratch/` are purgable; durable artifacts (extractor
  tweaks, run logs worth keeping) belong in the repo or vault, not scratch.