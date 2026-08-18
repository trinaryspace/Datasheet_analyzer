# PHASE 6 PLAN — Design-Time Content

**Status: SUPERSEDED — shipped.** Execution contract for
`.scratch/design-time-content/`, kept for the record. The measured outcome is
`Reports/PHASE_6_REPORT.md`; read that first. Three statements here were stale
by the time the phase ran and the report is the authority on all three: the ADR
is **0007**, not 0005 (0005 and 0006 were taken); `PIPELINE_VERSION` went
**0.4.0 → 0.5.0**, not 0.3.0 → 0.4.0; and ticket 05 was **unblocked** by
`LMX1204_registermap.pdf` landing in the repo.

**Depends on Phase 5** (retrieval core, confidence, MCP surface, alias
lexicon). New artifacts here are surfaced through the seams Phase 5 built.

**Scope decisions taken before writing**: derived data is deterministic-only
(no LLM in the derivation path); pin extraction covers printed pin tables only
(package drawings stay images); register maps are **first-class in this
phase**, not a stretch; plots get an axis catalog so the agent can pick the
right figure and be handed the PNG.

## Why

After Phase 5 the corpus answers datasheet questions well. It still does not
answer *design* questions, because it is organised the way a datasheet is
organised, and it is missing the two tables a designer and a firmware engineer
actually live inside:

- **The pin table.** During schematic capture, the pin table *is* the
  datasheet. It does not exist in the corpus in any queryable form.
- **The register map.** Currently every companion register-map PDF routes to
  the degraded `pdf_text` backend — paragraphs only, no tables. Bring-up and
  driver questions are unanswerable by construction.
- **Task-shaped views.** "What rails does this need and how much current?" is
  a five-section scavenger hunt across §4.3, §4.9, the pin table, and the
  package section. A designer asks it as one question.
- **Comparison.** Spec values are verbatim strings that are never parsed, so
  "which of these tolerates 105 °C" cannot be answered even though every
  number is present and cited.
- **Figure targeting.** 514 figures for one part, catalogued by caption and
  conditions only. An agent burns a vision call to discover it opened the
  wrong one.

Phase 6 is where the tool stops helping someone *read* a datasheet and starts
helping someone *design* with it.

## The derived-artifact contract (ADR 0005)

This phase creates the first artifacts that are not verbatim-extracted, which
puts pressure on invariant #1 ("LLM writes indexes, never content"). The
resolution, to be recorded as `docs/adr/0005-deterministic-derived-artifacts.md`
and added to `AGENTS.md` as **invariant 8**:

> A derived artifact may contain only:
> **(a)** values copied verbatim from a spec, table, or pin record;
> **(b)** values computed from those by a documented pure function;
> **(c)** structural labels drawn from a checked-in lexicon.
>
> Every field carries `source` (record id + page) and `derivation` (the named
> rule that produced it). No model call may appear anywhere in the derivation
> path. A derived artifact that cannot fill a field leaves it null and says
> so — it never interpolates, and it never emits a plausible default.

Concretely, every derived value ships in a provenance envelope:

```json
{ "verbatim": "1350 mA", "value_si": 1.35, "unit_si": "A",
  "source": "specs.json#rec_412", "page": 21,
  "derivation": "parse_quantity+si_normalize", "confidence": "high" }
```

`card_version` participates in the publish cache key, so changing a derivation
rule forces regeneration rather than silently leaving stale cards behind.

## Component specs

### 1. Normalized numeric layer (`structure/quantities.py`)

The enabling primitive for cards, comparison, and margin checks. **Verbatim
strings remain authoritative and are never mutated** — this layer is strictly
additive and always allowed to fail.

`parse_quantity(text, unit_hint) -> Quantity | None` must handle, with a test
case each:

