# PHASE 6.5 WAVE 0 — measured results

**Status: landed, one item blocked.** Tickets `.scratch/extraction-fidelity/issues/01–04`.
Execution contract: `Reports/PHASE_6_5_PLAN.md`. Waves 1 and 2 are not started.

Wave 0 is the part of Phase 6.5 that changes no extraction output and
therefore needs no rebuild. Three tickets landed; the fourth landed one of its
three steps and is blocked on a condition outside the code.

| # | Ticket | Outcome |
|---|---|---|
| 01 | `--json` stdout purity | landed |
| 02 | axis filters reachable from the CLI | landed |
| 03 | card invalidated when its document moves | landed |
| 04 | `ruff format` adopted | **step 1 of 3 only — blocked** |

Suite: **2308 collected, pytest exit 0, 0 failures**, up from 2276 at the
wave's start (+32 new tests, no test removed or skipped). `ruff check` clean.

---

## 01 — `--json` emits JSON and nothing else

**The plan's premise was right and its numbers were wrong.** Re-measuring
before writing the ticket found:

- The repo offers `--json` on **eight** verbs, not the five the plan named:
  `query`, `search`, `ask`, `plots`, `pins`, `regs`, `card`, `compare`.
- All eight parse **clean** in the main tree, which resolved **PyMuPDF
  1.28.0**, where `import fitz` prints nothing.
- The Phase 6 worktree resolved **PyMuPDF 1.28.2**, where `import fitz` prints
  `warning: The 'fitz' API is deprecated…` **to stdout**. That is where the
  original measurement came from, and it is real.
- `pyproject.toml` pins `pymupdf>=1.24`.

So whether this repo's `--json` was parseable was decided by dependency
resolution, not by this repo — and the defect is wider than one deprecation
line, because MuPDF writes its own diagnostics (malformed xref, unloadable
font) to the same stream on *every* version.

**Fix:** `_route_pymupdf_messages()` in `cli.py`, called as the first act of
`main()`, defaulting `PYMUPDF_MESSAGE=fd:2`. `setdefault`, so an operator who
routed messages deliberately keeps their routing. `main()` is the single
console entry point, so this also covers `dsa serve --mcp`, where stdout is a
JSON-RPC stream and pollution is worst.

**The test proves the mechanism, not the ambient version.** A test that only
parsed stdout would pass on 1.28.0 with the fix deleted. Instead:
`test_main_routes_before_dispatching` asserts the variable is in force from
*inside* the dispatch; `test_cli_import_does_not_reach_pymupdf` parses
`cli.py`'s own AST to prove no eager import could beat `main()` there; and
`test_every_json_verb_is_exercised` reads the parser's AST so a ninth `--json`
verb added later cannot silently escape the guarantee.

**Mutation-checked:** with the call replaced by `pass`, the suite fails
(`assert [None] == ['fd:2']`) on this quiet-PyMuPDF venv. The guarantee is
real here, not inherited from the installed version.

## 02 — Axis filters reachable from the CLI

`query.find_plots()` and `Retriever.plots()` already accepted `x_label`,
`y_label`, `near_x`, `near_y` — implemented, tested, and reachable from MCP.
Only the argument parser was missing them, because Phase 6 froze `cli.py`.

**A second seam was missing too, which the plan did not anticipate.**
`ProjectScope.plots()` did not accept the axis keywords at all, so
`dsa plots --project X --near-x …` would have raised
`TypeError: ProjectRetriever.plots() got an unexpected keyword argument
'x_label'`. Verified by reverting that file and watching the test fail with
exactly that error. Wiring only the parser would have shipped a flag that
crashes in one of the two scopes.

**The plan's worked example, measured on real data:**

| Query | Figures |
|---|---|
| `dsa plots --part HMC520A` | 107 |
| `… --x-label Frequency` | 42 |
| `… --x-label Frequency --near-x 3.5GHz` | **2** |

Both survivors matched `via axis · high`: *Figure 77* and *Figure 78,
Conversion Gain vs. IF Frequency at Various Temperatures* (p.22). On LMX1204,
`--y-label "Noise Floor" --near-x 3.5GHz` narrows 34 figures to 6. This is the
capability the phase-6 plan promised — 107 candidates down to 2 before a
single vision token is spent.

**Deliberately omitted:** `find_plots` also accepts `caption` and `conditions`
independently of `q`. They are not exposed. `--q` already searches both, and
the distinction (match the caption but not the conditions) has no demonstrated
caller. Recorded so the omission is a decision, not an oversight.

### Found while measuring: no corpus in this tree carries axis metadata

The worked example returned **0 hits on every part** at first. The cause is
not the wiring:

- Across all 218 published `plots.json` in `library/`: **2806 plots, 0 with
  axis metadata, `axis_confidence` absent on every one.**
