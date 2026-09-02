# datasheet-analyzer

Turn big IC datasheets into a **token-efficient, citation-verified markdown
corpus** that AI agents navigate with an index file + grep/read — instead of
loading tens of thousands of raw-PDF tokens into context.

Two reference parts are built and verified in this repo:

| | AFE7950 (SBASA41E) | AFE7953 (SBASAN1A) |
|---|---|---|
| PDF | 146 pages | 134 pages |
| Sections | 39 | 39 |
| Tables (atomic) | 15 | 14 |
| Figures → image files | 514 | 492 |
| `specs.json` records | 619 | 536 |
| Corpus tokens | 46,073 | 39,033 |
| INDEX.md tokens | 2,469 / 3,000 | 2,522 / 3,000 |

A golden Q&A set (19 questions, answers hand-verified against the printed
PDF) passes at ~2.5k tokens for parametric lookups, ~4.3k average for direct
section reads, and ~4k for plot lookups — vs ~46k for a full-text dump —
with every answer traceable to a printed page number.

## What it does

Pipeline: `PDF → acquire → extract → structure → enrich → publish → eval`

- **Extract** — TI datasheets use TI's document-viewer HTML (real tables,
  MathML, footnotes — no OCR, no hallucination); every other vendor and
  era routes to a vendor-neutral offline layout engine (`pdf_layout`,
  PyMuPDF-only, zero vendor assumptions — tables, specs, plots, page
  citations straight from the PDF). Register maps route to `pdf_layout`
  too — their tables *are* the document — while a degraded `pdf_text`
  backend handles the prose companions, errata / app notes (paragraphs
  only).
- **Structure** — HTML tables become atomic, span-expanded blocks with their
  conditions preamble + footnotes attached; sections get page ranges from the
  PDF's printed TOC; tables get exact pinned pages where possible.
- **Enrich** — an `INDEX.md` under a hard token budget (default 3,000). An
  LLM writes only the section descriptions (optional); all corpus content is
  verbatim-extracted. Without an API key, descriptions are deterministic.
- **Publish** — per-section markdown with CSV twins of every table,
  `specs.json`, `plots.json` + `figures/` image files, `pins.json` and
  `registers.json` where the document prints those tables, a
  `search_index.json` BM25 index per document, and `manifest.json`.
- **Derive** — task-shaped views computed from what was published: design
  cards (power / thermal / interface / limits) and cross-part comparison.
  **No model appears anywhere in a derived value's path**: every field is a
  verbatim copy, a documented pure function of one, or a lexicon label, and
  carries the record id, the printed page and the rule that produced it
  (`AGENTS.md` invariant 8).
- **Eval** — `dsa verify` runs the golden Q&A: every answer must appear in the
  corpus section covering the cited page **and** in the cited PDF page itself,
  plus deterministic spec-query and plot-query checks.

## Install

