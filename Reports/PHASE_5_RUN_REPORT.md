# PHASE 5 AUTONOMOUS RUN REPORT

Run date: 2026-08-15/16 (overnight, unattended).
Branch: `feat/phase5-retrieval`, based on `origin/worktree-roadmap-phases-5-7`.
Tickets 01–09: **all nine implemented and committed. The run did not stop
early.** There is no `STOPPED.md`.

**Final verification is green.** Both commands were re-run from a clean tree
immediately before this report was written:

| Command | Result |
|---|---|
| `.venv/Scripts/python.exe -m pytest tests/ -q` | **867 passed, 1 skipped**, exit 0, 102 s |
| `.venv/Scripts/python.exe -m ruff check src tests` | **All checks passed!**, exit 0 |

The single skip is `tests/integration/test_phase3_plots.py:184 — no
ANTHROPIC_API_KEY available`. It is the same skip that existed at baseline; the
suite is otherwise fully offline.

One nit worth knowing before you re-run it yourself: `addopts = "-q"` is already
in `pyproject.toml`, so typing `-q` again makes it `-qq` and pytest **prints no
summary line at all**. The run above looks silent-but-passing either way; use
`pytest tests/` with no extra `-q` if you want to see the count.

## Read this first

Three things, in the order I would look at them:

1. **`Reports/PHASE_5_REPORT.md` § "MCP hand-verification — OUTSTANDING".**
   This is the one acceptance box the run could not close and did not fake. No
   human has registered `dsa serve --mcp` in a real GUI client. The record
   table in that report is deliberately empty and says "not yet run by a human",
   and the report states the phase does not close on it. Everything a test can
   prove about the server *is* proven — the full tool surface was exercised
   against four real datasheets over the SDK memory transport, and ticket 07
   additionally drove the real `dsa serve --mcp` binary through the official
   SDK's `stdio_client` with the README's exact command/args/cwd, completing
   initialize → tools/list → resources/list → tools/call. What is unproven is
   the *registration* in a client, which needs your hands.
2. **`dsa verify --part AFE7950` and `--part AFE7953` exit 1 today.** The two
   reference corpora committed under `parts/` were published before ticket 03
   started writing `search_index.json`, so their new search-path golden reports
   `search unavailable: … Rebuild to enable search` and fails. This is
   deliberate honest degradation — the path never ran, so it does not pass —
   but it means a cold `dsa verify` on the committed corpora is red, and you
   should decide whether you are happy with that or want the corpora rebuilt
   and re-committed. AFE7950 needs one `dsa build` (network, TI). AFE7953 has
   **no offline build path at all** (no recorded TI document-viewer pages), so
   its gate test verifies against a copy whose index is rebuilt from the
   published markdown by the writer's own `build_search_index`.
3. **Ticket 04's grading finding.** Three of the four gate corpora (LM741,
   QPA1003P, HMC520A) grade **100% `low`** confidence on specs. The cause is
   real and measured: their captionless-era grids never pass the reconstruction
   gate on the header-declared split — rung 0 fails with "words fall outside the
   column bands" on every region — so only a rescue split reconstructs anything.
   The grade is faithful to the rule and is arguably true advice, but it carries
   no discrimination inside those parts. The implementer's judgement, which I
   agree with: the fix belongs in the layout floor, not in the grading rule. It
   is noted in `AGENTS.md` so nobody "improves" the mix by loosening the rule.

## Test count vs the 384 baseline

| | Tests | Passed | Skipped |
|---|---|---|---|
| Baseline (before ticket 01) | 384 | 383 | 1 |
| After ticket 01 | 418 | 417 | 1 |
| **Final (after ticket 09)** | **868** | **867** | **1** |

**+484 tests, zero regressions, zero deletions from the existing suite.** Two
independent checks back the "nothing was weakened" claim rather than my word:

- The six golden Q&A fixtures changed by **238 insertions and 0 deletions**.
  Not one existing expected answer, page or section was edited — every golden
  change this run is a new question appended.
- The residual-tracking sets (`KNOWN_ASK_MISSES` in
  `tests/integration/test_afe7950_build.py:331` and
  `tests/integration/test_phase4_layout_gate.py:625`) are asserted with **exact
  set equality**, so a regression fails *and* an unrecorded fix fails. They
  cannot be used to paper over a break.

