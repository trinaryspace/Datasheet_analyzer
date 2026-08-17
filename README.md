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
  citations straight from the PDF). **Register maps route to the same layout
  engine** — their register-summary and bit-field tables are the whole reason
  the document exists — while a degraded `pdf_text` backend handles errata and
  app notes (paragraphs only).
- **Structure** — HTML tables become atomic, span-expanded blocks with their
  conditions preamble + footnotes attached; sections get page ranges from the
  PDF's printed TOC; tables get exact pinned pages where possible.
- **Enrich** — an `INDEX.md` under a hard token budget (default 3,000). An
  LLM writes only the section descriptions (optional); all corpus content is
  verbatim-extracted. Without an API key, descriptions are deterministic.
- **Publish** — per-section markdown with CSV twins of every table,
  `specs.json`, `plots.json` + `figures/` image files, a `search_index.json`
  BM25 index per document, and `manifest.json`.
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
INDEX descriptions (one batched call per build; falls back safely without it).

Optional: `uv pip install --python .venv/Scripts/python.exe -e ".[mcp]"` adds
the MCP SDK for `dsa serve --mcp` (see [Use it from an agent](#use-it-from-an-agent-mcp)).
Everything else works without it.

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

### Look up a pin (`dsa pins`)

```bash
dsa pins --part AD9081 --pin A2            # one ball -> its signal, on its page
dsa pins --part AD9081 --name VDD          # every ball whose name carries VDD
dsa pins --part AD9081 --type power        # every supply ball
dsa pins --part AD9081 --q "clock" --json
```

Returns `pins.json` records: the designator, the printed name, the `I/O`
direction as printed, the description, the page, and a **type** —
`power | ground | analog | digital | clock | rf | nc | reserved | unknown` —
drawn from `registry/pin_types.yaml`. A printed row naming several pins
(`A1, A2, B1`, `C1-C3`) becomes one record per pin, each still quoting the row
it came from, so a pin search cannot miss a pin that shared a row.

Two honesty rules apply, and both are visible in the output. `unknown` is a
real answer: a pin the lexicon cannot read, or one whose evidence points at two
categories at once, is never guessed into a category, and every classified pin
publishes the phrase that decided it (`type_evidence`). And a part whose
datasheet prints no pin table — or whose pin table failed validation and was
rejected whole — has **no** `pins.json` at all; `dsa pins` there says so and
exits 2 rather than returning an empty list that would read as "this device has
no such pin". Where the package states a pin count and the extracted count
disagrees, the mismatch is recorded in the manifest and printed by
`dsa status`; it never suppresses the table.

### Look up a register (`dsa regs`)

```bash
dsa regs --part LMX1204 --addr 0x19        # one address -> its acronym + reset
dsa regs --part LMX1204 --addr 25          # ...the same register, in decimal
dsa regs --part LMX1204 --name R25         # exact acronym, with its bit fields
dsa regs --part LMX1204 --field CLK_MUX    # which register holds a bit field
dsa regs --part LMX1204 --q "SYSREF" --json
```

Returns `registers.json` records, published for every document whose register
summary passed validation: the address **as printed and as an integer**, the
acronym, the description the document gave the register, the printed access
column where there is one, and the reset value where the document states one —
with the printed line it was read from and the page it was printed on, because
a reset usually lives in the register's own declaration heading (`R25 Register
(Offset = 0x19) [Reset = 0x0211]`) rather than in the summary row.

The integer form is what makes a lookup usable: `0x19`, `0x19` in lower case,
`19h` and `25` are one question. Hex is recognised only by the marker the
document printed (`0x…` / `…h`) — a bare number means decimal on both sides,
because `--addr 6660` has no document to take a base from. A cell the grammar
cannot read keeps its printed form, publishes no integer, and is still
reachable by typing exactly what the page shows.

The same two honesty rules as pins apply: a summary table that fails
validation is rejected whole with a recorded reason and publishes no file, and
a part with no register summary anywhere makes `dsa regs` say so and exit 2
rather than return an empty list that would read as "this device has no such
register". A register the document states no reset for prints `reset=?`.

**Bit fields** ride on the same records: each register carries the fields its
own field table prints — name, bit range (as printed *and* as `hi`/`lo`), the
printed access code, the printed field reset and the description — plus the
register `width` those ranges were validated against and the bits of it no
field claims (`unaccounted_bits`). Asking for one register (`--name`, `--addr`)
or for a field (`--field`) prints them; a 35-row listing does not.

Bit fields are the one artifact here that ships **only** when it can be
verified, because a driver written against a wrong bit range misconfigures
silicon silently:

- a field set that overlaps or overflows its register's width is **refused
  whole** with a recorded reason — measured, LMX1204's own R90 table prints
  `15:8` and then `15:0`, a typo in the document, and the corpus publishes
  neither field rather than picking one;
- a register whose fields could not be read keeps its record with `fields: []`
  and that reason, so it is never silently absent;
- bits no field claims are listed rather than assumed, so the coverage of a
  field list is checkable by reading it;
- a register with no printed width to check against publishes no fields at all.

Because `--field` filters on a value the corpus *derived*, it also prints what it
could not consider — "14 of 70 registers … publish no bit fields; a bit-field
lookup here cannot establish that a field does not exist" — so an empty result is
never mistaken for a device without that bit.

Measured on LMX1204: **28 of 35 registers** publish a field set in each of its
two documents (116 fields each), every one of them tiling its 16-bit register
exactly, and every published field's printed quartet — bit range, name, access,
reset — verified against the text of the page it cites
(`tests/integration/test_phase6_registers.py`). The seven that publish none are
recorded in `KNOWN_SHORTCOMINGS.md`.

### Open a design card (`dsa card`)

```bash
dsa card --part AFE7950                    # which cards this build declares
dsa card --part AFE7950 --card power       # rails, per-rail current, dissipation
dsa card --part AFE7950 --card thermal     # RθJA, RθJC(top), ΨJT, ΨJB, TJ, TA, Tstg
dsa card --part AFE7950 --card interface   # JESD204 / SerDes rates, SPI timing
dsa card --part AFE7950 --card limits      # abs-max vs recommended, with the margin
dsa card --part AD9081 --card power --json # every value in its provenance envelope
```

A **design card** is the datasheet reorganised around a design task instead of
around the document: four views over records the corpus already published,
written into the corpus as `cards/<name>.json` + `cards/<name>.md` and printed by
this command from the same rendering, so the file and the command can never
disagree.

Nothing on a card is generated. Every value is a cell quoted **with its printed
unit**, a number computed from quoted cells by a named rule, or a label from
`registry/cards.yaml` — and each one carries the record it came from, the page it
was printed on and the rule that produced it (ADR 0005 / invariant 8). A test
walks every one of those references back to a record and a printed page; a value
with no resolvable provenance fails the build.

The `limits` card is the one that earns its keep alone. It joins the absolute-
maximum and recommended-operating tables — pages apart in every datasheet — by
alias-resolved symbol, and:

- computes a margin **only where both sides parsed** as numbers in the same SI
  base (a computed value has no verbatim: no page printed it, so it is marked
  `*(derived)*` and never quoted as printed text);
- **flags a zero margin**, where the recommended maximum *is* the absolute
  maximum and any overshoot is out of specification, and the reverse too;
- **lists every pair it could not compare**, with the reason — printed on one
  table only, no maximum stated, a value the numeric layer could not read, or an
  ambiguous join (three ratings against three rails pair only where two rows
  share a printed identity cell character for character; guessing between them
  would compute a 0.9 V rail's headroom against a 1.8 V rating).

Measured on AFE7950: `TJ` has 40 °C of headroom — 150 °C absolute maximum on p.4
against a 110 °C recommended operating maximum on p.6 — and the 0.9 V rail has
0.25 V. Neither reference part prints a zero-margin parameter; the flag is
pinned by test instead of by luck.

A card with nothing to show is **honestly empty**: it states what it looked for
and did not find, is published like any other card, and is recorded in the
manifest's `derived_warnings` (measured: LM741 is an op-amp, so its interface
card has no rows and says so). Widening a card is a YAML edit — a table title, a
unit, a symbol phrase — never a looser rule.

### Find a plot

```bash
dsa plots --part AFE7950 --q "Output Fullscale"
dsa plots --part AFE7950 --q "Gain Error" --section 4.12.1
dsa plots --part AFE7950 --tag "tx,800mhz"
dsa plots --part AFE7950 --q "Output Fullscale" --json
# the axis catalog: pick the figure before spending a vision call on it
dsa plots --part AFE7950 --y-label "Phase Noise" --near-x 1MHz
dsa plots --part AFE7950 --x-label "Temperature"
```

Returns matching `plots.json` records (caption, conditions, section, page,
confidence, and the image file path under `figures/`) for an agent to open.

Every record also carries an **axis catalog** — what each axis is titled, in what
printed unit, over what printed tick range, on what scale — read off the page
geometrically, so 514 figures narrow to a handful from text alone (measured:
`--y-label "Phase Noise"` leaves 30, `+ --near-x 1MHz` leaves 14). `--near-x`
scales the question to the axis's own printed unit, so `1.35GHz` matches an axis
printed in MHz.

An axis that could not be read is **null and says so** (`axis_confidence: low`)
rather than approximate, and the figure keeps its caption, conditions, page and
image regardless — no plot is lost to a failed axis reading. Because the axis
filters select on a derived value, they print the population they could not
consider, so an empty result on a part whose plots are raster images can never
read as "no such figure exists". Measured `high` axis coverage: AFE7950 89%,
AFE7953 75%, HMC520A 50%, LMX1204 43%, and AD9081 / LM741 / QPA1003P 0% — all
three of those draw their plots as images, which is a fact about the documents
(`Reports/PHASE_6_REPORT.md`, `KNOWN_SHORTCOMINGS.md`).

### Read content by section

Load `parts/AFE7950/INDEX.md` first — it maps every section to its file and
page range within its token budget. Then grep/read the section files:

```
parts/AFE7950/
├── INDEX.md               # always-loadable index (hard budget, 3000 tok)
├── AGENT.md               # the retrieval protocol, shipped with the corpus (~1.4k tok)
├── cards/                 # design cards: power|thermal|interface|limits, as .json + .md
├── sources.json           # doc inventory: sha256, type, revision, nda flag
├── manifest.json          # machine-readable section map + stats
└── docs/datasheet-<hash8>/
    ├── sections/*.md      # atomic; `<!-- source: <doc> p.N[-M] -->` header
    ├── tables/*.csv       # machine-readable twins of each section table
    ├── figures/           # plot image files referenced by plots.json
    ├── specs.json         # parametric spec records (symbol/name/conditions/min/typ/max/unit/page)
    ├── plots.json         # searchable plot catalog + file map + per-figure axis catalog
    └── search_index.json  # BM25 index over sections/*.md (what `dsa search` ranks)
```

Every answer should quote values **with units** and cite `p.N` from the
section header.

### The protocol ships with the corpus (`AGENT.md`)

`INDEX.md` is the map; `AGENT.md` beside it is how to read it. It is written
at publish for every part and every project, and it is short enough
(~1.4k tokens, ceiling 1,700) to load next to the index every time:

- the rules — index first, never bulk-read, prefer `ask`, quote units, cite
  `p.N`, check the confidence grade, and on `low` send the designer to the
  printed page;
- both access paths, the `dsa` CLI and the MCP tools, each with a worked
  example scoped to that part or project;
- the confidence table: what each grade means and what to do about it.

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

`--part` and `--project` are mutually exclusive, and one of them is required.

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
| `get_index` | part | the part's `INDEX.md` |
| `search` | part or project | BM25 hits, each cited by construction |
| `find_spec` | part or project | spec records through the alias ladder |
| `read_section` | part | one section verbatim, bounded by `max_tokens` |
| `find_plots` | part or project | the plot catalog, filtered |
| `get_figure` | part | one figure **as an image content block** |
| `ask` | part or project | one cited, budget-bounded answer pack |

Resources `dsa://part/<PART>/INDEX.md` and
`dsa://project/<NAME>/PROJECT_INDEX.md` let a client pin an index into context
without spending a tool call.

Every response carries citations and confidence, declares its own JSON schema
(shipped in each tool's `_meta.response_schema`), and is capped at
`DSA_MCP_MAX_TOKENS` (default 6000) — a truncated response **says so** and
names the setting. `get_figure`'s image block is atomic and is not trimmed:
truncating base64 makes a corrupt PNG, not a shorter one, so the cap governs
the JSON that cites it and the payload reports the image's byte size.

### Add companion documents

```bash
dsa add-doc register_map.pdf --part AFE7950 --type register_map [--nda]
dsa build afe7950.pdf --part AFE7950   # rebuild picks it up
```

Types: `register_map`, `errata`, `app_note`, `datasheet`. A `register_map`
extracts through the vendor-neutral layout floor and publishes
`registers.json` (`dsa regs`); errata and app notes extract with the honest
`pdf_text` backend (paragraphs only; no trusted tables, no `specs.json`).
All of them join the same `INDEX.md`.

### Other commands

```bash
dsa status    # config, LLM availability, built parts, per-part confidence mix
              # + per-doc extraction stats + recorded derived-artifact
              # warnings (e.g. a pin-count mismatch) + projects
dsa version
```

## Configuration

Environment variables (prefix `DSA_`, or `.env` file):

| Variable | Default | Purpose |
|---|---|---|
| `DSA_PARTS_DIR` | `parts` | where corpora are written |
| `DSA_PROJECTS_DIR` | `projects` | where projects are written |
| `DSA_CACHE_DIR` | `.cache` | HTTP + extraction caches |
| `DSA_INDEX_TOKEN_BUDGET` | `3000` | hard INDEX.md budget |
| `DSA_ASK_BUDGET` | `4000` | default `dsa ask` pack budget (`--budget` overrides) |
| `DSA_PROJECT_INDEX_TOKEN_BUDGET` | `4000` | hard PROJECT_INDEX.md budget |
| `DSA_MCP_MAX_TOKENS` | `6000` | hard cap on every `dsa serve --mcp` response |
| `DSA_LLM_DESCRIPTIONS` | `true` | use LLM for INDEX descriptions |
| `DSA_MODEL` | `claude-haiku-4-5` | Anthropic model for descriptions |
| `ANTHROPIC_API_KEY` | — | enables LLM enrichment |
| `DSA_PLOT_IMAGE_DPI` | `150` | DPI for PDF-rendered plot fallback |

Token counts everywhere are `chars/4` (see `tokens.py`).

## Development

```bash
python -m pytest tests/ -q    # 868 tests, ~90 s, fully offline (the
                              # phase-4 gate builds four real PDFs)
python -m ruff check src tests
```

Tests are hermetic: TI pages replay from `tests/fixtures/recorded_http/`
(unrecorded URL = hard error), synthetic PDFs are built in-test with PyMuPDF,
and the LLM is a fake client. Integration tests use the real `afe7950.pdf` /
`afe7953.pdf` (skip-guarded) plus recorded fixtures. The MCP server is driven
in-process over the SDK's memory transport — a real client session, no
subprocess and no port.

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
  a vendor is a brand-lexicon data change, not engine code). **Register maps
  route to `pdf_layout` for any vendor** (their tables are the product);
  errata and app notes use `pdf_text` for any vendor.
- Table page pinning is exact where the table is locatable in PDF page text;
  otherwise the table honestly keeps its section-level page range.
- Spec values are verbatim strings, and they stay authoritative: a parallel
  parsed layer (`value_si` / `unit_si` / `value_kind` in `specs.json`) is
  additive, may be absent for any row, and never rewrites what was printed.
  Where the two disagree, the printed string is correct by definition.
- **Register maps are read whole, or not at all.** A `register_map`
  companion publishes `docs/<doc>/registers.json` — one record per printed
  address, carrying the address both as printed and as an integer, the
  acronym, the description, the printed access column where a document has
  one, and the reset value where the document states one. A summary table that
  fails validation (a duplicate address, addresses out of order, a key column
  of prose) is **rejected whole with a recorded reason** and publishes no file,
  for the reason the pin rule gives. `access` and `reset` are `null` rather
  than defaulted when the document prints neither: TI's programmer's guides
  state access per *bit field*, not per register, and `dsa regs` says `reset=?`
  instead of a plausible zero. Measured on LMX1204 (`dsa build lmx1204.pdf
  --part LMX1204 --vendor unknown` + `dsa add-doc LMX1204_registermap.pdf`):
  35 registers from each of its two documents, all graded `high`, with 29 of
  35 resets citing an exact printed page and 6 honestly citing none.
- **Bit fields are published only where they can be checked.** Each register
  carries the fields its own field table prints (name, bit range printed *and*
  parsed, printed access, printed field reset) together with the register width
  the ranges were validated against and the bits no field claims. Overlap or
  overflow **refuses the register's whole field set** with a recorded reason, a
  register whose fields could not be read keeps `fields: []` and that reason,
  and no width means no fields — a field list nobody can check against a width
  is exactly the artifact this rule exists to prevent, since a wrong bit range
  becomes a driver that misconfigures silicon without complaining. Measured on
  LMX1204: 28 of 35 registers per document, 116 fields, each verified against
  the printed page it cites; the gaps are recorded in `KNOWN_SHORTCOMINGS.md`.
- **Pin tables are read from printed tables only.** Package *drawings* stay
  figure images (retrievable with `dsa plots` / the MCP `get_figure`); nothing
  reconstructs a ball map from a drawing, and no model is allowed anywhere in
  the pin path. A datasheet that prints its pin list only as a drawing, or
  whose printed pin table fails validation, therefore publishes no
  `pins.json` — deliberately, because a partial pin table reads as a complete
  one to whoever greps it. Measured on the six built corpora: AD9081 publishes
  321 pins, HMC520A's printed table is rejected with a recorded reason, and
  AFE7950 / AFE7953 / LM741 / QPA1003P publish none.
- **PyMuPDF is AGPL-3.0** — it is the engine behind the offline
  `pdf_layout` extraction floor, and TI's HTML path uses it for
  TOC/identity/verification. Fine for local research; review before
  commercial use.

## Repository docs

- `AGENTS.md` — architecture contract, invariants, module map
- `PHASE_1_REPORT.md` / `PHASE_2_REPORT.md` / `PHASE_3_REPORT.md` /
  `PHASE_4_REPORT.md` / `PHASE_5_REPORT.md` — measured results per phase (all
  five phases are shipped; PHASE 4 covers the vendor-neutral layout core +
  four-part gate, PHASE 5 the agent-native access surface: retrieval core,
  aliases, search, confidence, `ask`, projects, MCP, `AGENT.md`)
- `PHASE_2_PLAN.md` / `PHASE_3_PLAN.md` / `PHASE_4_PLAN.md` /
  `PHASE_5_PLAN.md` — completed execution contracts, superseded by their
  reports