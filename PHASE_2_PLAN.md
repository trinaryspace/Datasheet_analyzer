# Phase 2 Plan — `specs.json`: the Verified Structured Part Model

> Execution contract for the implementing agent. Read `AGENTS.md` first.
> Everything here builds on Phase 1 artifacts as they exist today — do not
> redesign what is already proven. Phase 2 is fully deterministic: **no LLM,
> no network** beyond what Phase 1 already does.

## Objective

Transform the 15 span-expanded parametric tables (already extracted with
conditions, footnotes and page refs) into a normalized, machine-queryable
`specs.json` per document, plus a query interface (`dsa query`). Parametric
questions become **deterministic lookups (~0.5–2k tokens)** instead of
section reads (~4–8k), with the same page-citation guarantees.

Success is measured on the real AFE7950 build: **≥8 of the 12 golden
questions answerable via `dsa query` with correct values AND correct page
cites, 100% of records schema-valid, zero unmapped tables.**

## Why this is safe to build now

Phase 1 already solved the hard part: `TableBlock.grid` is fully
rowspan/colspan-expanded, per-row test conditions are in the cells, footnote
markers are glued to values (`850MHz(2)`) and resolved in
`TableBlock.footnotes`, the conditions preamble is in `TableBlock.conditions`,
and pages are pinned (`TableBlock.page`, fallback section range). Phase 2 is
a **pure transform** over that structure — no new extraction risk.

## Deliverables (file-by-file)

### 1. `src/datasheet_analyzer/models.py` — additions (append, do not refactor)

```python
class SpecUnit(BaseModel):
    verbatim: str          # "Ω" (U+2126), "dBc/Hz", "" when unitless
    canonical: str         # "ohm", "dBc/Hz", "" — see units vocabulary below

class SpecRecord(BaseModel):
    # identity within the document
    section: str                    # "4.5"
    table_index: int                # 0-based within the section
    row_index: int                  # 0-based within the table body
    # semantic roles (empty string when the role doesn't exist for the table)
    symbol: str                     # "ATTstep"   (role: symbol)
    name: str                       # "DSA Attenuation step accuracy (DNL)" (role: name)
    conditions: str                 # row-level: "0 < Atten < 40dB, after calibration"
    table_conditions: str           # TableBlock.conditions verbatim
    min: str                        # verbatim strings — NEVER parsed to float
    typ: str                        #   ("1, 2 or 3" is not a float; keep text)
    max: str
    value: str                      # single-value tables (ESD "VALUE", thermal)
    unit: SpecUnit
    # provenance (the point of the whole system)
    footnotes: list[Footnote]       # full table footnotes (same objects as TableBlock)
    cited_markers: list[str]        # markers appearing in THIS row's cells
    page: int | None                # TableBlock.page or section.page_start fallback
    row_verbatim: list[str]         # the raw grid row — reconstruction check anchor

class SpecTableInfo(BaseModel):
    section: str
    table_index: int
    kind: str                       # "parametric" | "info" | "unmapped"
    n_records: int
    unmapped_headers: list[str]     # headers no role matched (report, don't force)

class SpecSet(BaseModel):
    schema_version: str             # SPECS_SCHEMA_VERSION, e.g. "1"
    part_number: str
    doc_hash: str
    records: list[SpecRecord]
    tables: list[SpecTableInfo]
```

Add `SPECS_SCHEMA_VERSION = "1"` to `config.py` (next to `PIPELINE_VERSION`).
Add `n_specs: int = 0` to `CorpusStats`.

### 2. `src/datasheet_analyzer/structure/roles.py` — header role detection (NEW)

Maps table headers to semantic roles. Deterministic, regex-driven, ordered.