Fourteen new test files landed, including `tests/unit/test_retrieve.py`,
`test_search.py`, `test_aliases.py`, `test_ask.py`, `test_confidence.py`,
`test_projects.py`, `test_mcp_server.py`, `test_mcp_responses.py`,
`test_protocol.py`, `test_golden_paths.py`, and the new
`tests/fixtures/golden_qa_AFE7953.yaml`.

## What landed, per ticket

| # | Commit | Subject | Files / lines |
|---|---|---|---|
| 01 | `6e5207b` | retrieval core seam | 11 files, +1238 / −199 |
| 02 | `adf567e` | alias lexicon | 13 files, +10201 / −49 |
| 03 | `f988aa2` | full-text search | 21 files, +1448 / −19 |
| 04 | `5b54a75` | per-record confidence | 23 files, +1381 / −80 |
| 05 | `1ab057e` | answer packs (`dsa ask`) | 15 files, +2364 / −16 |
| 06 | `696b701` | projects | 17 files, +2127 / −65 |
| 07 | `7d5c869` | mcp server (local stdio) | 18 files, +2450 / −14 |
| 08 | `f6fd723` | agent protocol files | 16 files, +1109 / −25 |
| 09 | `059c1f9` | golden extension + phase gate | 21 files, +1600 / −131 |

(`40f5507 chore: phase 5 autonomous implementation workflow` is the harness
commit that started the run.)

**01 — retrieval core seam.** All retrieval moved behind one module; `cli.py`
holds no retrieval logic, enforced by a source-token guard test that fails when
someone re-inlines a corpus walk or hand-builds a citation. Crude, but it is the
only assertion that actually catches the regression it is aimed at. Cache reuse
and invalidation are asserted by counting `Path.read_text` calls — never by
timing — and invalidation uses an explicit `os.utime` mtime bump, so there is no
clock-granularity race.

**02 — alias lexicon.** 77 entries. Ticket-time it measured 76 entries and a
52% hit rate over 65 questions from five goldens; ticket 09 added the AFE7953
benchmark and more entries, so the **final measured figure is 59/88 = 67%**
resolved via alias, with a 45% floor asserted so a lexicon or ladder regression
fails. Per part: AFE7950 15/21, AFE7953 11/13, AD9081 5/6, LM741 8/17,
QPA1003P 12/16, HMC520A 8/15.

**03 — full-text search.** Index economics are measured and stored in every
manifest's `CorpusStats`: AD9081 69 KB index = 0.9% of corpus, LM741 49 KB =
7.3%, QPA1003P 19 KB = 5.2%, HMC520A 37 KB = 0.6%.