- `parts/AFE7950` — the part the phase-6 gate measured 400/514 on — is built
  at pipeline **0.1.0**, five versions before the axis catalog existed.
- The phase-6 worktree's library *does* carry it (65 high, 183 low of 1254),
  which is where the 400/514 came from.

And the sharper half: **`PLOTS_SCHEMA_VERSION` was not bumped when the axis
catalog was added.** Every file above is schema `"2"`, exactly like a freshly
built one whose axes all failed to read. **The corpus cannot distinguish "not
attempted" from "attempted and unreadable"** — the precise failure invariant 8
exists to prevent, one level up from where it was applied. This is not a wave
0 fix (bumping the version republishes every `plots.json`); it belongs with
ticket 09's rebuild and its ADR, and it is filed there.

## 03 — A card is invalidated when its document moves

`load_card` called a card current when `schema_version` and `card_version`
matched. Neither changes when a document is republished from `docs/<doc>` to
`@library/docs/<doc>`, and every `source` a card holds is built from that
base — so a republish rewrote every citation while both version fields stayed
equal.

**Fix:** `Card.corpus_key`, a 16-hex digest over the sorted `(doc name,
ref_base)` pairs the corpus resolved to. `load_card` recomputes it via
`part_corpus_key()` and returns `None` on a mismatch, so a moved document is a
cache miss instead of a red gate. `CARDS_SCHEMA_VERSION` 1 → 2.
`publish.cards_current` reads the same function, so the batch skip gate and
the reader cannot disagree — two rules that could would produce a part the
gate skips and the reader rebuilds on every query.

**The defect reproduced in miniature, then closed.**
`test_without_the_key_the_stale_card_would_have_been_served` builds a card,
moves its document, and asserts on the file as written: `schema_version` and
`card_version` both still match, and auditing it gives **`resolved == 0` of
`checked > 0`** — the same shape as AD9081's 87-of-87. With the key,
`test_the_rebuilt_card_audits_clean` gets **0 problems and `resolved ==
checked`**.

**Cost, measured** — the check must be cheaper than the build it avoids:

| Part | Key recompute (cold / warm) | Build all cards |
|---|---|---|
| AD9081 | 27.4 ms / 1.6 ms | 1779 ms |
| HMC520A | 5.7 ms / 1.8 ms | 58 ms |
| LMX1204 | 28.5 ms / 2.6 ms | 1685 ms |

Cold is the first call in a process (`CorpusIndex` reads the manifest, then
caches); warm is every call after. Worst ratio is HMC520A at ~10% of a build,
and that read is one the build performs anyway.

**Stability, asserted not assumed:** the key is byte-identical across a
rebuild of identical input, and identical for the same part checked out at two
different paths — no absolute path reaches the digest, or every clone would be
born stale and rebuild on every read.

## 04 — `ruff format` — one step of three, then blocked

**Step 1 landed.** `Reports` added to `[tool.ruff] extend-exclude`. ruff 0.16
formats Python inside Markdown fences, and `Reports/PHASE_2_PLAN.md` and
`PHASE_3_PLAN.md` illustrate a model with hand-aligned comment columns that
carry the explanation:

```
    verbatim: str          # "Ω" (U+2126), "dBc/Hz", "" when unitless
```

`Reports/` is the archive of what each phase decided and measured. Rewriting
history to satisfy a source-code gate is the wrong trade. `docs/` stays in
scope: nothing there is affected today, and an ADR's code should read like the
code it describes.

**Steps 2 and 3 did not run.** `ruff format .` is repo-wide, and at the moment
wave 0 reached this ticket a second agent was actively editing this working
tree — `app/contracts.py`, `app/routers/projects.py`, `projects/shelf.py`,
`tests/unit/test_projects_api.py`, all of `web/`, and a new untracked
`app/sectiontext.py`, every one touched within the preceding 40 minutes. The
unformatted count moved from 81 files to 84 while wave 0 was running.

Running the formatter then would have rewritten another agent's half-finished
work and folded a mechanical reformat into their feature diff — destroying the
one property that makes this a worthwhile standalone commit. **It needs a tree
with one writer.** The 81/84 figures are already stale and must be re-measured
when it runs.

The same caveat applies, more weakly, to this wave's full-suite run: it
executed against a tree another agent was writing to. Every per-ticket test
above was run in isolation and is trustworthy; the repo-wide green is the
weaker signal.

## What wave 0 did not touch

No extraction output changed, so no cache was invalidated and nothing was
rebuilt — which was the point of separating these four from the rest.
`CARDS_SCHEMA_VERSION` 1 → 2 does republish every part's cards on next read,
but cards build from published JSON without re-reading a PDF; measured at
58–1779 ms per part above.

Wave 1 (tickets 05–08) and wave 2 (ticket 09) are unstarted. Wave 1 must land
as a single cache-invalidating change; splitting it costs a full re-extraction
per split.