| Input shape | Example | Result |
|---|---|---|
| plain | `105` | point |
| signed / unicode minus | `−40`, `+85` | point |
| range | `−40 to +85`, `-40…125` | range |
| inequality | `< 5`, `≥ 1.8` | bound |
| tolerance | `±0.5` | tolerance |
| SI prefix | `1350 mA`, `12 GSPS` | point, scaled |
| scientific | `1.2e-9` | point |
| unparseable | `See Figure 7`, `Note 2`, `—` | **None** |

Returning `None` is a first-class outcome recorded as
`parse_confidence: none`. Unit canonicalisation reuses `structure/units.py`
(including both ohm glyphs). Additive `SpecRecord` fields: `value_si`,
`unit_si`, `value_kind` (`point|range|bound|tolerance`), `parse_confidence`.

Any consumer that sorts, compares, or checks margins **must report the
unparsed population explicitly** — "3 of 47 rows could not be parsed, listed
below" — never quietly drop them.

### 2. Device-table abstraction (`structure/device_tables.py`)

Pin tables and register-summary tables are the same structural animal: wide,
repetitive, keyed by a first column. Building one abstraction with two
consumers is both less code and a better test surface than two parsers.

Pipeline: **identify → map columns → validate → emit**.

- **Identify** candidate tables by header lexicon (checked-in data, per the
  no-vendor-rules philosophy):
  - pin: `pin|ball|pad|no\.?|number` × `name|signal` × `type|i/o|dir` × `description|function`
  - register: `address|offset|reg` × `name|register` × `reset|default|por` × `access|r/w|type`
- **Map columns** to the target schema by header match, with positional
  fallback when headers are abbreviated or missing.
- **Validate**: unique keys, monotonic addresses where applicable, and
  expected-count cross-checks. A validation failure **rejects the table with a
  recorded reason** — the same honesty contract `pdf_layout` already applies
  to parametric tables — rather than emitting a half-parsed record set.
- **Emit** records with full provenance (table index, row index, page).

Rejections join the existing `extraction_stats.rejection_reasons` so device
tables are as measurable as parametric ones.

### 3. Pins (`pins.json`, `dsa pins`)

```json
{ "pin": "A1", "name": "VSSA", "type": "ground", "direction": "—",
  "description": "Analog ground", "page": 4,
  "table_index": 2, "row_index": 0, "confidence": "high" }
```

- **Multi-pin rows expand.** `A1, A2, B1` and `A1–A4` become four records
  sharing name/type/description, each individually citable.
- **Type classification** from a checked-in lexicon over name + description:
  `power | ground | analog | digital | clock | rf | nc | reserved | unknown`.
  `unknown` is a legitimate output; a guess is not.
- **Package cross-check**: where a pin count is parseable from the package or
  ordering-information section, compare it against the record count and emit a
  *warning* on mismatch. Honest, non-fatal, surfaced in `dsa audit`
  (Phase 7).
- CLI: `dsa pins --part X [--q VDD] [--type power] [--json]`.
- Package drawings stay figure images; `get_figure` already hands them over
  when a designer wants the ball map.

### 4. Registers (`registers.json`, `dsa regs`)

**Routing change, called out explicitly:** `DocType.REGISTER_MAP` currently
prefers the `pdf_text` backend for every vendor. This phase routes it to
`pdf_layout` so tables are available at all. That is a behaviour change to a
documented caveat in `README.md` and `AGENTS.md`, and it invalidates cached
extractions for register-map documents — hence the `PIPELINE_VERSION` bump.

Two table shapes, shipped in order:

**(a) Register summary** — address / name / reset / access. Handled by the
device-table abstraction directly.

**(b) Per-register bit fields** — the harder shape: a bit-position header row
(`7 6 5 4 3 2 1 0`) over field-name cells that span columns, followed by field
description rows. Ticket 05 ships (a) with a gate; ticket 06 attempts (b) and
is permitted to **park with a `KNOWN_SHORTCOMINGS.md` entry** if the accuracy
gate fails on the reference document, rather than shipping approximate
bitfields. Wrong bit positions are worse than absent ones.