**04 — per-record confidence.** Mix recorded for five of six parts. AFE7950
613/3/3 high/medium/low specs and 0/514/0 plots; AFE7953 531/2/3 and 0/492/0;
AD9081 151/207/191; LM741, QPA1003P, HMC520A all-low (see "Read this first" #3).

**05 — answer packs.** 88 questions answer under budget at 3000 tokens and at
the tight 400; largest pack 445 tokens.

**06 — projects.** A three-part `PROJECT_INDEX.md` measures 190 tokens against
a 4000-token budget; project-scoped `ask` routes each member's own golden back
to that member.

**07 — MCP server.** Local stdio. Full tool surface tested; registration in a
real client is the outstanding box above.

**08 — agent protocol.** `protocol.py` renders one rule set into
`parts/<PART>/AGENT.md` (1,420 tokens, ceiling 1,700),
`projects/<NAME>/AGENT.md` and the checked-in skill.

**09 — golden extension + phase gate.** Added the AFE7953 benchmark and ask/
search twins across all six parts, and wrote `Reports/PHASE_5_REPORT.md`.

## Open items

### Needs a human — blocks phase closure

- **MCP hand-verification.** Detailed above. Raised at ticket 07, carried
  through 08, still open at 09. `Reports/PHASE_5_REPORT.md` has the empty
  record table waiting for the client, the date and the calls made.

### Needs a decision — network required

- **AFE7950 and AFE7953 corpora under `parts/` are stale** in three respects:
  no `search_index.json` (so `dsa verify --part` exits 1), `confidence:
  unknown` on every record (so `dsa status` prints no confidence line), and no
  `AGENT.md` on disk. All three clear the moment the part is rebuilt, and the
  batch skip gate now refuses to skip such a corpus, so it is one command — but
  it is a networked TI fetch, so the run did not do it. AFE7953 cannot be
  rebuilt offline at all: the recorded HTTP fixtures only cover AFE7950.
- Ticket 08 explicitly declined to hand-write the two missing `AGENT.md` files,
  on the grounds that a manifest reporting `agent_doc_tokens: 0` next to a file
  that exists would be a corpus stating something untrue about itself. I think
  that was the right call.

### Known residuals — recorded in tests, not hidden

- **AFE7950 `q07-vco-coverage`** — the question names `VCOs`, a symbol *prefix*
  (`fVCO1`…`fVCO4`), not a phrase a whole-phrase lexicon can match; its expected
  extremes are the first and last of eight sibling rows, so the per-route row
  cap would drop one even if the rung existed.
- **LM741 `s1-spec-supply-absmax`** — the ask path reaches the named
  absolute-maximum supply rows and cites p.4, but the `±18` the question also
  expects lives on a nameless device-variant sub-row whose only text is the
  symbol `Supply`. Closing it is an extraction change (materializing an
  inherited *parameter name* into continuation rows), not a retrieval one.
- **Search top-1 is 64%** (top-3 82%) over whole-sentence questions across all
  88 goldens, with HMC520A the floor at 33% for a structural reason: unnumbered
  outline, 107 near-identically worded figure sections. The six search-path
  goldens — keyword queries, which is how `dsa search` is actually used — rank
  the answering section first **6/6**. This is the number the plan said to
  measure before considering embeddings. Nothing was tuned to improve it.

### Ticket-time items that later tickets closed — do not chase these

Several open items in the per-ticket handoffs were superseded before the run
ended. Flagging them so you do not spend the morning on closed work:

- Tickets 02, 03, 04, 05, 06, 07 and 08 each reported "`Reports/PHASE_5_REPORT.md`
  does not exist yet". It exists now — ticket 09 wrote it, 257 lines, with the
  measured numbers transcribed out of the tests that print them.
- Tickets 02 and 05 reported "AFE7953 has no golden benchmark". It has one now:
  `tests/fixtures/golden_qa_AFE7953.yaml`, 13 questions, added by ticket 09.
- Ticket 05 reported **five** twin-agreement misses out of 31. The final
  measured figure is **37/39 twins** with only the two residuals listed above.
  AFE7950 `q13-min-1p2v-supply`, QPA1003P `s2-spec-frequency-range` and
  HMC520A `q04-lo-amplitude` now pass. I verified this is a real fix and not a
  weakened test: all three questions are still present in their golden files
  unmodified, and the `KNOWN_ASK_MISSES` sets are exact-equality assertions, so
  a still-failing question would fail the suite.
- Ticket 05 noted that the plan's illustrative answer `TJ … 105 °C — §4.3, p.6`
  is not AFE7950's real data. Worth remembering when reading the plan: the real
  corpus prints `TJ Junction temperature: 150 °C (max) — §4.1, p.4`, and that
  is what the pack returns. The literal §4.3/p.6 shape is asserted against a
  synthetic corpus built to the plan's example.

### One design decision that was deliberately *not* taken

Regenerating the committed search indexes for AFE7950/AFE7953 was rejected,
because the existing test
`test_a_corpus_published_before_search_says_rebuild_not_no_match` records
AFE7953's un-indexed state and weakening it is forbidden by the run's rules. If
you would rather have green `dsa verify` than that recorded behaviour, that is
your call to make, not the run's.

## Reviewer notes carried forward

- The `cli.py` source-token guard test (ticket 01) is crude by construction.
  It is a string check over source. If it ever fires spuriously, fix the guard,
  do not delete it — it is the only thing standing between the seam and slow
  re-inlining.
- The confidence grading rule (ticket 04) should not be loosened to make the
  mix look better on LM741/QPA1003P/HMC520A. `AGENTS.md` says so; this report
  says so twice.
- Every measured number in `Reports/PHASE_5_REPORT.md` is printed by a test at
  run time, so it cannot drift silently from the code. If you change a number
  in the report, a test will contradict you.
