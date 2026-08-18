# FULL-SCALE TEST — runbook

**Written for: 2026-08-19.** Every command in Stages 0–6 was executed by the
author against this worktree before being written down; the observed output is
quoted beside it. Stages 7+ cover Phase 7/8 capabilities and are marked with
their landing status — do not run a stage whose phase has not landed.

Budget about **90 minutes** for Stages 0–6, which is the part that tests the
system as it exists today.

---

## What you are testing

A hardware designer, mid-schematic-capture, asks a model a question about a
part and gets a correct, cited answer in one round trip. Concretely:

1. a datasheet PDF becomes a corpus, offline and deterministically;
2. every answer carries a printed page you can check;
3. an agent can drive the whole thing over MCP without you;
4. the system says *"I don't know"* rather than guessing.

Item 4 is the one worth attacking hardest. A tool that confidently returns a
wrong number is worse than no tool, so several steps below are deliberately
designed to make it fail.

---

## Stage 0 — Setup (5 min)

```bash
cd C:/Users/afpim/Repos/datasheet_analyzer/.claude/worktrees/roadmap-phases-5-7
git log --oneline -1
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check src tests
.venv/Scripts/dsa.exe status
```

**Observed:** `1663 passed, 1 skipped` in 202 s at the Phase 6 baseline, ruff
clean. After Phase 7 ticket 01 the suite is `1708 passed`. `dsa` lives at
`.venv/Scripts/dsa.exe`.

`dsa status` prints `llm: NO KEY (deterministic mode)`. **That is the correct
mode for this test** — every number below is reproducible.

> **`pytest -q` gotcha:** `addopts = "-q"` is already set. Adding another `-q`
> makes it `-qq` and pytest prints no summary line at all.

---

## Stage 1 — Security hygiene (2 min, do this first)

`.env` is tracked in git in the **main checkout** and contains an `API_KEY`
line. It has never been committed. Clear it before it can enter history:

```bash
cd C:/Users/afpim/Repos/datasheet_analyzer
git status --short .env          # confirm it is staged/tracked
git rm --cached .env
git commit -m "chore: untrack .env"
```

The worktree's `.gitignore` already lists `.env`; confirm the main checkout's
does too.

---

## Stage 2 — Build a corpus offline (5 min)

```bash
export DSA_PARTS_DIR=/c/tmp/dsatest/parts
export DSA_CACHE_DIR=/c/tmp/dsatest/cache
.venv/Scripts/dsa.exe build lm741.pdf --part LM741 --vendor unknown
```

**Observed:** exit 0. `40 sections, 6 tables, 3 figures, 10 footnotes, 71 spec
records, 3 plot files; corpus 13 672 tokens; INDEX.md 2 253 tokens (budget
3 000); page coverage 40/40`.

**`--vendor unknown` is required to build a TI part offline.** Without it,
vendor detection pins `ti`, which routes to the `ti_html` backend and needs
network. See **F2** — that path crashes rather than degrading.

---

## Stage 3 — Verify, and learn to read the number (5 min)

```bash
.venv/Scripts/dsa.exe verify --part LM741 --pdf lm741.pdf
```

**Observed: `17/17 passed (100%)`.**

Now run it **without** `--pdf` and watch it report **`2/17 passed (12%)`** on
the identical corpus. Nothing is broken; the page-truth check is *disabled*,
but a disabled check renders as ❌ and still counts in the headline. This is
**F1**, and it is the single most misleading output in the system.

**Rule: always pass `--pdf`.**

For a part with companion documents, `--pdf` must point at the document the
questions are actually sourced from — see **F12** and Stage 5.

---

## Stage 4 — The retrieval surfaces (15 min)

```bash
.venv/Scripts/dsa.exe ask    --part LM741 "what is the maximum supply voltage?"
.venv/Scripts/dsa.exe search --part LM741 "offset null"
.venv/Scripts/dsa.exe card   --part LM741 --card power
.venv/Scripts/dsa.exe pins   --part LM741
.venv/Scripts/dsa.exe plots  --part AFE7950 --y-label "Fullscale"
```

**Observed:**

- `ask` → `Supply voltage: ±22 V (max) — §6.1, p.4 [low]`, a supporting
  excerpt, and a `Verify: Printed page 4 of lm741.pdf` footer. Correct.