```json
{ "block": "TX_DIG", "name": "TXDIG_CTRL0",
  "address": {"verbatim": "0x1A04", "value": 6660},
  "width": 8, "reset": {"verbatim": "0x00", "value": 0}, "access": "R/W",
  "fields": [{"name": "NCO_EN", "bits": {"verbatim": "[3]", "hi": 3, "lo": 3},
              "access": "R/W", "reset": "0", "description": "Enable NCO"}],
  "page": 212, "confidence": "high" }
```

- CLI: `dsa regs --part X [--name] [--addr 0x1A04] [--field NCO] [--json]`,
  and an MCP `find_register` tool.
- **Blocked on the reference register-map PDF** being dropped into the repo.
  Until it lands, ticket 05 stays `needs-info`: a register parser written
  without a real document to gate against would be fiction. Synthetic fixtures
  built with PyMuPDF cover the unit level in the meantime.

### 5. Design cards (`cards/*.json` + `cards/*.md`)

Task-shaped views over records that already exist. Four cards, each with a
selector rule set and each emitting an **honest empty card** when the part
genuinely lacks the data:

| Card | Contents | Selectors |
|---|---|---|
| `power` | rails: voltage min/typ/max, max current, total dissipation | pin type `power` ∪ symbols matching `V(DD\|CC\|SS)`, `I(DD\|CC)` families via the alias lexicon |
| `thermal` | RθJA, RθJC(top), ΨJT, ΨJB, TJ max, TA range, Tstg | thermal symbol family |
| `interface` | JESD204B/C support, lane count, max lane rate, SPI timing | interface lexicon; empty for parts without one |
| `limits` | abs-max vs recommended-operating delta per parameter, with computed margin | join §abs-max and §recommended by alias-resolved symbol |

The `limits` card is the one that earns its keep on its own: it computes
margin only where **both** sides parsed numerically, lists the pairs it could
not compare, and flags parameters where recommended-max equals abs-max (zero
margin) — a genuine design hazard that is invisible when the two tables are
read pages apart.

Rendered `cards/power.md` carries a `<!-- derived: card_version N -->` banner
and a citation on every row. `dsa card --part X --card power`, plus an MCP
`get_card` tool.

### 6. Plot axis catalog

Additive `PlotRecord` fields: `x_label, x_unit, x_min, x_max, y_label, y_unit,
y_min, y_max, axis_confidence`.

Extraction is geometric and deterministic: tick labels cluster along the
figure region's left edge and bottom edge; the axis title is the text run
parallel to that edge (rotated 90° for the y-axis, which PyMuPDF reports via
span direction). Numeric tick sequences give min/max. **Anything uncertain
stays null** with `axis_confidence: low`.

This makes `find_plots --near-x 3.5GHz --y-label "Gain"` narrow 514 figures to
one before a single vision token is spent, and `get_figure` (Phase 5) hands
back that one PNG for the agent to present. Image *analysis* of the PNG is a
future consumer of this catalog and is explicitly not built here — the catalog
is designed so it can be added without reshaping `plots.json`.

### 7. Cross-part compare (`dsa compare`)

```
dsa compare AFE7950 AFE7953 --symbol Pdiss
dsa compare AFE7950 AFE7953 --card power
```

Aligns rows by alias-resolved symbol. Each row shows both verbatim values,
both page cites, and an SI delta **only where both sides parsed**. Rows
present in one part and not the other are reported as `only in A`, never
silently dropped. This is the part-selection question, answered in one call.

## Schema / CLI / versions

- **Additive only** to existing models. New files per document: `pins.json`,
  `registers.json`, `cards/*.json`, `cards/*.md`.
- `PIPELINE_VERSION` 0.3.0 → **0.4.0**. The register-map routing change
  invalidates `(content_hash, backend)` cache entries for those documents —
  intentional and documented.
