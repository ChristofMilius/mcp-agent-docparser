# mcp-agent-docparser

**SDK documentation extractor** as a local **MCP server**. Point an
MCP-aware agent harness at a documentation site, and it fetches the pages,
strips navigation noise, converts HTML to clean markdown, and returns (or
writes) a `.md` file ready to drop into any LLM context window.

Pipeline: **fetch → extract → emit**.

This is the terminal-menu `docparser` (a standalone project) rebuilt as an
MCP tool for the agent-tools stack. The interactive REPL commands became
MCP tools: receipt management, parse, and probe are now callable by any
harness (Claude, opencode, etc.) over stdio.

## Tool surface

| Domain | Tools |
|---|---|
| Receipts | `receipt_list`, `receipt_show`, `receipt_add`, `receipt_edit`, `receipt_delete`, `receipt_reload` |
| Parse | `doc_parse`, `doc_parse_url` |
| Discovery | `doc_probe`, `doc_probe_js`, `doc_output` |
| Utility | `get_current_datetime` |

## Receipts

A **receipt** is a named profile that tells docparser how to fetch and
extract one documentation site. Receipts live in `receipts.json` — never in
the Python source. The repo ships two prefilled examples: **Memvid**
(`memvid-python`, static Mintlify) and **LM Studio** (`lmstudio-python`,
JS-rendered Next.js with a Copy-as-Markdown button). Delete them or keep
them; they are regular receipts.

### Receipt schema

```jsonc
{
  "my-sdk-python": {
    // Required
    "name":      "My SDK (Python)",          // human label
    "language":  "python",                   // used in code blocks and header
    "urls":      ["https://docs.example.com/overview"],  // fetched in order
    "selectors": ["#content", ".prose", "article", "body"],

    // Optional
    "strip_tags":           ["nav", "footer", "header", "script", "style"],
    "section":              null,            // restrict to content after this H2 text
    "js_render":            false,           // use Playwright instead of requests
    "markdown_passthrough": false,           // treat extracted <pre> as raw markdown
    "notes":                "",              // free-text notes about the site

    // Managed automatically
    "last_fetched": null,                    // ISO date of last successful parse
    "last_output":  null                     // filename of last emitted .md
  }
}
```

## Workflow for a new site

```
1. doc_probe           → paste the docs URL, see which selectors match and
   (or doc_probe_js      what H2s exist. Nothing matched? The site is
    for JS-rendered)     probably JS-rendered — retry with doc_probe_js.
2. receipt_add         → save the findings as a receipt (best_selector +
                         strip_tags / js_render / markdown_passthrough).
3. doc_parse(key)      → fetch, extract, emit .md into doc_output/. Returns
                         the rendered markdown directly. doc_parse with
                         dry_run=true previews what will be fetched.
```

For a single unfamiliar page that matches an existing receipt's template,
`doc_parse_url(template_key, url)` parses it without persisting a receipt.

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- Playwright Chromium (only for `js_render` receipts):
  `uv sync && uv run playwright install chromium`

## Install

```powershell
git clone <repo-url> mcp_agent_docparser
cd mcp_agent_docparser
uv sync
```

## Usage

### Run as an MCP server (stdio — what harnesses expect)

```powershell
uv run mcp-agent-docparser
```

Override paths via environment variables (defaults resolve relative to the
project root, never the process CWD):

| Var | Default | Purpose |
|---|---|---|
| `DOCPARSER_RECEIPTS` | `receipts.json` | Path to the receipts registry |
| `DOCPARSER_OUTPUT_DIR` | `doc_output` | Where emitted `.md` files go |
| `DOCPARSER_LOGS_DIR` | `logs` | Rotating DEBUG logs (5×5 MB) |

To serve over HTTP (streamable-http) instead:

```powershell
uv run mcp-agent-docparser serve --http --port 8000
```

### Register in an MCP client

```json
{
  "mcpServers": {
    "mcp-agent-docparser": {
      "command": "uv",
      "args": ["--project", "C:/path/to/mcp_agent_docparser", "run", "mcp-agent-docparser"]
    }
  }
}
```

### CLI commands

| Command | Purpose |
|---|---|
| `serve` *(default)* | Run the MCP server. `--http --port` for streamable-http |
| `doctor` | Offline diagnostics: paths, registry state, emitted files |

## Output

Files are written to `doc_output/` as `{receipt_name}_{YYYYMMDD_HHMMSS}.md`.
Each file contains a header block (language, fetch timestamp, source URLs),
the receipt's `notes` if set, and one `<!-- SOURCE: url -->` section per
fetched page. `doc_parse` also returns the rendered markdown in its result,
so the model can use the content even if the harness has no filesystem view.

## Development

```powershell
uv run ruff check .
uv run pytest -q
```

Tests cover the receipt registry, config path resolution, extraction, the
parse pipeline (mocked fetch), and the full tool surface — no network needed.

## Agent skill: fixing noisy fetched pages

When a fetched page comes out malformed (wrong code-fence language, blank
lines in code blocks, leaked navigation noise, heading-anchor junk, CRLF
copy-markdown), opencode loads the **`docparser-page-fixes`** skill from
`.opencode/skills/docparser-page-fixes/SKILL.md`. It teaches the
reproduce → isolate → fix → test → restart loop, maps the real
symptom/cause/fix cases from this repo's history, and lists the extractor's
gotchas (MULTILINE regexes, trailing-newline traps, the stale-MCP-module
restart requirement). Extend it whenever the extractor grows a new fix.

## License

MIT © 2026 Christof Milius