- `search` → BM25 hits with scores and page cites; the §5 hit returns the
  printed pin table verbatim.
- `card --card power` → a provenance table with grades and `§x.y, p.N`, and
  the disambiguation note *"largest of 2 printed values for this parameter"*.
  Note the syntax is `--card power`, **not** a positional argument.
- `pins` → an honest-degradation message. But see **F6**: LM741 *does* print a
  pin table and extraction yielded zero pins with no recorded reason.
- `plots --y-label` → filters on the printed axis, reports ranges and scale,
  **and states its blind spot**: *"23 of 514 figures publish no readable y
  axis … cannot establish that no such figure exists."* That sentence is the
  behaviour to look for everywhere.

### Things to try that should fail honestly

```bash
.venv/Scripts/dsa.exe query  --part LM741 --symbol NOSUCHSYMBOL
.venv/Scripts/dsa.exe ask    --part LM741 "what is the gate charge?"
.venv/Scripts/dsa.exe regs   --part LM741
```

A good result is an explicit *"not found, here is what I looked for"*. A bad
result is a confident wrong number. **Report anything that guesses.**

---

## Stage 5 — The fleet: 7 parts, 3 vendors (20 min)

All seven parts have been rebuilt at the current schema and verified. Rebuild
them yourself, or use `parts/` if the corpora have been moved in.

| Part | Vendor | Build command | Goldens |
|---|---|---|---|
| AFE7950 | TI | `build afe7950.pdf --part AFE7950` *(network)* | 21/21 |
| AFE7953 | TI | `build afe7953.pdf --part AFE7953` *(network)* | 13/13 |
| LM741 | TI | `build lm741.pdf --part LM741 --vendor unknown` | 17/17 |
| LMX1204 | TI | see below — **needs its companion** | 12/12 |
| AD9081 | ADI | `build ad9081.pdf --part AD9081` | 12/12 |
| HMC520A | ADI | `build hmc520a.pdf --part HMC520A` | 15/15 |
| QPA1003P | Qorvo | `build QPA1003P.pdf --part QPA1003P` | 16/16 |

**106 golden questions, all passing.**

LMX1204 is the multi-document case and the most instructive one:

```bash
.venv/Scripts/dsa.exe add-doc tests/fixtures/pdf/LMX1204_registermap.pdf \
    --part LMX1204 --type register_map --vendor unknown
.venv/Scripts/dsa.exe build tests/fixtures/pdf/lmx1204.pdf \
    --part LMX1204 --vendor unknown
.venv/Scripts/dsa.exe verify --part LMX1204 \
    --pdf tests/fixtures/pdf/LMX1204_registermap.pdf
```

**Observed:** without the companion it scores **2/12**. With the companion and
`--pdf` pointed at the *register map*, **12/12**. Pointed at the *datasheet*,
still 2/12 — because all twelve questions are sourced from the companion and
`verify` accepts only one `--pdf`. That is **F12**.

Then exercise registers, which is what bring-up actually needs:

```bash
.venv/Scripts/dsa.exe regs --part LMX1204 --address 0x18
.venv/Scripts/dsa.exe regs --part LMX1204 --name "Temperature Sensor"
```

**Observed:** 28 of 35 registers publish validated bit fields; the other 7
publish `fields: []` with a recorded reason. Seven registers with no fields is
a *recorded limit*, not a silent gap — confirm the reason is stated.

---

## Stage 6 — MCP: the agent path (15 min)

This is the capability the whole roadmap exists to deliver, and the one step
still needing a human.

**Verified already** (real subprocess over stdio, not the in-process test
transport): `initialize` handshake OK, `tools/list` returns **13 tools**,
`tools/call ask` returns a cited answer at 892 tokens of a 6000 budget, output
is correct UTF-8, and `dsa version` writes only `0.5.0` to stdout so the
JSON-RPC framing is clean.

The 13 tools: `list_parts`, `list_projects`, `get_index`, `search`,
`find_spec`, `find_plots`, `find_pin`, `find_register`, `get_card`,
`read_section`, `get_figure`, `compare_parts`, `ask`.

Register it in your GUI client:

```json
{
  "mcpServers": {
    "datasheet-analyzer": {
      "command": "C:\\Users\\afpim\\Repos\\datasheet_analyzer\\.claude\\worktrees\\roadmap-phases-5-7\\.venv\\Scripts\\dsa.exe",
      "args": ["serve", "--mcp"],
      "env": {
        "DSA_PARTS_DIR": "C:\\Users\\afpim\\Repos\\datasheet_analyzer\\.claude\\worktrees\\roadmap-phases-5-7\\parts"
      }
    }
  }
}
```

Then ask the model, in its own words:

1. *"Which parts do you know about?"*
2. *"What is the AFE7950's maximum junction temperature? Cite the page."*
3. *"I'm clocking the LMX1204 — what do I write to R0 to reset it?"*
4. *"Compare the AFE7950 and AFE7953 power rails."*
5. *"What's the gate charge of the LM741?"* ← **must decline**, not invent.

**This is the real test.** Everything before it is machinery.

---

## Stage 7+ — Phase 7 and 8 capabilities

**Status at the time of writing: Phase 7 ticket 01 landed** (document registry
+ `dsa fetch`, 45 new tests). Tickets 02–08 and all of Phase 8 were still
running. **Check `git log --oneline` and `Reports/PHASE_7_REPORT.md` before
running anything here** — a command whose ticket has not landed will simply not
exist.

When Phase 7 has landed, the network steps are consolidated in
`Reports/PHASE_7_LIVE_RUN.md`. The important ones:

```bash
dsa fetch AFE7950                      # expect a sha256 mismatch — see F4
dsa fetch AFE7950 --accept-new-revision
dsa check-revisions --all
dsa audit --all
```

**Expect the first fetch of every TI part to report a hash mismatch.** That is
correct, not a bug: TI regenerates a datasheet's "PACKAGE MATERIALS
INFORMATION" page with the current date on every download, so the bytes differ
daily while the revision identifier does not (**F4**). The warning is written
to say so explicitly.

---

## Known findings — what you will hit, and what it means

Full evidence in `Reports/FINDINGS_2026-08-18.md`.

| ID | Severity | Symptom | Verdict |
|---|---|---|---|
| F1 | HIGH | `verify` without `--pdf` reports 12% on a 100% corpus | Real defect — disabled ≠ failed |
| F12 | HIGH | Multi-document part scores 2/12 with the wrong `--pdf` | Real defect — resolve PDF per record |
| F2 | HIGH | TI build dies with a raw traceback on a 404 | Real defect — breaches invariant 7 |
| F4 | HIGH | TI sha256 changes daily | Upstream behaviour — design must not read it as a new revision |
| F8 | HIGH | `sniff_revision` → `SYSREFOUT0` for LMX1204 | Real defect — regex too loose |
| F3 | MED | `dsa batch` has no `--vendor` override | Gap — blocks offline batch of TI parts |
| F6 | MED | LM741 pin table not extracted, no reason recorded | Real defect — and the message points at a `dsa status` that carries nothing |
| F10 | MED | Two revision parsers disagree | Duplication — should share one |
| F11 | LOW | `TJ` matches "Total Jitter" in a thermal question | Alias ladder imprecision |
| F7 | INFO | Every `pdf_layout` spec grades `low` | Confidence tracks backend, as designed |
| F9 | INFO | ADI unreachable; TI fetchable by part number | Environment constraint |

F4 and F8 are already written into `.scratch/reach-and-trust/issues/02-revision-awareness.md`
as blocking criteria with the measured evidence, so the Phase 7 workflow fixes
them rather than you.

---

## Scoring

The system passes if:

- [ ] `pytest` green, `ruff` clean
- [ ] all seven parts build and verify at 100% **with the correct `--pdf`**
- [ ] every answer you spot-check against the printed page is correct
- [ ] every question it cannot answer is **declined**, not guessed
- [ ] MCP registers in your client and answers questions 1–4
- [ ] question 5 is declined

It does **not** pass merely because the tests are green. The objective
function is the golden Q&A and your own spot-checks against printed pages.

---

## If something fails

1. Re-run with the exact command from this file — most surprises are F1
   (missing `--pdf`) or F12 (wrong `--pdf` on a multi-document part).
2. `dsa status` shows configuration, detected parts, and recorded reasons.
3. `KNOWN_SHORTCOMINGS.md` records measured limits with the test that measures
   them; check there before filing something as new.
4. For a build failure, re-run with `--vendor unknown` to force the offline
   `pdf_layout` floor and see whether it is a backend-routing problem.
