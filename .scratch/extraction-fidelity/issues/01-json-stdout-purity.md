# 01 — `--json` must emit JSON and nothing else

**What to build:** A guarantee that stdout carries the payload and only the
payload, on every verb that offers `--json`, independent of which PyMuPDF the
environment resolved.

**Measured, and measured twice — read this before starting.** The Phase 6.5
plan recorded "`dsa card --part AD9081 --card power --json | jq` fails" and
named five verbs. Re-measuring on the merge tree found something more useful:

- The repo offers `--json` on **eight** verbs, not five: `query`, `search`,
  `ask`, `plots`, `pins`, `regs`, `card`, `compare`.
- All eight currently parse **clean** in the main tree's venv, which resolved
  **PyMuPDF 1.28.0**. Importing `fitz` there prints nothing.
- The Phase 6 worktree's venv resolved **PyMuPDF 1.28.2**, where `import fitz`
  prints `warning: The `fitz` API is deprecated…` **to stdout**. That is where
  the original measurement came from, and it is real.
- `pyproject.toml` pins `pymupdf>=1.24`. **Whether this repo's `--json` is
  parseable is therefore decided by dependency resolution, not by this repo.**

That is the defect worth fixing, and it is larger than one deprecation line:
MuPDF writes its own diagnostics (malformed xref, bad font, recoverable syntax
errors) to the same stream, so any sufficiently broken PDF corrupts a `--json`
payload today on *every* PyMuPDF version.

**Fix:** `os.environ.setdefault("PYMUPDF_MESSAGE", "fd:2")` at the top of
`cli.py`, before any lazy import can reach `fitz`. Verified to work: with it
set, the 1.28.2 warning lands on stderr and captured stdout is empty.
`setdefault`, not assignment, so an operator who has routed messages somewhere
deliberately keeps their routing.

`cli.py` is the single console entry point (`dsa = datasheet_analyzer.cli:main`),
so this one line also covers `dsa serve --mcp` — where stdout pollution is
worst, because it is a JSON-RPC stream — and `dsa serve`.

**Do not** rewrite the nine `import fitz` sites to `import pymupdf`. It would
silence one message on one version while leaving MuPDF's own chatter on
stdout, and the `>=1.24` floor predates the `pymupdf` module name.

**Blocked by:** —

**Status:** done

- [x] `PYMUPDF_MESSAGE` defaulted to `fd:2` in `cli.py`, above every import
      that could reach `fitz`, with a comment naming *why* (stdout is the
      payload channel) rather than what
- [x] A test asserts stdout parses as JSON for **all eight** `--json` verbs
- [x] That test proves the *mechanism*, not the ambient version: it must fail
      if the env default is removed, on a venv where importing `fitz` is
      silent. Simulate the write (a fixture that prints to stdout from inside
      the code path, or assert the env var's effect directly) — a test that
      only passes because 1.28.0 happens to be installed asserts nothing.
- [x] No subprocess, no network, no PDF read — invariant 4 holds
- [x] `dsa --help` and every non-`--json` path unchanged

**Owns:** `src/datasheet_analyzer/cli.py`, `tests/unit/test_cli_json.py`

---

Source: `.scratch/extraction-fidelity/SPEC.md`