```python
ROLE_PATTERNS: list[tuple[re.Pattern, str]]  # ordered, first match wins
#   r"(?i)^test conditions?$"            -> "conditions"
#   r"(?i)^(min|minimum)$"              -> "min"
#   r"(?i)^(typ|typical)$"              -> "typ"
#   r"(?i)^(nom|nominal)$"              -> "typ"        (4.3 recommended-operating)
#   r"(?i)^(max|maximum)$"              -> "max"
#   r"(?i)^unit$"                       -> "unit"
#   r"(?i)^value$"                      -> "value"      (4.2 ESD)
#   r"(?i)^parameter$"                  -> "parameter"  (positional split below)
#   r"(?i)^thermal metric"              -> "name"       (4.4: THERMAL METRIC | AFE7950 | UNIT)
#   r"(?i)^part number$"                -> "symbol"     (section 3 package info)
#   anything else                       -> None (unmapped)

def assign_roles(headers: list[str]) -> list[str]:
    """header list -> role list, same length. Roles: symbol, name, conditions,
    min, typ, max, value, unit, other. Rules:
    - apply ROLE_PATTERNS per header;
    - multiple 'parameter' columns: first -> 'symbol', second -> 'name',
      further -> 'other' (TI's colspan-PARAMETER header expands to 2 columns);
    - exactly one 'parameter' column -> 'name';
    - a header matching nothing -> 'other', recorded for SpecTableInfo.unmapped_headers;
    - a column whose header is '' but whose position is inside a known table
      -> 'other' (do not guess)."""

def classify_table(headers: list[str], roles: list[str]) -> str:
    """-> 'parametric' (has name|symbol AND (min|typ|max|value) AND unit),
       'info'       (has symbol/name but no min/typ/max/unit roles),
       'unmapped'   (no usable roles at all)."""
```

Reference expectations (must be asserted in tests against the REAL recorded
tables — see test plan): all of 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9,
4.10, 4.11 classify `parametric`; section 3 package table classifies `info`;
zero headers unmapped across all 15 tables.

### 3. `src/datasheet_analyzer/structure/units.py` — unit canonicalization (NEW)

```python
CANONICAL_UNITS: dict[str, str]  # verbatim -> canonical
#   "Ω" (U+2126) / "Ω" (U+03A9) / "ohm"      -> "ohm"
#   "dB","dBm","dBc/Hz","dBFS","deg"          -> themselves
#   "V","mV","mVpp","Vppdiff"                 -> "V" family kept verbatim-canonical: "mVpp" stays "mVpp"
#   "A","mA","µA"                             -> themselves
#   "°C","°C/W"                               -> themselves
#   "Hz","kHz","MHz","GHz"                    -> themselves
#   "SPS","MSPS","GSPS","bps","Mbps","Gbps"   -> themselves
#   "s","ms","ns","ps","UI"                   -> themselves
#   "F","pF","W","mW","bits"                  -> themselves
# unknown verbatim -> canonical == verbatim AND recorded in unknown_units report

def canonical_unit(verbatim: str) -> SpecUnit
def normalize_text(s: str) -> str
    """Derived-artifact normalizer for VALUE TEXT ONLY (never applied to
    corpus markdown): trims, collapses whitespace, unifies '–'/'−' to '-'.
    Applied to min/typ/max/value/conditions inside SpecRecord so queries can
    match; the raw row stays in row_verbatim."""
```

### 4. `src/datasheet_analyzer/structure/specs.py` — the transform (NEW)

```python
def table_to_records(section: SectionNode, table: TableBlock,
                     table_index: int) -> tuple[list[SpecRecord], SpecTableInfo]
    """Per body row: zip roles with grid cells -> SpecRecord.
    - symbol/name from role columns (may be '' when absent);
    - row-level conditions = the 'conditions' role cell;
    - footnotes: attach table.footnotes to every record; cited_markers =
      markers from TableBlock.cited_markers that appear in THIS row's cells
      (regex r'\(\d+\)' on the row's cell texts);
    - page = table.page if set else section.page_start (may still be None —
      honest, never guessed);
    - rows that are entirely empty after role-zipping are skipped (grid was
      already spacer-cleaned in Phase 1);
    - 'info'/'unmapped' tables still emit records with whatever roles exist
      (provenance preserved), only classification differs."""

def build_specset(raw: RawDocument, part_number: str) -> SpecSet
    """All sections/tables -> SpecSet with per-table SpecTableInfo and a
    coverage summary (records, mapped/unmapped counts)."""
```

### 5. `src/datasheet_analyzer/publish/writer.py` — extend (minimal diff)