- New CLI: `pins`, `regs`, `card`, `compare`. New MCP tools: `find_pin`,
  `find_register`, `get_card`, `compare_parts`; `find_plots` gains axis
  filters.
- New config: `DSA_CARD_VERSION` (participates in the publish cache key).

## Acceptance gate

The claim is *"the corpus answers schematic-capture and bring-up questions,
and every derived number traces to a printed page."*

1. Pin tables extract for all six built parts, or are **honestly rejected with
   a recorded reason** — a part with no parseable pin table must produce no
   `pins.json` rather than a partial one. Golden pin questions per part
   (pin → name, name → pins, count by type) verify at 100%.
2. The package cross-check runs on every part; mismatches appear as warnings,
   and at least one is asserted in test if any part mismatches.
3. Register summary tables extract from the reference register-map PDF, with a
   golden set covering address→name, name→reset, and access lookups.
   Bit-field extraction either passes its accuracy gate or is parked with a
   recorded shortcoming.
4. All four cards build for AFE7950 and AD9081. **Every value on every card
   resolves to a spec/pin record and a printed page**, asserted programmatically
   by walking each card's `source` fields — this is the invariant-8 test.
5. `parse_quantity` unit tests cover every row of the shapes table above,
   including the unparseable cases returning `None`.
6. `dsa compare AFE7950 AFE7953` produces a delta table where both sides
   parsed, and reports the unparsed population explicitly.
7. Axis metadata extracted for ≥60% of AFE7950's 514 figures with
   `axis_confidence: high`; the rest honestly null. (Threshold is a floor to
   beat and to record in the report, not a target to fit to.)
8. All Phase 5 goldens still at 100%; `pytest` offline, `ruff` clean.

## Implementation order

| # | Ticket | Notes |
|---|---|---|
| 01 | ADR 0005 + provenance envelope | Contract first — everything else conforms to it |
| 02 | Numeric layer (`parse_quantity`) | Pure, heavily unit-tested, no I/O |
| 03 | Device-table abstraction | Shared machinery; no consumer yet |
| 04 | Pins + `dsa pins` | First consumer; proves the abstraction |
| 05 | Register summary + `dsa regs` | **Blocked on reference PDF** |
| 06 | Register bit fields | Gated; may park with a shortcoming |
| 07 | Design cards + `dsa card` | Composes 02 + 04 |
| 08 | Plot axis catalog | Independent; parallelisable throughout |
| 09 | `dsa compare` | Composes 02 + 07 |
| 10 | MCP surface + goldens + phase gate | Closes the phase |

04 must land before 05 so the device-table abstraction is proven on the easier
shape first. 08 is independent of everything and can fill any wait on the
reference PDF.

## Docs / invariants to update on landing

- `AGENTS.md`: **invariant 8** (deterministic derived artifacts); module map
  gains `structure/device_tables.py`, `structure/quantities.py`, `cards/`;
  the register-map caveat is rewritten.
- `README.md`: the "register maps stay paragraphs-only" caveat and the "spec
  values are never parsed" caveat both need amending — the second becomes
  "verbatim values are authoritative; a parallel parsed layer is additive and
  may be absent."
- `CONTEXT.md`: new nouns — **Design card**, **Device table**, **Quantity**.
- `docs/adr/0005-deterministic-derived-artifacts.md`.

## Out of scope (kept out, recorded)

- **Geometric ball-map reconstruction** from package drawings. Pin tables
  only; drawings remain retrievable images.
- **Vision fallback for unparseable pin tables** — would put a model in the
  content path, contradicting invariant 8.
- **Curve digitization** ("what is the gain at 3.5 GHz"). The axis catalog is
  the groundwork; digitization needs its own accuracy gate against hand-read
  values before any number it produces can be trusted, and a confidently wrong
  interpolated value is the worst failure this tool could have.
- **Cross-part interface validation** (does part A's output level match part
  B's input?) — needs connectivity, which needs netlist import. Not before
  projects prove out.