Requires Python ≥ 3.10 and [uv](https://docs.astral.sh/uv/). Commands below
are for Git Bash on Windows:

```bash
uv venv --python 3.10 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
source .venv/Scripts/activate   # puts `dsa` and `python` on PATH
```

If you skip the activation line, call `.venv/Scripts/dsa.exe` and
`.venv/Scripts/python.exe` directly — all commands below work either way.

Optional: put `ANTHROPIC_API_KEY=...` in a `.env` file to enable LLM-written
INDEX descriptions (one batched call per build; falls back safely without it),
and the chat agent behind `dsa serve`.

> **Check that your `.env` is not tracked.** `.gitignore` lists it, but git
> keeps tracking a file it already tracks, so a repo that committed one before
> the rule existed is still committing your key on every change. Run
> `git ls-files --error-unmatch .env`; if that *succeeds*, untrack it with
> `git rm --cached .env` and commit. The file stays on disk — only the index
> entry goes. (Rotate the key too if it was ever pushed.)

Two optional extras, each kept out of the core install so a plain one stays
lean. Everything else works without either:

```bash
# the MCP SDK, for `dsa serve --mcp`
uv pip install --python .venv/Scripts/python.exe -e ".[mcp]"

# FastAPI + uvicorn + sse-starlette, for the local workbench `dsa serve`
uv pip install --python .venv/Scripts/python.exe -e ".[web]"
```

See [Use it from an agent](#use-it-from-an-agent-mcp) and
[Use it in a browser](#use-it-in-a-browser-dsa-serve). Running either command
without its extra prints an install hint, not a traceback.

## Quickstart

```bash
# Build the corpus (first run fetches TI pages + plot images, cached forever)
dsa build afe7950.pdf --part AFE7950

# Verify against the golden Q&A set (citations + page truth)
dsa verify --part AFE7950 --pdf afe7950.pdf

# Also verify deterministic spec lookups
dsa verify --part AFE7950 --pdf afe7950.pdf --specs

# Second reference part, same build path
dsa build afe7953.pdf --part AFE7953
dsa verify --part AFE7953 --pdf afe7953.pdf --specs
# (per-part goldens live in tests/fixtures/golden_qa_<PART>.yaml; `dsa verify`
# resolves a part's own benchmark and fails loudly when it is missing, rather
# than running another part's)

# Non-TI part: vendor detected and pinned from page-1 brand text, built
# and verified fully offline through the pdf_layout floor
dsa build ad9081.pdf --part AD9081 --vendor adi         # ADI part, explicit pin
dsa verify --part AD9081 --pdf tests/fixtures/pdf/ad9081.pdf --specs
# (A brand-less PDF pins --vendor unknown instead — see the LM741 gate fixture)

# One invocation builds every PDF in a directory as its own part corpus
# (part = uppercase filename stem; flat scan; failing jobs are isolated;
#  unchanged parts skipped; parallel with --workers N, default 4)
dsa batch datasheets/
```

Useful flags: `build --no-cache` (re-extract), `build --no-llm` (deterministic
descriptions even with a key set); `batch` accepts the same `--no-cache` /
`--no-llm` options plus `--force` (rebuild even when up to date) and
`--workers N` (parallel jobs; `DSA_BATCH_WORKERS` env default, 1 = serial).

## Using the corpus

### Ask one question, get one cited answer (`dsa ask`)

```bash
dsa ask --part AFE7950 "max junction temperature" --budget 3000
## AFE7950 — SBASA41E (datasheet-c1b4663b)
### Answer
TJ  Junction temperature: 150 °C (max) — §4.1, p.4  [high]
TJ  Operating Junction Temperature: 110(1) °C (max) — §4.3, p.6  [high]
TJ  Maximum Operating Junction Temperature: 125 °C (min) — §4.3, p.6  [high]
TJ  Total Jitter Tolerance: 0.42 UI (max) — §4.8, p.20  [high]
### Supporting excerpt  (§4.1 Absolute Maximum Ratings, p.4)
## Unnumbered table > **Test conditions:** over operating free-air temperature
range (unless otherwise noted)(1) | | | MIN | MAX | UNIT | … | Supply Voltage
Range | DVDD0P9, VDDT0P9 | –0.3 | 1.2 | V | …
### Verify
Printed page 4 of afe7950.pdf.  Confidence: high.

dsa ask --part QPA1003P "where is the functional block diagram?" --json
```

That transcript is the command's own output on a freshly built AFE7950 corpus
(190 tokens), wrapped for this page with the middle of the excerpt row elided
at `…`. It is worth reading against the plan, which illustrated this question
with `105 °C — §4.3, p.6`: the AFE7950 prints its junction-temperature limit
in §4.1 Absolute Maximum Ratings on page 4, and the pack cites what the
datasheet prints, never what the example said. (A corpus built before
per-record grading landed answers the same rows graded `unknown` until it is
rebuilt.)

One call instead of three or four. Routing is **deterministic — no LLM is in
the path** — classified by feature hits in order:

| Feature in the question | Route |
|---|---|
| the alias ladder resolves it to spec records | `spec` |
| plot vocabulary (`plot`, `curve`, `vs`, `versus`, `graph`, `figure`, `diagram`) **and** a figure whose caption uses the question's words | `plot` |
| anything the full-text index ranks | `search` |
| nothing, and this corpus has no current full-text index | `unavailable` — rebuild to enable search (exit 2, as `dsa search` does) |
| nothing | `none` — an explicit no-match plus nearest candidates, never a guess |

The `unavailable` route is why an empty full-text result is never reported as
an answer: `search()` returns nothing both when nothing matched and when there
was no index to match against, and only the first of those is a statement
about the datasheet.

The pack is filled greedily against `--budget` (default `DSA_ASK_BUDGET`,
4000 tokens) over a **reserved tail** — the header, the first answer line and
the verify footer — so a budget can only ever cost extra rows and excerpt
prose. **Citations are never the truncated part**, and any truncation prints a
notice naming `--budget`. `--json` emits a shape with a declared schema
(`retrieve.pack.ANSWER_PACK_SCHEMA`).

### Ask a parametric question (cheapest: ~2.5k tokens)

```bash
dsa query --part AFE7950 --symbol DACRES
# DAC resolution (DACRES): 14 bits — §4.5, p.7 [table 0 row 0] [via symbol · high]

dsa query --part AFE7953 --symbol DACRES
dsa query --part AFE7950 --section 4.10 --name SYSREF
```

You do not have to know the datasheet's symbol. `--symbol` / `--name` take a
designer's words and run a resolution ladder — exact symbol, then alias phrase,
then alias prefix family, then substring, then a token-overlap fuzzy match —
and every answer reports the rung that found it:

```bash
dsa query --part AFE7950 --name "junction temperature"
# Junction temperature (TJ): 150 °C — §4.1, p.4 … [via alias:junction temperature · high]

dsa query --part AFE7950 --symbol IDD        # the whole IVDD* supply-current family
dsa query --part AFE7950 --name "junction temperature" --json
```

The synonyms live in `src/datasheet_analyzer/registry/aliases.yaml`; adding one
is a YAML edit, never a code change. `--section` still AND-s with the term.
A query that matches nothing says so and lists the nearest candidates in the
corpus — it never guesses. Answers carry verbatim values, units, conditions,
footnote markers, and page cites.

### Trust an answer: the confidence grade

Every spec and plot record is graded when the corpus is built, and the grade is
printed after the rung (`[via symbol · high]`) and returned in `--json`:

| Grade | What it means |
|---|---|
| `high` | pinned to an exact printed page, reconstructed from the table's own declared columns, and the row prints a value |
| `medium` | the page is a section range, or the row printed no value at all |
| `low` | the grid was rescued by the layout engine's retry ladder, or a value's unit is missing where its alias family expects one |
| `unknown` | ungraded — a corpus built before grading existed; rebuild it |

`low` is not "wrong": it is "open the printed page before you quote this". The
mix per part is recorded in `manifest.json` and printed by `dsa status`.

### Search the text (every hit already cited)

```bash
dsa search --part AFE7950 "sysref setup"
# 1. §4.10 SYSREF Timing — §4.10, p.31-33 [score 8.41 · via fulltext]
#    SYSREF setup time must be met for deterministic latency. …

dsa search --part AFE7950 "thermal pad" --limit 3
dsa search --part AFE7950 "dBc/Hz" --json
```

Ranked with BM25 over a `search_index.json` built at publish — no ripgrep, no
subprocess, no network. Every hit carries the section's page range **from the
manifest**, so a caller never attributes a page itself, plus a ±240-char
snippet grown to sentence boundaries.

The tokenizer is built for datasheets: no stemming, ASCII-only lowercasing (so
`Ω` U+2126 and `Ω` U+03A9 stay distinct, as does `RθJA`), and compound unit
strings index whole and split (`dBc/Hz` finds `dbc/hz`, `dbc` or `hz`). Bare
numbers are deliberately *not* indexed — `dsa query` is the exact-value path,
and a bare `105` ranks nothing. A corpus built before search existed says
"rebuild to enable search" instead of returning an empty result.

### Find a plot

```bash
dsa plots --part AFE7950 --q "Output Fullscale"
dsa plots --part AFE7950 --q "Gain Error" --section 4.12.1
dsa plots --part AFE7950 --tag "tx,800mhz"
dsa plots --part AFE7950 --q "Output Fullscale" --json
```

Returns matching `plots.json` records (caption, conditions, section, page,
confidence, and the image file path under `figures/`) for an agent to open.

### Look up a pin (`dsa pins`)

```bash
dsa pins --part AD9081 --type power        # every supply pin, by lexicon label
dsa pins --part AD9081 --q VDD             # designator, name or description
dsa pins --part LMX1204 --type ground --json
```

The table a designer lives inside during schematic capture. `A1, A2, B1` and
`A1–A4` expand into four records that share name/type/description and are
each individually citable. The type (`power | ground | analog | digital |
clock | rf | nc | reserved | unknown`) comes from
`registry/pin_types.yaml`, and each record names the lexicon entry that
produced it in `type_evidence`. A part whose datasheet prints no readable pin
table publishes **no** `pins.json` and says so — that is different from a part
with no pins.

### Look up a register (`dsa regs`)

```bash
dsa regs --part LMX1204 --addr 0x11        # by value: 0x11, 0x11, 17 are one question
dsa regs --part LMX1204 --name R17
dsa regs --part LMX1204 --json
```

Address / name / reset / access, each cited to the page that printed it.
A column the map never printed stays empty and says so — a blank reset read
as `0x00` is what breaks a bring-up sequence. Per-register **bit fields** are
published for every register whose field-description table reads whole:
`--field NCO` finds them by name, and each field carries its printed bit
range, access and reset. A field set is accepted whole or refused whole, so a
register whose table could not be read keeps an empty `fields` list and is
named in the set's warnings — and a part that publishes no bit field at all
has `--field` say so out loud rather than returning an empty result that
reads as "this register has no fields".

### Get a design card (`dsa card`)

```bash
dsa card --part AFE7950 --card power       # rails: voltage min/typ/max, current
dsa card --part AFE7950 --card thermal     # RθJA, RθJC, ΨJT, TJ, TA, Tstg
dsa card --part AD9081  --card interface   # JESD204B/C, lane count, lane rate
dsa card --part AFE7950 --card limits      # abs-max vs recommended, with margin
```

A task-shaped view over records that already exist: "what rails does this need
and how much current?" is one call instead of a five-section scavenger hunt.
Every value carries the record it was copied from, the printed page, and the
named rule that produced it; a field that could not be filled is null and says
why. The `limits` card computes margin **only where both sides parsed** and
flags any parameter whose recommended maximum equals its absolute maximum —
a design hazard that is invisible when the two tables are read pages apart.
Cards are written to `parts/<PART>/cards/<kind>.json` and `.md`, and
`DSA_CARD_VERSION` participates in the publish cache key, so changing a
derivation rule regenerates them instead of leaving stale numbers behind.

### Compare two parts (`dsa compare`)

```bash
dsa compare AFE7950 AFE7953 --symbol TJ
dsa compare AFE7950 AFE7953 --card power
```

Rows are aligned by alias-resolved symbol. Each row shows both verbatim values
with both page cites, and an SI delta **only where both sides parsed**. A
parameter one part prints and the other does not is reported as such, never
silently dropped, and the unparsed population is named rather than hidden.

### Read content by section

Load `parts/AFE7950/INDEX.md` first — it maps every section to its file and
page range within its token budget. Then grep/read the section files:

```
parts/AFE7950/
├── INDEX.md               # always-loadable index (hard budget, 3000 tok)
├── AGENT.md               # the retrieval protocol, shipped with the corpus (~1.4k tok)
├── sources.json           # doc inventory: sha256, type, revision, nda flag
├── manifest.json          # machine-readable section map + stats
└── docs/datasheet-<hash8>/
    ├── sections/*.md      # atomic; `<!-- source: <doc> p.N[-M] -->` header
    ├── tables/*.csv       # machine-readable twins of each section table
    ├── figures/           # plot image files referenced by plots.json
    ├── specs.json         # parametric spec records (symbol/name/conditions/min/typ/max/unit/page)
    ├── plots.json         # searchable plot catalog + file map + axis catalog
    ├── pins.json          # pin records, one per designator (when a pin table was read)
    ├── registers.json     # register summary records (when a register map was read)
    └── search_index.json  # BM25 index over sections/*.md (what `dsa search` ranks)
└── cards/                 # derived design cards: power|thermal|interface|limits
    ├── power.json         # every value carries source + page + derivation
    └── power.md           # the same card rendered, a citation on every row
```

`cards/` hangs off the **part**, not a document: a card composes records from
every document registered for the part.

Every answer should quote values **with units** and cite `p.N` from the
section header.

### The protocol ships with the corpus (`AGENT.md`)

`INDEX.md` is the map; `AGENT.md` beside it is how to read it. It is written
at publish for every part and every project, and it is short enough
(~1.8k tokens, ceiling 2,200) to load next to the index every time:

- the rules — index first, never bulk-read, prefer `ask`, quote units, cite
  `p.N`, check the confidence grade, and on `low` send the designer to the
  printed page;
- both access paths, the `dsa` CLI and the MCP tools, each with a worked
  example scoped to that part or project;
- the confidence table: what each grade means and what to do about it;
- the verbs beyond answering — `fetch`, `check-revisions`, `diff-rev`, `audit`,
  `family` — and the one rule that goes with them: never run a network verb to
  answer a question. A stale corpus is something to report, not to go and fix
  mid-answer.

The same text is checked into this repo as the Claude Code skill
`.claude/skills/datasheet-corpus/SKILL.md`, so an agent working in this
workspace adopts the protocol before it opens anything. Both are rendered
from `src/datasheet_analyzer/protocol.py` — edit that, then run
`python scripts/write_skill.py`; a test fails if the two ever disagree.

### Group parts into a design (`dsa project`)

A **project** is the noun above `part`: an explicit list of parts plus the
free text that joins them, with one always-loadable `PROJECT_INDEX.md` for
the whole board.

```bash
dsa project new rf-frontend --interfaces "AFE7950 TX -> HMC520A DSA -> board edge"
dsa project add rf-frontend AFE7950 --role "quad RF transceiver"
dsa project add rf-frontend HMC520A AD9081
dsa project build rf-frontend        # writes PROJECT_INDEX.md under its budget
dsa project status                   # every project and its parts
```

```
projects/rf-frontend/
├── project.json        # name, parts[] (+ role), interfaces, notes, timestamps
├── PROJECT_INDEX.md    # always-loadable, hard budget (4000 tok)
└── AGENT.md            # the same retrieval protocol, scoped to the design
```

Membership is explicit — no BOM or netlist parsing. A part with no built
corpus is refused with the build command that would fix it, so a project
never points at nothing. `project.json` is meant to be hand-edited: the
`interfaces` note and each part's `role` are yours, and a rebuild never
rewrites them.

Then ask the whole design one question. Every hit is labelled with the part
it came from, and a question two parts answer returns both:

```bash
dsa ask --project rf-frontend "does anything here need a 1.8 V rail?"
dsa search --project rf-frontend "sysref"
dsa query  --project rf-frontend --name "junction temperature"
dsa plots  --project rf-frontend --q "gain"
```

```
## rf-frontend — project (AFE7950, HMC520A, AD9081)
### Answer
[AFE7950] VDD1P8  1.8V supply: 1.75 V (min) — §4.3, p.6  [high]
[AD9081] VDD1P8  1.8 V supply: 1.75 V (min) — §Power Supply, p.9  [medium]
### Verify
AFE7950 — Printed page 6 of afe7950.pdf.  Confidence: high.
```

`--part`, `--project` and `--family` (below) are mutually exclusive, and one of
them is required.

### Answer a whole series at once (`dsa family`)

A **project** is parts somebody put on one board. A **family** is one device
published in several options — AFE7950 and AFE7953 are one vendor's one document
template, quad TX/RX and dual. Reading both datasheets means reading the same
thirty-odd sections twice to find the handful that moved, so a family index
lists every identical section **once** and tabulates only the differences.

```bash
dsa family list                    # what is declared, and what is only proposed
dsa family suggest                 # PROPOSE groupings from built corpora
dsa family confirm AFE795x         # the human act; --dry-run prints and writes nothing
dsa family build AFE795x           # families/AFE795x/FAMILY_INDEX.md + family.json
dsa ask --family AFE795x "maximum junction temperature"
```

```
## AFE795x — family (AFE7950, AFE7953)
### Answer
TJ  Junction temperature: 150 °C (max) — §4.1, p.4  [high]  [common to AFE7950, AFE7953]
### Verify
AFE7950 — Printed page 4 of afe7950.pdf.  Confidence: high.
```

**Membership is declared, never inferred.** This is the rule the whole feature
turns on. A family index says *"this section is identical in every member — read
it once"*, and a wrong member makes that sentence a lie the reader cannot see.
So `registry/families.yaml` is the only file `dsa family build` reads;
`dsa family suggest` writes a different file (`families.candidate.yaml`) whose
every entry carries `confirmed: false`; and the loader refuses that file **by
name**, before parsing, so a proposal cannot be promoted by a typo. Only
`dsa family confirm` moves an entry across.

**What is "the same" is decided by reading, not by resemblance.** A section is
shared only when every member prints it under the same title with byte-identical
body text (the `<!-- source: -->` provenance line and the `# N Title` heading
stripped first, because those name each member's own revision and section
number). A spec row aligns on the row **as printed** inside the section as
printed — symbol, name and conditions, character for character — because an
alias key would fold `IVDD1P8` and `IVDD1P2` onto one bucket and then refuse
them both. A pin, a register reset and a bit range are quoted on both sides and
**never scored**: a signed difference between two bit patterns is a number that
means nothing and looks like it means something.

Measured on this repository's AFE7950 + AFE7953 corpora: 39 sections, 14 of them
identical in both and listed once (3664 tokens counted once instead of twice);
763 spec rows aligned, 379 printing the same values everywhere and counted
rather than tabulated, 384 in the delta table, 461 refusals listed with their
printed values. `FAMILY_INDEX.md` renders to **2290 tokens** under its 4000
budget against **4758** for the two members' own `INDEX.md` files — a ratio of
**0.481** — and `family.json` beside it always holds every row the budget capped.

Neither AFE795x member publishes a readable pin table or register map, and the
index says so in those words rather than printing an empty table: *"no member
publishes pins … this family states nothing about pins, which is not the same as
stating they agree."*

### Use it from an agent (MCP)

`dsa serve --mcp` exposes the same retrieval core as MCP tools over **local
stdio** — no HTTP, no auth, no ports. The SDK is an optional extra, so install
it once:

```bash
uv pip install --python .venv/Scripts/python.exe -e ".[mcp]"
# or: pip install -e ".[mcp]"
dsa serve --mcp        # speaks MCP on stdin/stdout; a client launches this
```

Register it with any MCP client (`mcp.json` / `claude_desktop_config.json` /
Cursor's MCP settings). `cwd` is what makes `parts/` and `projects/`
resolvable, or set `DSA_PARTS_DIR` / `DSA_PROJECTS_DIR` to absolute paths:

```json
{
  "mcpServers": {
    "datasheets": {
      "command": "C:/path/to/repo/.venv/Scripts/dsa.exe",
      "args": ["serve", "--mcp"],
      "cwd": "C:/path/to/repo",
      "env": { "DSA_MCP_MAX_TOKENS": "6000" }
    }
  }
}
```

On macOS/Linux the command is `/path/to/repo/.venv/bin/dsa`.

| Tool | Scope | Returns |
|---|---|---|
| `list_parts` | — | built parts: revision, vendor, counts, confidence mix |
| `list_projects` | — | projects, their members, whether each is built |
| `list_families` | — | declared families, their members, whether each is built |
| `get_index` | part | the part's `INDEX.md` |
| `get_family_index` | family | the series' `FAMILY_INDEX.md`, derived live |
| `search` | part, project or family | BM25 hits, each cited by construction |
| `find_spec` | part, project or family | spec records through the alias ladder |
| `read_section` | part | one section verbatim, bounded by `max_tokens` |
| `find_plots` | part, project or family | the plot catalog, filtered by text, section, tags **or axis** |
| `get_figure` | part | one figure **as an image content block** |
| `ask` | part, project or family | one cited, budget-bounded answer pack |
| `find_pin` | part or project | pins by designator, name, description or type |
| `find_register` | part or project | registers by name, address or bit field |
| `get_card` | part | one design card (power / thermal / interface / limits) |
| `compare_parts` | named parts | two or more parts aligned on one parameter or card |
| `get_audit` | part | thirteen graded readings and the letter they average to |

`find_plots` takes `x_label` / `y_label` (substrings of the printed axis
titles) and `near_x` / `near_y` (a quantity the printed axis range must
cover, SI prefixes converted on both sides), so an agent narrows hundreds of
figures to the one worth opening before spending a vision token. A figure
whose axes could not be read is not a match — `axes.confidence` says so.

`list_families`, `get_family_index` and `get_audit` are phase 7's:
`list_projects` and `get_index` one noun across, plus the trust call that
grades a corpus *before* an agent answers from it. The family index is derived
**live** from the members' records rather than read off `families/<NAME>/`, so
a client never has to know whether `dsa family build` has run.

**A family is a scope, not just a catalog entry.** `search`, `find_spec`,
`find_plots` and `ask` each take a `family` beside `part` and `project`, and
name exactly one of the three. On the CLI all seven scoped verbs resolve a
family — `query`, `search`, `plots`, `ask`, and since 2026-09-02 `pins`,
`regs` and `card`, which used to accept the flag and refuse it; `find_pin` and
`find_register` over MCP have yet to follow (KNOWN_SHORTCOMINGS.md).
The envelope's `scope` object carries all three names, so every response says
which scope answered it; a family answer that reported `{part: "",
project: ""}` would be indistinguishable from a call that named no corpus at
all. The extra key costs 4 tokens on a 65-token envelope, 0.067 % of the
6000-token cap.

Only `ask` folds. A finding every member printed identically, character for
character, comes back once, cited to the reference member and labelled with
the members it is common to. `search`, `find_spec` and `find_plots` return one
row per member, because a record list has nowhere to say whose page a folded
row came from — measured on AFE795x, 45.7 % of the spec rows common to both
members print on different pages. The aligned, folded view of a series is
`get_family_index`, which prints both operands' pages on every delta.

`find_pin`, `find_register`, `get_card` and `compare_parts` are the **derived**
artifacts of phase 6, and they carry one extra rule: nothing on them is
generated. Every value is printed text
copied verbatim, a number computed from it by a named pure function, or a
label from a checked-in lexicon, and each ships with the record and printed
page it came from (`AGENTS.md` invariant 8, `docs/adr/0007-…`). A field that
could not be filled is null and says why.

Resources `dsa://part/<PART>/INDEX.md` and
`dsa://project/<NAME>/PROJECT_INDEX.md` let a client pin an index into context
without spending a tool call.

Every response carries citations and confidence, declares its own JSON schema
(shipped in each tool's `_meta.response_schema`), and is capped at
`DSA_MCP_MAX_TOKENS` (default 6000) — a truncated response **says so** and
names the setting. `get_figure`'s image block is atomic and is not trimmed:
truncating base64 makes a corrupt PNG, not a shorter one, so the cap governs
the JSON that cites it and the payload reports the image's byte size.

### Use it in a browser (`dsa serve`)

Everything above is the product; the workbench is a **third front end** onto
it, beside the CLI and the MCP server. It adds no retrieval of its own — same
`retrieve/` core, same `Citation`, same confidence grades — and the CLI remains
the surface the golden Q&A and the test suite exercise. What it adds is the one
step a terminal cannot make cheap: **clicking a citation and landing on the
printed page it names, with the cited block highlighted.**

```bash
uv pip install --python .venv/Scripts/python.exe -e ".[web]"
npm --prefix web install && npm --prefix web run build   # builds web/dist, served by dsa serve
dsa serve
# datasheet workbench: http://127.0.0.1:8765
```

Local and single-user by construction: it binds `127.0.0.1` (override with
`DSA_SERVE_HOST` / `DSA_SERVE_PORT`), there is no authentication, and there is
nothing to log into. The chat agent uses `ANTHROPIC_API_KEY` from your `.env`
and `DSA_CHAT_MODEL`; the rest of the app — analyze, review, library, PDF,
citations — works with no key at all.

The path through it is four steps.

**1. Analyze.** Point at a directory of PDFs and start. Every file in it is
analyzed in the background with live per-part progress, so a 40-PDF shelf can
be left running. One bad file fails its own job and leaves the rest going, and
re-analyzing an unchanged directory is near-free — the same hash-gated skip
`dsa batch` uses. Parts that finish are askable while the others are still
building.

**2. Review.** Before anything is built, a review screen shows what was
inferred from each document: its **part number**, read from the title block
rather than the filename (so `sbas123e.pdf` proposes `AFE7950`, not
`SBAS123E`), and its **applicability** — the set of parts the document is
about. A datasheet names one part; an application note may name a family
prefix like `AFE79xx`; a layout-guidelines note may apply to everything. A
document that cannot be classified defaults to *all parts*, which is the
honest, non-lossy answer rather than a wrong owner. Every proposal is editable
here, and correctable later from the Library screen. Nothing is inferred that
you did not see.

This is why one PDF no longer means one part: a register map, an errata and a
datasheet all apply to the same device, so a question whose answer is in the
register map and whose context is in the datasheet can finally be asked at all
(`docs/adr/0005-documents-apply-to-parts.md`). Your own **labels**
(`reviewed`, `thermal`, `jesd204`) attach to a document on the same screen and
are never touched by a rebuild.

**3. Ask.** Type the question without choosing a part first. The scope is
resolved for you — to exactly one part or one project — and shown as an
editable control on the answer, so what the answer was drawn from is always on
screen. An ambiguous question asks which device you meant instead of guessing,
and there is no "everything" scope to fall back to
(`docs/adr/0006-auto-resolved-scope.md`). Answers stream token by token and
carry the same citations, match reasons and confidence grades the CLI prints.

The agent behind that box has twelve tools — the same corpus reads the CLI and
MCP make, plus `get_audit`, which grades the corpus before the answer quotes
it, and `list_families` / `get_family_index` for a declared series. **None of
them takes a part, project or family name.** The scope is resolved once, shown
to you, and injected into every tool, so the agent has no argument through
which it could answer from a device you were not shown — which is why
`get_family_index` here maps the series *this* conversation is about, although
its MCP twin takes a family name.

**4. Verify.** Click a citation. The PDF opens in the pane beside the answer,
at that page, with the cited block highlighted. The highlight is found on
demand by searching the printed page for the record's own text — nothing is
precomputed, and no extraction cache is invalidated to support it. **A block
that cannot be located opens the page with no highlight**, because a box around
the wrong row is worse than no box, exactly as an unpinned page stays honestly
blank rather than guessed.

Conversations are saved and reloadable, and an answer plus its citations
exports to markdown for a design review — or to a
`tests/fixtures/golden_qa_<PART>.yaml` entry, which is how a fact you verified
by hand becomes a regression test.

For development, `npm --prefix web run dev` serves the UI on `:5173` and
proxies `/api` to `dsa serve` on `:8765`, so both halves reload independently.
`web/dist/` is gitignored; so are `library/` (the document inventory and your
labels), `sessions/` (saved conversations) and `families/` (a family index is
derived in full from tracked records, so it is a cache — the *declaration* it
is built from, `registry/families.yaml`, is what this repo tracks).

### Add companion documents

```bash
dsa add-doc register_map.pdf --part AFE7950 --type register_map [--nda]
dsa build afe7950.pdf --part AFE7950   # rebuild picks it up
```

Types: `register_map`, `errata`, `app_note`, `datasheet`. A `register_map`
extracts with the same `pdf_layout` engine a datasheet does, so its register
tables are read as tables and answer `dsa regs`; the prose companions
(`errata`, `app_note`) extract with the honest `pdf_text` backend (paragraphs
only; no trusted tables, no `specs.json`). All of them join the same
`INDEX.md`.

### Onboard a part from the registry (`dsa fetch`)

```bash
dsa fetch AFE7950                       # resolve -> download -> verify sha256 -> register
dsa fetch --url <URL> --part AD9081     # the growth path: records the URL for next time
dsa fetch --project rf-frontend         # everything the design is missing; skips what is present
dsa fetch AFE7950 --accept-new-revision # after reading a hash-mismatch warning
```

`registry/datasheets.yaml` is the checked-in answer to "where does this part's
PDF come from". **This tool never guesses a datasheet URL and never falls back
to a search** — a plausible vendor URL that resolves to the wrong document puts
the wrong datasheet in front of a designer with a citation that looks exactly
as trustworthy as a correct one. A part the registry does not know is an error
naming `--url`; an entry with no URL says *why* it has none.

`dsa fetch` is the only command that may reach the network for a document.
`dsa build` acquires nothing. A sha256 mismatch **stops** without writing or
registering anything, and names its likely cause from the *parsed revision*
rather than from the hash — a vendor that regenerates a package-materials
addendum with the current date changes the bytes daily while the revision
identifier stays put, so "the hash moved" is not evidence of a new revision.

### Ask upstream whether a corpus is still current (`dsa check-revisions`)

```bash
dsa check-revisions AFE7950             # one part
dsa check-revisions --all --json        # the fleet, machine-readable
```

Explicit, opt-in, network — and the only thing that writes a freshness state.
Nothing on the build or answer path calls it, so a lookup never depends on a
vendor's web server, and the download goes through an **uncached** fetcher
because a freshness check served from a cache is not a freshness check.

Three states, and the default is the one that protects you:

| state | means |
|---|---|
| `current` | a check ran and the upstream revision identifier matched |
| `stale` | a check ran and upstream reports a **different** revision |
| `unknown` | nobody has checked, or the check could not complete |

`unknown` is **not** `current`, and every surface says so: the `INDEX.md`
banner, `dsa status`, the `dsa audit` metric and every answer pack's footer.
A check that cannot complete records only *why* and leaves the state exactly
as it was, so a failed check can never clear a warning.

### Compare two revisions of one part (`dsa diff-rev`)

```bash
dsa diff-rev --part AFE7950 --from "Rev. D" --to "Rev. E"   # writes REVISION_DIFF.md
dsa diff-rev --part AFE7950 --json --no-write               # print it, write nothing
```

What moved between two revisions the part holds: sections added, removed and
retitled; spec rows whose printed values changed, with an SI delta where the
two are comparable; pins and registers appearing, disappearing or renamed.
Both sides are cited, always — a diff you cannot open both pages of is not a
finding.

`--from` / `--to` accept a `--rev` label, a printed revision identifier, or a
document directory; omit both and the part must hold exactly two. **No part in
this repo does.** A part builds one datasheet, so the second side is either a
companion document filed with `dsa add-doc` or the other revision built under
its own part number — for which `dsa compare` is the right scope. Asked for a
diff it cannot make, `dsa diff-rev` says which document the part holds and
names both ways to give it a second:

```text
diff-rev error: AFE7950 holds one built document (datasheet-c1b4663b); a
revision diff needs two.
```

### Errata, cross-linked to what they invalidate

An errata document joins a part the way any companion does
(`dsa add-doc lm741_errata.pdf --part LM741 --type errata`). What a rebuild
then adds is the link: each item of that document is matched against the
sections, spec rows, pins and registers the part published, and the result is
written beside `INDEX.md`.

```
parts/LM741/
  errata_links.json    every item, its targets, and what each one matched on
  ERRATA.md            the same thing for a person to read
```

Every rule is an **exact** comparison against an identifier the document
printed - a cued section number (`Section 6.1`), a printed table caption, a
symbol, an alias phrase, a pin name, a cued pin designator (`ball A1`), a
register name, a parsed register address. There is deliberately no
prose-similarity rule and no threshold to loosen: an erratum and a datasheet
section are written about the same device in the same words, so *resemblance*
between them is the null hypothesis, not evidence, and a link produced that way
would put a warning banner on a page the erratum was never about.

Three things follow, and all three are asserted rather than documented:

- **Nothing is lost.** An item no rule could place is published under
  `## Unlinked errata`, in full. The report opens with an arithmetic a reader
  can check - *N items: X linked, Y unlinked* - so nothing can go missing
  between the errata document and the file.
- **Every link says what it matched on**, so a wrong link is diagnosable from
  the file instead of by re-reading the PDF.
- **The warning follows the value.** A section an erratum names carries a
  banner in its published markdown (inserted before the search index is built,
  so what is searchable stays what is readable), and `dsa ask` prints the
  erratum on the answer row itself - dropped only if that row is dropped,
  exactly like its citation.

A part that registers no errata document gets **no file at all**. That is the
point: an empty `errata_links.json` would read as "no known issues", which is a
claim this corpus has no evidence for. See `KNOWN_SHORTCOMINGS.md` for what has
and has not been confirmed against a real vendor errata sheet.

### Grade a corpus before you trust it (`dsa audit`)

`extraction_stats` tells the *builder* how a build went. `dsa audit` tells the
*reader* whether to trust what came out of it — thirteen readings taken off
artifacts the corpus already publishes, each graded A–F against
`src/datasheet_analyzer/registry/audit_rubric.yaml`, averaged by weight into
one letter and one sentence.

```bash
dsa audit AD9081              # one part's scorecard
dsa audit --all               # the fleet table, worst grade first
dsa audit --all --json        # the same, for tooling
dsa audit --all --min-grade B # exit 1 if any part is below B (opt-in)
```

```
| Metric                   | Reading | Count   | Grade | Weight |
| section page coverage    | 100%    | 34/34   | A     | 3      |
| table accept rate        | 100%    | 29/29   | A     | 2      |
| mean table fidelity      | 88%     |         | B     | 2      |
| records graded high      | 49%     | 422/859 | A     | 3      |
| figure axes read         | 0%      | 0/100   | F     | 1      |
| revision freshness       | unknown |         | C     | 3      |
| golden pass rate         | 100%    | 16/16   | A     | 4      |
...
> This corpus grades B - figure axes read 0%. 2 of 13 metrics could not be
> computed and are excluded, not scored.
```

Three things are worth knowing before reading a grade.

**A metric the corpus carries no fact for is `n/a`, and it is excluded from the
average.** Never zero, which would defame a corpus for a statistic nobody
recorded; never full marks, which would flatter one. The rule ships in the
scorecard's own `unavailable_policy` field, so a reader is told the convention
rather than left to assume it, and the count of excluded metrics is printed
beside the grade — a `B` earned on ten metrics is a different claim from a `B`
earned on all thirteen. A **missing artifact** is different and is graded down:
a corpus that publishes no pins, no registers or no card rows is a corpus that
cannot answer those questions.

**The thresholds are data.** Every cut point in `audit_rubric.yaml` is anchored
to a value measured on this repository's own eleven corpora, and the ~120-line
comment block at the head of the file says which reading each one was placed
against. Nothing in `datasheet_analyzer/audit/` hard-codes a threshold, a
weight or a letter: a metric the YAML does not carry is not graded at all, and
`tests/unit/test_audit.py` proves it by *deleting* one.

**`revision freshness` reads `unknown` on every corpus in this repository, and
`unknown` grades `C` rather than `A`.** Nobody has checked is not the same as
still current. Run `dsa check-revisions` first if you want that row to mean
something.

### Propose benchmark questions, then confirm them (`dsa golden`)

Invariant 5 says the golden set is this project's objective function and that
it is hand-verified. That survives sixty parts only if the *typing* goes and
the *judgment* stays. `dsa golden suggest` templates candidate questions from
records that already carry a verbatim answer and a printed page; `dsa golden
confirm` walks them beside that page and merges the ones a human accepts.

```bash
dsa golden suggest --part AD9081 --n 20        # writes golden_qa_AD9081.candidate.yaml
dsa golden confirm --part AD9081 --pdf ad9081.pdf   # walk them by hand
dsa golden confirm --part AD9081 --accept-ids g-a15af6a3-pin_t0-r1-A2
dsa golden confirm --part AD9081 --decisions decisions.yaml --dry-run
```

**A candidate counts toward nothing until a human confirms it.** That is the
clause invariant 5 gains, and it is defended three ways rather than one,
because the failure would be silent: the candidate file has a different
*filename* from the benchmark, its top-level key is `candidates:` and it has no
`questions:` at all, and `load_golden` refuses it *by name* — `dsa verify
--golden <candidate file>` exits 2 and says which file to point at instead.

**Selection is stratified, and the stratification is the point.** Twenty
questions off one easy spec table satisfy `--n 20` and confirm only the
extraction path that was already working. Candidates are drawn by a recursive
round-robin over artifact → extraction backend → confidence grade → printed
section, and the mix is published in the file so a degenerate set is visible on
sight. Measured on AD9081 with `--n 20`: 7 specs, 7 pins, 4 plots, spread over
three confidence grades.

**Nothing is dropped in silence.** Every record no template could use is
counted by artifact and by reason, and printed:

```
Refused - 344 record(s) no template could use:
| Artifact   | Reason                                         | Records |
| specs.json | the record prints no name or symbol to ask about | 268    |
| specs.json | the record prints no numeric answer to ask for   |  70    |
| plots.json | the caption is only a figure label               |   1    |
```

That table is how a *stale* corpus is told apart from a broken generator: a
part whose records predate ADR 0005 record ids reports "the record carries no
id to cite" and names the rebuild, rather than reporting an empty pool with a
plausible wrong cause.

**The merged file says how it was confirmed, and never more than that.** A
`--pdf` walk stamps "shown beside the printed PDF page it cites"; a walk with
no PDF stamps that the corpus's own text was shown and cannot confirm a page
citation; a bulk `--accept-ids` / `--decisions` run — the default — stamps that
**no page was displayed** and the questions are unverified. The merge appends,
keeping the existing bytes as the prefix of the new file and matching its
indentation, and it validates the result *before* opening the file for writing,
so a merge that would produce unparsable YAML cannot corrupt the benchmark.

**Back up the golden file before a real confirm run anyway.** All the committed
benchmarks are git-tracked, so recovery is `git checkout --
tests/fixtures/golden_qa_<PART>.yaml`. `DSA_GOLDEN_DIR` moves where all three
files live, which is what keeps a test run — or a prototype that inherited
default settings — off the real ones.

### Other commands

```bash
dsa status    # config, LLM availability, built parts, per-part confidence mix
              # + per-doc extraction stats + projects
dsa family    # list | suggest | confirm | build (see above)
dsa version
```

## Configuration

Environment variables (prefix `DSA_`, or `.env` file):

| Variable | Default | Purpose |
|---|---|---|
| `DSA_PARTS_DIR` | `parts` | where corpora are written |
| `DSA_PROJECTS_DIR` | `projects` | where projects are written |
| `DSA_FAMILIES_DIR` | `families` | where a family index is written |
| `DSA_LIBRARY_DIR` | `library` | the document inventory: one record per `content_hash`, holding its applicability and your labels |
| `DSA_SESSIONS_DIR` | `sessions` | saved `dsa serve` conversations |
| `DSA_CACHE_DIR` | `.cache` | HTTP + extraction caches |
| `DSA_INDEX_TOKEN_BUDGET` | `3000` | hard INDEX.md budget |
| `DSA_ASK_BUDGET` | `4000` | default `dsa ask` pack budget (`--budget` overrides) |
| `DSA_PROJECT_INDEX_TOKEN_BUDGET` | `4000` | hard PROJECT_INDEX.md budget |
| `DSA_FAMILY_INDEX_TOKEN_BUDGET` | `4000` | hard FAMILY_INDEX.md budget |
| `DSA_MCP_MAX_TOKENS` | `6000` | hard cap on every `dsa serve --mcp` response |
| `DSA_LLM_DESCRIPTIONS` | `true` | use LLM for INDEX descriptions |
| `DSA_MODEL` | `claude-haiku-4-5` | Anthropic model for descriptions |
| `DSA_CHAT_MODEL` | `claude-opus-5` | Anthropic model for the `dsa serve` chat agent |
| `DSA_CHAT_MAX_TOKENS` | `16000` | one assistant turn's output budget |
| `DSA_SERVE_HOST` | `127.0.0.1` | `dsa serve` bind address (no auth — keep it loopback) |
| `DSA_SERVE_PORT` | `8765` | `dsa serve` port |
| `DSA_ANALYZE_WORKERS` | `4` | parallel jobs in a workbench analyze run |
| `ANTHROPIC_API_KEY` | — | enables LLM enrichment |
| `DSA_PLOT_IMAGE_DPI` | `150` | DPI for PDF-rendered plot fallback |

Token counts everywhere are `chars/4` (see `tokens.py`).

## Development

```bash
python -m pytest tests/ -q    # ~90 s, fully offline (the phase-4 gate
                              # builds four real PDFs)
python -m ruff check src tests

npm --prefix web run typecheck   # frontend types
npm --prefix web test            # vitest + jsdom; tests live in tests/web/
```

Tests are hermetic: TI pages replay from `tests/fixtures/recorded_http/`
(unrecorded URL = hard error), synthetic PDFs are built in-test with PyMuPDF,
and the LLM is a fake client. Integration tests use the real `afe7950.pdf` /
`afe7953.pdf` (skip-guarded) plus recorded fixtures. The MCP server is driven
in-process over the SDK's memory transport — a real client session, no
subprocess and no port. The workbench is held to the same rule: its backend is
tested in-process against a temp `parts_dir` / `library_dir` / `sessions_dir`
and its frontend under jsdom — no browser, no live server, no real model.

Per-part goldens in `tests/fixtures/golden_qa_<PART>.yaml` are the
objective function: hand-verified answers and page cites covering direct
corpus reads, spec queries, plot queries and — since phase 5 — the **ask**
and **search** paths (AFE7950 carries the 21-Q benchmark; the four gate parts
AD9081/LM741/QPA1003P/HMC520A each have their own, all verified 100% offline;
AFE7953 has a 13-Q set verified against the committed corpus + the
skip-guarded PDF, because that part has no offline build path).
`dsa verify --part X` discovers the part's golden by name and fails loudly
when it is missing — extend a set when new answer paths ship; `dsa verify`
must stay at 100% for supported paths.

Every part's set carries one **ask-path** question (a designer's words, no
symbols) and one **search-path** question (top-1 must be the section holding
the answer). Both reuse an existing question's cited page and verbatim
substrings, so the new surface is proven against the old objective function:

```yaml
- id: a01-ask-max-junction-temperature
  question: What is the maximum junction temperature?
  expected_substrings: ["Junction temperature", "150"]
  pages: [4]
  kind: ask
  ask_query: {route: spec}        # `dsa ask` must route to a record and cite p.4

- id: k01-search-sysref-timing
  question: Where are the SYSREF setup and hold requirements specified?
  expected_substrings: ["50", "ps"]
  pages: [27]
  kind: search
  search_query: {query: "sysref setup and hold"}   # top-1 must be §4.10
```

`dsa verify` runs both tables whenever a set carries them, needs no `--pdf`
for either, and fails the command when one fails. An ask-path question also
fails when its pack goes over budget, and a search-path question fails with
`search unavailable` on a corpus with no current index — a path that never
ran establishes nothing.

## Caveats

- **Content path is vendor-neutral.** TI keeps its HTML viewer path;
  ADI / Qorvo / older TI / vendor N+1 datasheets route to the offline
  `pdf_layout` floor (PyMuPDF-only, no per-vendor layout rules — adding
  a vendor is a brand-lexicon data change, not engine code). Register maps
  read through `pdf_layout` for any vendor (a document-type fact, not a
  vendor rule: read as paragraphs a register map answers nothing); the prose
  companions — errata, app notes — use `pdf_text` for any vendor.
- Table page pinning is exact where the table is locatable in PDF page text;
  otherwise the table honestly keeps its section-level page range. A row of a
  table that spills onto the next printed page cites its own page only on the
  `pdf_layout` path; an HTML-derived table gives every row the page the table
  starts on (see `KNOWN_SHORTCOMINGS.md`).
- Register summary tables (address / name / reset / access) publish as
  `registers.json` and answer `dsa regs --part X [--name] [--addr 0x1A04]`.
  A summary table that fails validation is rejected whole with a recorded
  reason rather than published half-read, and a column the map never printed
  stays empty and says so — a blank reset read as `0x00` is what breaks a
  bring-up sequence.
- **Verbatim values are authoritative; the parsed numeric layer is additive
  and may be absent.** Every printed cell is kept exactly as the datasheet
  printed it and is never mutated. Beside it, `structure/quantities.py` parses
  what it can into SI floats (`value_si`, `unit_si`, `value_kind`,
  `parse_confidence`) so cards, margins and `dsa compare` can do arithmetic.
  A cell that does not parse stays `parse_confidence: none` — a first-class
  outcome, not an error — and any consumer that sorts or compares **reports
  the unparsed population explicitly** rather than dropping it.
- Pin tables publish as `pins.json` and answer `dsa pins --part X [--q VDD]
  [--type power]`; multi-pin rows expand so each pin is individually citable,
  and a type comes from a checked-in lexicon with `unknown` as a legitimate
  answer. A pin table that fails validation is rejected **whole**, with the
  reason recorded — a pin table missing a row reads as "this pin does not
  exist" during schematic capture. Package drawings stay figure images.
- Design cards (`dsa card --part X --card power|thermal|interface|limits`)
  and `dsa compare A B` are derived views: they compose records that already
  exist, and every value on them carries the record id, the printed page and
  the named rule that produced it. An empty card is a real answer — this part
  does not print that data — and `dsa compare` reports rows only one part
  prints rather than dropping them.
- **PyMuPDF is AGPL-3.0** — it is the engine behind the offline
  `pdf_layout` extraction floor, and TI's HTML path uses it for
  TOC/identity/verification. Fine for local research; review before
  commercial use.

## Repository docs

- `AGENTS.md` — architecture contract, invariants, module map
- `CONTEXT.md` — the domain glossary: Part, SourceDocument, Library,
  Applicability, Tag, Label, Job, Batch
- `docs/adr/` — architecture decision records, including
  `0005-documents-apply-to-parts.md` (why a document applies to parts instead
  of belonging to one), `0006-auto-resolved-scope.md` (why there is still no
  "all parts" scope), `0007-deterministic-derived-artifacts.md` (why no
  model may appear anywhere in a derived value's path) and
  `0008-tracked-corpora-are-current-and-self-contained.md` (what version a
  committed corpus must be at, and why it may not reference the library)
- `KNOWN_SHORTCOMINGS.md` — what this tool cannot currently do, why, what it
  does instead, and what would close each entry
- `PHASE_1_REPORT.md` / `PHASE_2_REPORT.md` / `PHASE_3_REPORT.md` /
  `PHASE_4_REPORT.md` / `PHASE_5_REPORT.md` / `PHASE_6_REPORT.md` /
  `PHASE_6_5_REPORT.md` — measured
  results per phase (all shipped; PHASE 6.5 is the fidelity pass that added no
  capability and made the layer under the derived artifacts read the page
  correctly; PHASE 4 covers the
  vendor-neutral layout core + four-part gate, PHASE 5 the agent-native access
  surface: retrieval core, aliases, search, confidence, `ask`, projects, MCP,
  `AGENT.md`; PHASE 6 the design-time content: the numeric layer, pins,
  registers, design cards, the plot axis catalog and cross-part compare, all
  under invariant 8)
- `PHASE_2_PLAN.md` / `PHASE_3_PLAN.md` / `PHASE_4_PLAN.md` /
  `PHASE_5_PLAN.md` / `PHASE_6_PLAN.md` — completed execution contracts,
  superseded by their reports