- `write_corpus(...)` writes `docs/<doc_dir>/specs.json` next to `sections/`
  when a SpecSet is provided (new optional parameter `specsets: list[SpecSet] | None`).
- Sets `stats.n_specs`.
- `CorpusManifest` gains nothing structural (sections already carry
  `doc_hash`); the specs file path is derivable: `docs/<doc_dir>/specs.json`.

### 6. `src/datasheet_analyzer/query.py` — deterministic lookup (NEW)

```python
@dataclass
class SpecQuery:
    part_dir: Path
    def find(self, *, symbol: str = "", name: str = "",
             section: str = "") -> list[SpecRecord]
    """Case-insensitive substring match on the given fields (ANDed).
    Loads every docs/<doc>/specs.json under the part dir."""

def format_answer(records: list[SpecRecord], limit: int = 5) -> str
    """Human/agent-readable answer rows:
    '<name> (<symbol>): min/typ/max + unit, conditions — §4.5, p.7 [table 0 row 12]'
    Includes footnote text when the row carries cited_markers."""
```

### 7. `src/datasheet_analyzer/cli.py` — additions

- `dsa build` — unchanged behavior + now emits `specs.json` (deterministic,
  adds <1 s). Printed summary gains `, N spec records`.
- `dsa query --part AFE7950 [--symbol ATTstep] [--name "step accuracy"]
  [--section 4.5]` → prints `format_answer` rows; exit 0 if ≥1 record, 1 if none.
- `dsa verify` gains `--specs` flag: for each golden question with
  `spec_query:` set in golden_qa.yaml (see below), run the query and require
  a record whose fields contain all `expected_substrings` AND whose `page`
  is in `pages`. Reported as a second table in the verify output.

### 8. `tests/fixtures/golden_qa.yaml` — extend (do not touch existing entries)

Add to ≥8 of the 12 existing questions a `spec_query` block:

```yaml
    spec_query: {symbol: "DACRES"}          # or {name: "step accuracy", section: "4.5"}
```

Rules: query must be selective enough to return ≤3 records; the matched
record's page must equal the question's cited page. Add 4 NEW
spec-only questions to grow the benchmark:

- q13: min operating voltage of the 1.2V rails → "1.15" (§4.3, p.6)
- q14: PFD frequency range → "100"–"500" MHz (§4.7, p.18)
- q15: SerDes output rise/fall time → "8" ps (§4.8, p.20)
- q16: ESD rating value (§4.2, p.5) — read the real value from the corpus
  when implementing; mark it `kind: direct`.

Update `GoldenQuestion` in models.py: add optional field
`spec_query: dict[str, str] | None = None`.

### 9. `pipeline.py` — wire-in (minimal diff)

After `pin_table_pages` / after loading cached raw (specs derive from
`RawDocument`, so they work identically on fresh and cached extractions):

```python
specset = build_specset(raw, part_number)     # NEW
# ...pass specset into write_corpus via the docs tuple...
```

Regenerate specs on EVERY build: the transform is deterministic and fast
(<1 s), so no spec cache exists to invalidate. If a future phase adds an LLM
to this path, cache by `(content_hash, SPECS_SCHEMA_VERSION, model)` — say so
in a comment.

## Test plan (all hermetic; fixtures already exist)

### `tests/unit/test_roles.py` (new)
- `test_standard_parametric_headers` — `["PARAMETER","PARAMETER","TEST CONDITIONS","MIN","TYP","MAX","UNIT"]`
  → `[symbol, name, conditions, min, typ, max, unit]`.
- `test_nom_maps_to_typ` — 4.3-style `MIN NOM MAX` headers.
- `test_value_and_thermal_metric_roles` — 4.2 `VALUE`, 4.4 `THERMAL METRIC`.
- `test_info_table_classification` — section 3 `PART NUMBER | PACKAGE | PACKAGE SIZE` → `info`.
- `test_unmapped_headers_recorded_not_forced` — a garbage header lands in
  `unmapped_headers`, role `other`.
