# TODO / Backlog

Non-urgent ideas, cleanups, and deferred decisions. Not a commit log — items
land here when they are deliberately *not* acted on right now.

## Formatting rust (ruff format)

`ruff format --check .` flags 24 files repo-wide (as of the Phase 2 commit
`3438c85`). This is pre-existing style drift — column-aligned dicts (e.g.
`hits: list[str]   = []` in `probe.py`), trailing-comma style, line-wrapping
preferences that changed with the ruff version — not introduced by any phase.

The repo's gate is `ruff check` (green); `format` is not enforced. A sweep is
a standalone, no-logic-change commit: run `ruff format .`, re-run
`ruff check .` + full pytest, and review the diff as diff-only (it will
touch every file).

## Toolchain

- Ruff formatted python files must not be committed mixed with logic —
  never merge a formatting sweep into a feature phase.