- `test_all_real_tables_classify` — replay every table from the recorded
  RawDocument (the integration cache JSON or re-parse recorded sections):
  14 parametric + 1 info, zero unmapped headers. **This is the key coverage gate.**

### `tests/unit/test_units.py` (new)
- `test_ohm_sign_canonicalizes` — U+2126 and U+03A9 both → `ohm`, verbatim kept.
- `test_known_units_passthrough` — the full vocabulary above.
- `test_unknown_unit_recorded_verbatim` — e.g. `dBmV` → canonical `dBmV` + flagged.
- `test_normalize_text_dash_space_only` — values normalized, corpus untouched.

### `tests/unit/test_specs.py` (new)
- `test_row_extraction_exact_values` — recorded 4.5 table → records:
  `DACRES typ=="14" unit=="bits"`, `ATTstep after-calibration row typ=="±0.1"`,
  conditions cell exact, `page == 7` (pinned).
- `test_row_footnote_markers_scoped_per_row` — the `850MHz(2)` row has
  `cited_markers == ["(2)"]`, the DACRES row has `[]`.
- `test_footnotes_attached_to_every_record` — all records of 4.5 carry all
  three footnotes.
- `test_page_falls_back_to_section_start_when_unpinned` — honest `None` only
  when the section itself is unpaged (synthetic).
- `test_row_verbatim_roundtrip` — each record's `row_verbatim` reconstructs
  the grid row (provenance anchor).
- `test_empty_rows_skipped`.
- `test_specset_schema_validates` — pydantic round-trip of the real SpecSet.

### `tests/unit/test_query.py` (new)
- synthetic two-doc part dir on disk → `find(symbol=...)`, `find(name=...)`,
  AND-semantics, case-insensitivity, empty result exit path.
- `test_format_answer_has_citation_and_footnote` — contains `§4.5`, `p.7`,
  and footnote text when markers exist.

### `tests/integration/test_phase2_specs.py` (new, marker `integration`)
- Build real AFE7950 (same recorded-HTTP fixture pattern as Phase 1) →
  `docs/datasheet-<hash>/specs.json` exists; ≥150 records (4.5 alone has ~190 rows);
  every record validates; every record's `page` is `None` or within its
  section's manifest range; ≥8 golden `spec_query` checks pass incl. page match.
- `dsa query --symbol ATTstep` CLI smoke test via `cli.main([...])`.
- Regression: Phase 1 golden `verify` still 12/12 (now 16/16 with new questions).

### Update existing
- `tests/integration/test_afe7950_build.py` — extend `test_corpus_shape`
  with `n_specs >= 150`; add specs file existence to `test_every_manifest_file_exists`.

## Execution order (8 tasks, each independently verifiable)

1. models.py additions + SPECS_SCHEMA_VERSION (+GoldenQuestion.spec_query)
2. `structure/roles.py` + test_roles (real-table coverage gate)
3. `structure/units.py` + test_units
4. `structure/specs.py` + test_specs
5. `query.py` + test_query
6. writer/pipeline/cli wire-in + golden_qa.yaml extension
7. integration: real build, all Phase 2 integration tests green
8. `PHASE_2_REPORT.md` (measured: records, coverage, query-answerable golden
   count, tokens/answer vs Phase 1) + AGENTS.md module-table update

## Acceptance criteria (copy into the report)

- [ ] `dsa build` writes `specs.json`; printed summary shows `N spec records`
- [ ] `dsa query --part AFE7950 --symbol DACRES` prints `14 bits — §4.5, p.7`
- [ ] ≥8/12 original golden questions pass `--specs` mode; 16/16 overall
- [ ] 14 parametric + 1 info tables, **0 unmapped headers**
- [ ] 100% records validate; every record page ∈ its section range or `None`
- [ ] `pytest` + `ruff` green; integration build green
- [ ] Tokens per spec answer measured in report (expect ~0.5–2k incl. INDEX.md)

## Explicitly out of scope (do not build)

- Float parsing / numeric comparison of values (verbatim strings only).
- LLM normalization of parameter names (later phase if needed).
- Cross-part comparison, fleet manifest, MCP (Phase 4).
- specs from any future `pdf_text` backend (register maps): html-derived only.
