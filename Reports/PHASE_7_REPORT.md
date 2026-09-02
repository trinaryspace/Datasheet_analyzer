# PHASE 7 — Reach & Trust, as ported onto `feat/gui-workbench`

Phase 7 was implemented on an abandoned parallel lineage
(`feat/phase7-reach-trust`) that had implemented phase 6 differently — its own
`cards/`, `structure/pins.py`, `compare/` and a top-level `provenance.py` where
this branch has a `derive/` package. A merge conflicts in 161 files and would
leave two phase-6 implementations in the tree, so the features are **ported**:
read off that branch, rewritten onto this branch's layout, and **re-measured
here**. Every number in this report was taken on this branch's corpora. Where a
reading differs from the source lineage's report, this one is right about this
tree and that is stated rather than smoothed.

The port runs in batches. Batches A and B (document registry and `dsa fetch`;
revision awareness and staleness; `dsa diff-rev`; errata cross-linking) are
recorded in their commits and in `README.md`, `AGENTS.md` and
`KNOWN_SHORTCOMINGS.md`. This report covers **batch C** (tickets 05 and 06) and **batch D** (ticket 07,
the last feature batch).

---

## Ticket 05 — `dsa audit`: the corpus scorecard and its rubric

Ported from `fed4d26`. `ExtractionStats` told the *builder* how a build went;
nothing told the *agent* whether to trust a corpus before answering. `dsa audit`
is that signal: thirteen readings taken off artifacts the corpus already
publishes, each graded A–F against a checked-in rubric, averaged by weight into
one letter and carried by a one-sentence headline.

### What shipped

| Piece | Where | What it owns |
|---|---|---|
| the rubric, as data | `registry/audit_rubric.yaml` | every threshold, weight and letter, plus a ~120-line comment block justifying each cut point against a reading measured on this repository's eleven corpora |
| the loader | `audit/rubric.py` | `AuditRubric` / `MetricRule`; grading a ratio, grading a named state, averaging letters. Nothing here has a fallback threshold — a metric the file does not carry is not graded |
| the readers | `audit/build.py` | `build_scorecard`, `METRIC_KEYS`, and the `n/a`-vs-zero rule that governs all thirteen |
| the renderings | `audit/render.py` | the per-part scorecard and the fleet table |
| the command | `cli.py::_cmd_audit` | `--part` / `--all` / `--json` / `--min-grade` |

### The measured fleet

All eleven built corpora under `parts/`, graded by `dsa audit --all`, worst
first. These are the grades this branch's corpora actually earn today.

| Part | Grade | Score | Graded | n/a | Worst graded metric |
|---|---|---|---|---|---|
| LHA-83W+ | **C** | 2.44 | 5 | 8 | pin records published: no (D) |
| PSA-8A+ | **C** | 2.44 | 5 | 8 | pin records published: no (D) |
| ZX10R-2-183-S+ | **C** | 2.44 | 5 | 8 | pin records published: no (D) |
| lm741 | **C** | 2.39 | 11 | 2 | records graded high 4 % (F) |
| PMA1-14LN+ | **B** | 2.62 | 7 | 6 | figure axes read 0 % (F) |
| QPA1003P | **B** | 2.74 | 11 | 2 | figure axes read 0 % (F) |
| LMX1204 | **B** | 2.95 | 10 | 3 | mean table fidelity 68 % (D) |
| HMC520A | **B** | 3.09 | 11 | 2 | design cards hold rows: no (D) |
| AFE7950 | **B** | 3.25 | 10 | 3 | alias hit rate 0 % (F) |
| AFE7953 | **B** | 3.30 | 10 | 3 | pin records published: no (D) |
| AD9081 | **B** | 3.39 | 11 | 2 | figure axes read 0 % (F) |

Per metric, across the eleven:

| Metric | AD9081 | AFE7950 | AFE7953 | HMC520A | LMX1204 | QPA1003P | lm741 | LHA-83W+ | PMA1-14LN+ | PSA-8A+ | ZX10R |
|---|---|---|---|---|---|---|---|---|---|---|---|
| section page coverage | 100 % | 100 % | 100 % | 100 % | 100 % | 100 % | 100 % | 100 % | 100 % | 100 % | 100 % |
| table accept rate | 100 % | n/a | n/a | 86 % | 82 % | 83 % | 75 % | n/a | n/a | n/a | n/a |
| mean table fidelity | 88 % | n/a | n/a | 81 % | 68 % | 93 % | 72 % | n/a | n/a | n/a | n/a |
| spec page rate | 100 % | 100 % | 100 % | 100 % | 100 % | 100 % | 100 % | n/a | n/a | n/a | n/a |
| records graded high | 49 % | 54 % | 52 % | 38 % | 22 % | 9 % | 4 % | n/a | 100 % | n/a | n/a |
| pin records published | yes | no | no | yes | yes | no | no | no | no | no | no |
| register records published | no | no | no | no | yes | no | no | no | no | no | no |
| design cards hold rows | yes | yes | yes | **no** | yes | no | yes | no | no | no | no |
| figure axes read | 0 % | 78 % | 76 % | 39 % | 68 % | 0 % | 0 % | n/a | 0 % | n/a | n/a |
| errata items placed | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| alias hit rate | n/a | 0 % | 40 % | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| revision freshness | unknown on all eleven | | | | | | | | | | |
| golden pass rate | 100 % | 100 % | 100 % | 100 % | n/a | 100 % | 100 % | n/a | n/a | n/a | n/a |

**Stated plainly.**

- **lm741 grades C, and it should.** It publishes 70 spec rows and grades 3 of
  its 73 graded records `high`: 4 %, an `F` on the heaviest non-golden weight.
  That is the true reading of a corpus whose every parametric value needs the
  printed page opened, and curving it would defeat the metric.
- **The three Mini-Circuits parts grade C on five metrics out of thirteen.**
  LHA-83W+, PSA-8A+ and ZX10R-2-183-S+ publish no specs, no plots, no pins, no
  registers and no card rows — their datasheets are two to five sections of
  prose and a table this pipeline rejects. Eight metrics report `n/a` and are
  excluded; the five that can be read are graded, and the `C` is the honest
  reading of a corpus that can answer almost nothing.
- **PMA1-14LN+ reads `records graded high 100 %` over a denominator of two.**
  That is why the scorecard prints the counts beside every percentage: a rate
  over two records and a rate over eight hundred are different claims.
- **AD9081, QPA1003P, PMA1-14LN+ and lm741 read 0 % figure axes.** Their
  figures are raster plots whose axes exist only as pixels; the catalog
  attempted a reading and could not make one. That is `LOW`, not `UNKNOWN`, and
  therefore a graded `F` rather than an `n/a` — the distinction the axis metric
  was built on.
- **HMC520A publishes no design-card rows at all**, and is graded down for it.
  It is a real finding, not an error.
- **`revision freshness` is `unknown` on all eleven**, correctly: no corpus
  here has been checked against a live upstream. `unknown` grades `C`, not `A`
  — ticket 02's asymmetry, now on a scorecard — so every part carries that `C`
  today and the fleet's grades will rise once `dsa check-revisions` has run.
- **`errata items placed` is `n/a` everywhere**, because no part registers an
  errata document. `n/a`, never 100 %: silence is not a clean bill of health.

### Two departures from the source lineage, both deliberate

**`table_pin_rate` is not published here.** It divides
`CorpusStats.tables_pinned` by `n_tables`, and this branch's publisher records
no pinning count — a table's printed page is stamped on the `TableBlock` at
construction and never carried into the manifest. Reading that absence as
"0 tables pinned" is exactly the defamation the `n/a` rule forbids, and
recording the count would mean rebuilding every corpus in the repository. A
scorecard row that can never say anything is noise, so the metric is absent
rather than permanently `n/a`, and the reason is in `KNOWN_SHORTCOMINGS.md`
with what would close it.

**`errata_link_rate` is published in its place**, which that lineage had no
errata linker to compute. The decision was open: `ErrataTarget` is structurally
a derived value (source ref + page + rule + grade) but is not a `DerivedValue`,
so `check_provenance` / `iter_derived_values` do not walk `errata_links.json`,
and it was fair to ask whether the audit should cover errata at all. It should,
for three reasons. First, the audit does not walk the link set either — it
reads two published counts and carries its own `source` and `derivation` like
every other metric, so the provenance gap is not a gap *here*. Second, an item
that names no record is a known issue an agent will answer around while
silently omitting, which is precisely the class of fact a trust signal exists
to put in front of an answer; nothing else in the scorecard would ever mention
it. Third, the ingredients were already on disk from batch B
(`CorpusStats.n_errata_items` / `n_errata_linked`, and `errata_links.json`'s
own `links` / `unlinked` lists, which is what the metric actually reads,
because it is the artifact a consumer would find). The cost is that the metric
cannot discriminate today — every part reports `n/a` — and its cut points are
therefore placed by argument rather than by reading, which the rubric says out
loud.

### The reviewer note this port fixed rather than reproduced

`_mean_fidelity` conflated a measured 0.0 with "never computed" and stated a
backend fact it had not checked. Availability now comes from the recorded
backend and from whether that backend accepted a table to score, so a
`pdf_layout` corpus that really reconstructs at 0 % grades `F` instead of
hiding behind the sentence written for a backend that computes no fidelity at
all. Three tests (`TestAMeasuredZeroIsAReading`).

The second note — that the `--min-grade` comparison branch was never exercised
by a *graded* part below the floor — is closed by
`TestTheCommand::test_a_graded_part_below_the_floor_exits_one`.

### The rubric's calibration, re-anchored

Every cut point was re-read against the fleet above rather than carried over.
Only one moved: `axis_coverage`'s `A` from 0.45 to 0.75, because this fleet's
best reading is 78 % and four corpora read 0 %, so leaving `A` where it was
would have handed an `A` to a corpus reading less than the median. That change
lowers two grades on the metric (LMX1204 A→B, HMC520A B→C) and moves no overall
letter, which is the direction a recalibration should go. Every other threshold
still fits its measured spread and is left alone, with the readings it was
placed against recorded in the file.

---

## Ticket 06 — `dsa golden suggest|confirm`

Ported from `9be58d5`. Invariant 5 is the right objective function and it does
not survive sixty parts of hand-verification. This ticket removes the typing
and leaves the judgment exactly where it was.

**The clause invariant 5 gains:** *a generated candidate counts toward nothing
until a human confirms it.*

### What shipped

| Piece | Where | What it owns |
|---|---|---|
| the two files and their rules | `evalh/candidates.py` | `golden_qa_<PART>.candidate.yaml` and `golden_qa_<PART>.rejected.yaml`; `question_to_dict` is the single place a golden question becomes YAML |
| generation | `evalh/suggest.py` | four named templates (one per artifact), the recursive stratified order, the pool and the **refused population** |
| the decision | `evalh/confirm.py` | `apply_decisions` (the pure core), `merge_into_golden` (append + validate-before-write), `page_context` / `render_candidate` (the glance), `run_interactive` (the thin shell) |
| the command | `cli.py::_cmd_golden` | `golden suggest` / `golden confirm`, the paths and the exit codes |
| where a benchmark lives | `evalh/golden.py` | `default_golden_path` / `golden_dir()`, honouring `DSA_GOLDEN_DIR` |

### Adapted to this branch's `GoldenQuestion`

There is no `pin_query`, `reg_query` or `card_query` here. A pin candidate is
`ask_query: {route: pin}` and a register candidate `{route: register}` — the
shape `evalh/citations.py` documents and `golden_qa_AD9081.yaml` already uses.
`CorpusIndex` carries specs and plots only, so pins and registers are read off
the published `pins.json` / `registers.json` beside each document. `source` is
composed against `index.reference_base(doc)`, so a document published once into
the shared library store is cited `@library/docs/<doc>/specs.json#<id>`; every
candidate on every part resolves through `derive.provenance.resolve_source`
(0 unresolvable of 140 checked).

### The three defences of invariant 5

The name, the shape (`candidates:`, no `questions:` key at all), and the
refusal (`load_golden` rejects a candidate file *by name*; `dsa verify --golden
<candidate>` exits 2). Asserted with a **control**, which is the part that
makes the assertion mean something: the same `dsa verify` run is compared
before and after generation (stdout byte for byte, exit code included) and must
be identical — and then one candidate is confirmed and the report must *grow*.

### How good the proposals are

Twenty candidates per part, all accepted unread into a scratch benchmark under
`.scratch/`, then verified. Nothing filters a candidate by whether it would
pass — that would fit the proposals to the checker rather than to the document.

| Part | corpus-side | page-truth-inclusive |
|---|---|---|
| AD9081 | 20/20 text, 7/7 spec, 6/6 plot, 7/7 ask | 20/20 |
| AFE7950 | 20/20 text, 10/10 spec, 10/10 plot | 20/20 |
| AFE7953 | 20/20 text, 10/10 spec, 10/10 plot | 20/20 |
| HMC520A | 20/20 text, 7/7 spec, 6/6 plot | 20/20 |
| LMX1204 | 20/20 text, 5/5 spec, 5/5 plot, 4/5 ask | 19/20 |
| lm741 | 20/20 text, 17/17 spec, 3/3 plot | 19/20 |
| QPA1003P | 20/20 text, 16/16 spec, 4/4 plot | 18/20 |

**136 of 140 page-truth-inclusive.** The four failures are one shape and all
the reviewer's job: a printed identity composed from cells that never appear
contiguously on the page — `Input adjustment range` (lm741 p.5), `Input Power
(P VD = +28 V, I` twice (QPA1003P, where the name cell wrapped mid-print), and
`Figure 8-4 DC-Coupled Differential Input` (LMX1204). That is a candidate to
edit or reject, and it is also a measurement of how often a table's identity
cell is a join rather than a quote.

**LMX1204's page-truth number needs one caveat about `dsa verify`, not about
the candidates.** It is a two-document part, and `--pdf` takes one file. Its
register candidates come from the register-map document and pass against
`LMX1204_registermap.pdf`; checked against `lmx1204.pdf` they read as three
failures. The table above checks each question against the document it was
templated from. The one-PDF limitation is pre-existing and is not touched here.

**The source lineage's AFE7950/AFE7953 finding does not reproduce.** It
reported 0 spec/pin/register candidates for both because their records predated
ADR 0005 record ids. On this branch those corpora carry ids and yield 608 and
526 templatable spec records (plus 514 and 492 plots) respectively. On this branch only a **plot** can
be unaddressable at all: `SpecRecord.id`, `PinRecord.id` and
`RegisterRecord.id` are computed fields that `derive.provenance` reconstructs
for a legacy file, while `PlotRecord.id` is stored.

### A finding about the tool that generation surfaced

The ask router names a pin by an upper-case designator lifted out of the
question text (`retrieve.pack.PIN_DESIGNATOR_RE`). **A datasheet that numbers
its pins `1..40` therefore cannot reach the pin route by asking about a pin at
all**: all five LMX1204 pin candidates routed `search`, and `dsa ask --part
LMX1204 "Which signal is on pin 20?"` still does. The generator now withholds
`ask_query: {route: pin}` for such a designator and records why on the
candidate — a path marker is a claim about the tool, and where it cannot be
true it is left off rather than asserted, the same rule a derived artifact
follows when it cannot fill a field. The router gap itself is untouched and
belongs to whoever owns the ask path next.

### The seven reviewer notes, and what was done about each

| # | Note | Disposition |
|---|---|---|
| F16 (HIGH) | `merge_into_golden` wrote the file and *then* re-parsed it, so unparsable YAML raised before the rollback guard and left the benchmark corrupted | **Fixed.** The merged text is parsed and compared **in memory**; the file is opened for writing only after every check passes. A post-write re-read with rollback is kept as a second line of defence. A benchmark that already does not parse is refused rather than appended to. 3 tests |
| F17 (HIGH) | A newly created golden file was stamped "Every answer below was checked against the printed page before it landed here" unconditionally — including for a bulk run where no page was shown | **Fixed.** `merge_into_golden` takes the provenance of the decisions and writes that: `PROVENANCE_PAGE` only for a `--pdf` walk, `PROVENANCE_CORPUS` for a walk with none, `PROVENANCE_BULK` — the default — for `--accept-ids` / `--decisions`. The forged sentence is asserted *absent*. 6 tests |
| 3 | The empty-pool note misreported its cause on a legacy corpus, and a stale corpus silently yielded the degenerate set box 1 exists to prevent | **Fixed.** Refusals are counted per artifact and per reason; the note names the reason that actually refused the most records, with its count. A corpus with unaddressable records also gets an explicit "N record(s) carry no id … needs a rebuild" line, and one published at an older pipeline version says so |
| 4 | Untemplatable records were dropped silently; the documented claim that they are "counted" was not implemented (ADR 0005's unparsed-population clause) | **Fixed.** `GoldenCandidateSet.refused` (additive) carries the full population by artifact and reason; `dsa golden suggest` renders it as its own table. Measured: AD9081 refuses 344 records, 268 of them because the row prints no name or symbol to ask about |
| 5 | The merge rollback guard and the reindent logic had zero test coverage | **Fixed.** Both tested, the reindent on both indentation styles this repo's files use, the guard by forcing a merge that would move an existing question |
| 6 | The stratification helper is vacuous on a constant list, so the test named for the degenerate generator would not catch it | **Fixed.** The round-robin property is asserted at the level it is actually claimed for (artifact globally, confidence within each artifact — it is a recursive stratification, not a flat one, and the source's flat assertion was asserting something the design never promised), plus an explicit non-vacuity assertion, plus the skewed corpus a flat pass gets wrong: twelve spec rows over six tables against two pins, `--n 4`, must draw two pins |
| 7 | No test checked that the page text appears in what `confirm` shows | **Fixed.** Two: a sentinel string pushed through `page_context` into `render_candidate`, and the same through the interactive shell's injected writer |

### `dsa golden confirm` cannot reach the real benchmarks

The hazard is specific: `confirm` writes `tests/fixtures/golden_qa_<PART>.yaml`,
which is this repository's objective function, and the CLI resolved that path
from a module constant. Three things now stand between a test and that file,
and all three are asserted:

1. **The path is a setting.** `Settings.golden_dir` (`DSA_GOLDEN_DIR`, default
   empty = the repo's `tests/fixtures`) is read by `evalh.golden.golden_dir()`,
   which `default_golden_path` resolves through and which
   `cli._default_golden_path` delegates to. Nothing else composes the path.
2. **The suite points it somewhere else, for every test.** `tests/conftest.py`
   sets `DSA_GOLDEN_DIR` to a per-test temporary directory in the same autouse
   fixture that already redirects `DSA_PARTS_DIR` and `DSA_LIBRARY_DIR` — the
   fixture batch B added after a prototype run wrote into the repo's real
   `library/`. The one test that legitimately exercises *discovery* against the
   committed benchmarks takes a `committed_golden_dir` fixture and only reads.
3. **The bytes are checked.**
   `TestNothingHereCanReachTheRealBenchmarks::test_every_committed_benchmark_is_byte_identical_after_all_of_that`
   shells out to `git status --porcelain -- tests/fixtures` and fails naming
   any benchmark a test touched, and a sibling asserts no `.candidate.yaml` or
   `.rejected.yaml` was left beside them.

Verified three ways beyond those tests: `git status --short tests/fixtures/`
was clean after every test run in this batch; the proposal-quality measurement
above ran with `DSA_GOLDEN_DIR` pointed at `.scratch/p7batchC/goldenq` and its
output was deleted afterward; and `git diff --stat` across all three commits of
this batch touches no file under `tests/fixtures/`.

---

## What remains unrunnable offline

Nothing in batch C needs a network to *run* — both commands read only what the
corpus already publishes, and no model call appears in either path. What cannot
be **exercised** here:

- `revision_freshness` grading `current` or `stale`. Every corpus reads
  `unknown` until `dsa check-revisions --all` has run against a live upstream
  (ticket 02's deferred step). Only synthetic fixtures reach the other two
  states.
- `errata_link_rate` reading anything at all. No part registers an errata
  document, so it is `n/a` on all eleven and its cut points are uncalibrated.
- `alias_hit_rate` above 40 %. Only two benchmarks ask a name-keyed spec
  question; nothing here has read higher.
- A **human** confirming a generated candidate. That is the whole point of the
  ticket and it is not something a machine can do on its own behalf: no
  generated question was committed to `tests/fixtures/`.
- Rebuilding AFE7953 (needs the TI document viewer) — unchanged from phase 5.

## The gate, measured

`.venv/Scripts/python.exe -m pytest tests/ -q` offline, twice, on the final
tree: **2806 tests, 2772 passed, 0 failed, 0 errors, 34 skipped**, 449 s and
452 s. The branch's pre-batch baseline was 2673 passed / 0 failed / 34 skipped,
so batch C adds 131 tests (49 in `tests/unit/test_audit.py`, 80 in
`tests/unit/test_golden_assist.py`, 2 parametrizations in
`tests/unit/test_cli_json.py`) and skips nothing new. `ruff check .` and
`ruff format --check .` clean over 340 files. `git status --short
tests/fixtures/` empty after every run.

No `PdfLayoutBackend.output_version`, `STRUCTURE_STAGE_VERSION` or existing
schema version moved, and no corpus was rebuilt: every grade above was read off
the corpora as they stand at pipeline 0.5.0.

## Deliberately not ported

- **MCP `get_audit`.** The source lineage shipped the scorecard as a
  fourteenth MCP tool. Batch C's brief named the `audit/` package, the rubric
  and the `dsa audit` CLI verb, and not the MCP surface, so it is not here:
  `mcp_server/responses.py` declares no `get_audit` schema and
  `test_mcp_server.py`'s whole-surface caps are untouched. Adding it is
  additive and small — `build_scorecard` already returns a model, and the
  headline is the sentence an agent would answer with — but it changes the
  declared tool count, which is asserted in two places, and that belongs in a
  batch that owns those assertions.
- **`AGENT.md` and the `datasheet-corpus` skill do not mention `dsa audit` or
  `dsa golden`.** The same standing gap phase 6 recorded for its own tools.
  Not a criterion of either ticket.

## What batch D should know

- **`dsa audit` is where a families/compare adapter's own trust signal belongs.**
  The scorecard is built per part; a family or a comparison spans several, and
  the honest reading of a cross-part artifact is bounded by the *worst* corpus
  in it. `audit.render.grade_order` is the one definition of "worse" and
  `audit.build.build_scorecard` takes a part directory, so a family view can
  compose them without re-deriving anything.
- **`METRIC_KEYS` is thirteen and the rubric grades exactly those thirteen**,
  asserted both ways in `test_audit.py`. Adding a metric means adding a reader,
  a key, a rubric entry and a line in `TestEveryMetricIsGraded.EXPECTED`.
- **`PartComparison` already carries `card_version` and an `unparsed` list.**
  The compare adapter should not need a new honesty channel; the
  unparsed-population clause has a home.
- **`GoldenCandidateSet.refused` is the shape to copy** for any new selector
  that refuses records. It is `{artifact: {reason: count}}` and the reasons are
  module constants, so a file and its module use the same words.
- **Do not assert a path marker a route cannot take.** The pin lesson
  generalizes: `retrieve.pack` exports `PIN_DESIGNATOR_RE` and
  `RECORD_IDENTIFIER_RE` for exactly that check.
- **`--json` verbs are held to a table.**
  `test_cli_json.py::test_every_json_verb_is_exercised` compares the parser's
  `--json` list against `JSON_INVOCATIONS`; `audit` and `golden suggest` are in
  it now, and a new one must be added there or the test fails.
- **`test_scope_seam.py` forbids the identifier `part_dirs` in `cli.py`.** It
  is a grep-shaped guard against a front end building its own project scope;
  `_cmd_audit`'s `--all` loop calls its local `targets` for that reason.

---

# Batch D — ticket 07: part families

Ported from `3022f28`. The direct answer to *"become an expert on a series of
parts"*: `registry/families.yaml` declares who is in a family, `dsa family
build` writes `families/<NAME>/FAMILY_INDEX.md` with the shared sections listed
**once** and only the differences tabulated, and `dsa ask --family` returns a
finding every member printed identically once and flags the members that differ.

**The rule the whole ticket turns on:** *membership is declared, never
inferred.* A family index says "this section is identical in every member — read
it once", and a wrong member makes that sentence a lie a designer cannot see. So
the suggester may only **propose**.

## What shipped

| Piece | Where | What it owns |
|---|---|---|
| membership | `families/registry.py` + `registry/families.yaml` | `FamilyEntry` / `FamilyRegistry`, the candidate file refused **by name**, `resolve`'s two refusals (`FamilyMiss`, `FamilyUnconfirmed`), each naming its fix |
| the proposal | `families/suggest.py` | part-number stem + section-map Jaccard overlap, both above a floor; every proposal `confirmed: false` |
| the derivation | `families/build.py` | section alignment (number, then printed title), the spec/pin/register/bit-field delta rows, the counts and the refusals |
| the rendering | `families/render.py` | `FAMILY_INDEX.md` under a hard token budget with nine stages of degradation |
| the files | `families/store.py` | `families/<NAME>/FAMILY_INDEX.md` (bounded) + `family.json` (complete) |
| the question | `retrieve/family.py` + `pack.build_family_pack` | `FamilyRetriever` (a `ProjectRetriever` by composition), `load_members`, and the shared/divergent collapse |
| the command | `cli.py` | `dsa family list\|suggest\|confirm\|build`, and `--family` as the third scope beside `--part` / `--project` |
| the scope | `retrieve/scope.py` | `resolve_family`, `unbuilt_family_members`, and `resolve_scope`'s additive `family=""` |
| the models | `models.py` | `FamilySection`, `FamilyIndex` (from the seam), now typed on `CompareRow` |

## The comparison seam, and the duplication it exposed

Ticket 07 is the only phase-7 feature that needs the comparison engine, which is
why it was left last. The source drove it through `compare/build.py`'s
`build_spec_comparison` with a `key_for=` hook that ticket added there. This
branch spells comparison in `derive/compare.py` — `compare_specs`, `Comparison`,
`CompareRow`, `CompareCell` — and had no hook.

**The hook, ported additively.** `compare_specs(..., key_for: SpecKeyFn)`
replaces exactly two things: the join key a spec record offers, and the row's
`matched_on` sentence. Nothing else. The four join rungs, the
exactly-one-free-row-per-part rule, the refusal of an ambiguous key, the SI
delta and the parse population are untouched, and `_Candidate.aligned_on`
defaults to `""` so `_matched_on` reaches its four original sentences on every
row `dsa compare` builds.

**Proof `dsa compare` is unchanged**, measured rather than argued: the full
`compare_specs` payload over the committed AFE7950 + AFE7953 corpora was dumped
before the change and after it and diffed — **byte-identical**, 742 rows (408
aligned, 31 present in one part only, 303 unaligned, 415 deltas), every
`matched_on` string included — together with a `--symbol TJ` comparison and its
rendered markdown. The diff was re-run after the model move below and was
identical again. `tests/unit/test_compare.py` is untouched and green.

**Why a family cannot use the alias key.** `dsa compare` aligns two *unrelated*
parts on the alias-resolved symbol, because that is what makes `TJ` and
`Junction temperature` one row. A family's members are one vendor's one document
template, so an alias key folds `IVDD1P8` and `IVDD1P2` onto one bucket and then
refuses them both as ambiguous. The family key is therefore
`(family section, printed symbol, printed name, printed conditions)`, compared
character for character after the shared `normalize`.

**The alignment numbers, measured here.** The source report claims 83 aligned
rows on the alias key against 318 on the printed-row key. Neither reproduces —
this branch's corpora carry record ids the source lineage's did not:

| Key | Aligned rows | Identical | In the delta table |
|---|---|---|---|
| alias-resolved symbol (`dsa compare`) | **408** | — | 415 deltas computed |
| printed row inside the family section | **763** | 379 | 384 |

The relation the hook exists for holds — the printed-row key is strictly finer
and pairs strictly more — and
`test_the_printed_row_key_aligns_more_here_than_the_alias_key_would` asserts
that relation rather than either number.

## The duplicated comparison model, resolved

The batch seam had added `ComparisonCell` / `ComparisonRow` / `PartComparison`
to `models.py` while `derive/compare.py` already published this branch's
`CompareCell` / `CompareDelta` / `CompareRow` / `Comparison`. Two comparison
models in one tree is a defect.

**The live ones win, and all three speculative ones are deleted.** Checked
before deleting: nothing in this tree referenced them except the `FamilyIndex`
the same seam added; `retrieve/revdiff.py` names `PartComparison` only in prose;
the only other hits were under `.claude/worktrees/`, which is the other lineage's
tree and not this one.

`FamilyIndex.deltas` must therefore hold `CompareRow`, and `models.py` cannot
import from `derive/compare.py` (that module imports `models`), so
`CompareCell` / `CompareDelta` / `CompareRow` **moved into `models.py`** — beside
`RevisionChange` and `FamilySection`, which is where every other derived-row
model on this branch already lives — and `derive/compare.py` imports and
re-exports them. Its `__all__` is unchanged, so no importer sees a difference,
and the byte-identical payload diff above was re-taken after the move.

Adapting families to `CompareRow` cost four shape changes, all recorded in
`families/build.py`: `cells` is a dict keyed by part rather than a list; a delta
is a `CompareDelta` on the row rather than a `delta` on each cell; `aligned_on`
is `matched_on`; and the source's `ambiguous_in` / `note` become
`not_comparable` lines plus `status` / `flags`, which is the field `dsa compare`
already writes its own refusals into. `CompareRow` has no `group`, so the family
section rides in the join key behind a unit separator (`\x1f`, the one byte a
printed symbol cannot contain) and `families.section_of` reads it back; a test
asserts that separator never reaches the rendered page.

## The refusals, which are most of the design

- **A section is shared only when it is identical everywhere** — same printed
  title in every member, byte-identical body in every member, with the
  `<!-- source: ... -->` provenance line and the `# N Title` heading removed
  first (they name each member's own revision, pages and section number and
  would make every section divergent for a reason that is not about the device).
- **`partial` is not `divergent`.** "Some member does not print this section at
  all" is a different fact from "every member prints it and something moved",
  and only the first is an absence.
- **A section aligns on its printed number, then on its printed title, and
  nowhere else.** AFE7950 numbers its back matter §6.x and AFE7953 §5.x; the
  title rung folds those into one section (measured: the five support sections)
  and refuses to fold anything whose printed titles differ.
- **A pin name, a register reset and a bit range are never scored.** Quoted on
  both sides with no delta, no sign and no direction — `revdiff` refuses a reset
  for the same reason, and it bears restating: a signed difference between two
  bit patterns is a number that means nothing and looks like it means something.
  A bit field is its own row rather than a cell of its register's, so "3
  registers differ" can never silently mean "3 bit fields inside one register
  do".
- **An empty pin delta table is ambiguous, so it is never left to speak for
  itself.** The notes state what each member publishes either way.
- **A declared member with no corpus is named**, not dropped.

## The token win, measured

Both readings are on the corpora committed under `parts/`, rendered **under**
the 4000-token budget that ships — a bound you did not apply is not a result:

| Sections | Shared | Spec rows aligned | Identical | Delta rows | Refusals listed | `FAMILY_INDEX.md` | Σ member `INDEX.md` | Ratio |
|---|---|---|---|---|---|---|---|---|
| 39 | 14 | 763 | 379 | 384 | 461 | **2290 tok** | 4758 tok | **0.481** |

The other half of the win is the one the ticket names: **3664 tokens** of
section body are identical across both members and are listed once rather than
twice.

The 461 refusals break down, and every one of them is a line carrying the
printed values: 360 keys only one member publishes, 16 keys one member prints
several rows under, 43 printed pairs whose two sides did not read into the same
unit, and 42 rows (21 per member) whose printed cell the numeric layer could
not parse at all. 360 + 16 + 43 + 42 = 461, and 379 + 360 + 16 + 8 = 763.
The arithmetic closes, which is the point of printing it.

## The suggester proposes and nothing else

`dsa family suggest` reads only built corpora, groups by shared part-number stem
**and** section-map Jaccard overlap ≥ 0.8, and writes
`registry/families.candidate.yaml` — a different filename, a `candidates:`
top-level key, `confirmed: false` on every entry, and a header that says so. It
is defended three ways, each asserted:

1. `load_families` refuses that filename outright (before parsing, so the check
   cannot depend on the proposal being well-formed);
2. `load_candidates` forces `confirmed: False` whatever the file says, so a
   hand-edited proposal cannot confirm itself;
3. `resolve` refuses an unconfirmed entry even inside `families.yaml`, naming
   `dsa family confirm <NAME>` — and the `--family` scope goes through the same
   `resolve`, so the CLI cannot route around it.

`TestSuggestOnlyProposes::test_an_unconfirmed_suggestion_builds_nothing_through_the_cli`
runs the whole loop: suggest → `family build` exits 2 → no `families/<NAME>/`
directory exists. `test_confirm_moves_it_across_and_then_it_builds` shows
`--dry-run` still builds nothing.

## `dsa ask --family`

The third scope, beside `--part` and `--project`. `FamilyRetriever` is a
`ProjectRetriever` by composition — every fan-out a design needs, a series needs
identically — and the one thing a family adds is the answer rule:

- a finding **every** declared member produced, **character for character**, is
  returned once, carrying `shared_with` and the reference member's citation;
- anything else is returned per member, `shared: false`, with one `divergence`
  line per member under a `### Per-member differences` heading placed
  immediately below the answer.

Character-for-character is the whole strictness: `1.35 A` and `1350 mA` are the
same magnitude and are not the same printed answer. A member that answered
**nothing** is a divergence, not an abstention.

`AnswerPack` gains `family` / `shared` / `divergence` and `PackLine` gains
`shared_with`, all additive, all in `ANSWER_PACK_SCHEMA`, all empty on a
single-part **and** on a project pack (both asserted).

`SCOPE_ERROR` is left **character for character** as ADR 0006 worded it —
`test_scope_seam.py` holds it to that — and the three-scope refusal
(`FAMILY_SCOPE_ERROR`) widens the list while reusing that rationale clause
verbatim rather than re-wording it. One rationale, written down once.

## What did not reproduce from the source report

Three claims, each re-measured here and each different:

- **"619 of 619 AFE7950 spec records carry no addressable record id."** False on
  this branch: `SpecRecord.id` is a computed property and all 619 (and all 536
  of AFE7953's) carry one. The committed corpora are citable and the family
  index over them is real, which is why the integration test uses them rather
  than rebuilding both members.
- **The hand-verified delta `IVDD1P8 / Group 3C: VDD1P8PLL + / 12.6 mA vs
  16 mA`.** Does not exist here. Both members print
  `Group 3C: VDD1P8PLL + VDD1P8PLLVCO`, but under *different operating modes*,
  so nothing pairs on the printed row. That reading came off a layout-floor
  rebuild whose row names differ from these corpora's.
- **"83 aligned rows on the alias key vs 318 on the printed-row key."** Measured
  here: 408 and 763.

What is confirmed unchanged: **the reference family publishes no pins and no
registers**, because neither AFE795x datasheet prints a table this repo can read
as one. The index states that absence in words rather than implying agreement,
and the pin/register/bit-field delta paths are proven on synthetic corpora.

## Hand-verified against the printed datasheets

Two findings, checked against the *printed page* of each PDF rather than against
the corpus that produced them:

| | AFE7950 | AFE7953 |
|---|---|---|
| **shared** — §4.1 `Peak Input Current` | `20` (max), p.4 | `20` (max), p.4 |
| **only-in** — §4.9 `IVDD0P9`, `Mode 10: 4T4R2F` | `3578.9` (typ), p.25 | printed on **no page** |

The second is the interesting one: AFE7950 is the quad-transmitter device and
AFE7953 the dual, so `4T4R2F` appears nowhere in afe7953.pdf — and the test
proves that by reading **all 134 of its pages**, not by trusting its corpus. An
absence is the finding a series reader is asking about, and it is the one thing
a corpus cannot be taken at its word for.

## Shortcomings, honestly

- **The reference family computes no `si_delta` at all** — 0 of 763 aligned
  rows. Three separate causes, only one of which is about the devices: 379 rows
  agree; 376 are only-in or ambiguous because the two devices sweep different
  operating modes; and the 8 rows that align *and* differ do so by **column**
  (`t(SCLK)_R = 50` under `typ` in one corpus and under `max` in the other),
  which `si_delta` refuses to subtract and lists under "not comparable" with
  both verbatim values. Recorded in `KNOWN_SHORTCOMINGS.md` with what would
  close it.
- **An ambiguous key is refused whole here, not per part.** This branch's join
  pairs a key only where it names exactly one free row in *each* part that has
  it, so a member printing two rows under one printed identity leaves every
  candidate under that key unpaired. The source lineage refused per part and let
  the unambiguous members still compare. This is stricter, not weaker, and it is
  this branch's `dsa compare` behaviour rather than a family decision — changing
  it would change `dsa compare`, which this batch was not permitted to do.
- **The delta table is capped under a tight budget** (60 → 25 → 10 rows), says
  so, names `family.json` as the complete copy, and orders rows so the cap drops
  the least informative last.
- **A family is not a corpus.** `families/<NAME>/` is written by its own command
  and is no part of any part's publish cache key; rebuilding a member does not
  refresh a family index, and nothing pretends otherwise.
- **No MCP surface, and no GUI surface.** The plan lists `list_families` and
  `get_family_index`; they are not in this ticket's acceptance criteria and did
  not ship. `app/deps.py::get_retriever` still resolves `part` / `project` only.

## What remains unrunnable offline

Nothing in ticket 07 needs a network to *run*: `dsa family build` and
`dsa ask --family` read only what the member corpora already publish, and no
model call appears in either path. What cannot be **exercised** here:

- **A computed delta on the reference family** — see the shortcoming above. It
  needs either a closer family or both members rebuilt through one backend
  (~6 min; a single `--vendor unknown` build of afe7950.pdf measured 181 s), and
  a rebuild changes every other measured reading in this repository.
- **The pin, register and bit-field delta paths on a real family.** Neither
  AFE795x member publishes a readable pin table or register map.
- **A family of more than two members.** `_record_deltas` and `_collapse` are
  N-way by construction and are tested at N=2 only; no third AFE79xx corpus
  exists here.
- **A human confirming a proposal into the shipped `registry/families.yaml`.**
  `AFE795x` was confirmed by hand in the port; every test that confirms writes
  into a tmp `registry_dir`, never the checked-in file.

## The gate, measured

`.venv/Scripts/python.exe -m pytest tests/ -q` offline, on the final tree:
**2879 tests, 2845 passed, 0 failed, 0 errors, 34 skipped**, 446 s. The
pre-batch baseline was 2806 tests / 2772 passed / 0 failed / 34 skipped, so
batch D adds **73 tests** — 54 in `tests/unit/test_families.py`, 17 in
`tests/integration/test_phase7_families.py`, 2 parametrizations in
`tests/unit/test_cli_json.py` (`family list --json`, `family build --json`) —
and skips nothing new. `ruff check .` and `ruff format --check .` clean over
350 files.

`git status --short -- families` and `-- tests/fixtures` are both empty after
the run, which is the point of the isolation fix in `524257e`.

No `PdfLayoutBackend.output_version`, `STRUCTURE_STAGE_VERSION` or existing
schema version moved, and **no corpus was rebuilt**: every number above was
read off `parts/` as it stands at pipeline 0.5.0. `FAMILY_SCHEMA_VERSION` is
`"1"` and is no part of any publish cache key — a family index is derived live,
like a comparison and a scorecard.

## Commits

| | |
|---|---|
| `3e89c37` | `families/registry.py`, `families/suggest.py`, `registry/families.yaml` — membership, and a suggester that may only propose |
| `28f1a49` | the `key_for=` hook on `derive/compare.py`, and the comparison-model duplication resolved |
| `32198bd` | `families/build.py`, `render.py`, `store.py`, `retrieve/family.py` |
| `78384f0` | `build_family_pack`, the third scope, `dsa family list\|suggest\|confirm\|build` |
| `35fc89c` | 52 unit tests + 17 integration tests, every number re-measured |
| `524257e` | a family build must not write into the repository it is tested from |

## What the integration stage must still wire up

- **`--family` on the other scoped verbs.** `_add_scope` now offers all three,
  so `dsa query --family`, `dsa search --family` and `dsa plots --family`
  already resolve and answer — but the *family* answer rule
  (`build_family_pack`'s common-once collapse) exists for `ask` only. The other
  verbs fan out like a project and label each hit with its part, which is
  correct but is not the family reading. Deciding whether they should collapse
  too is an integration call.
- **MCP.** `list_families` / `get_family_index` are not declared, and
  `mcp_server/server.py::resolve_scope` still passes two arguments. Adding the
  scope is one keyword; adding the tools changes the declared tool count, which
  is asserted in two places.
- **The GUI.** `app/deps.py::get_retriever` takes `(part, project)`;
  `app/routers/chat.py::resolve_scope` is the HTTP surface for the same
  decision. Both are additive one-liners against `retrieve.scope.resolve_scope`,
  which already takes `family=`.
- **`AGENT.md` and the `datasheet-corpus` skill do not mention `dsa family`.**
  The same standing gap phase 6 and batch C recorded for their own tools.
- **Nothing decides whether `families/` is committed.** It is untracked and
  un-ignored, exactly as `projects/` is, so a built family index currently
  lives only on the machine that ran `dsa family build`. Whether the repo
  should carry `families/AFE795x/` the way it carries `parts/` is an
  integration decision, not this batch's. What *is* settled here: no test can
  write one into the tree by accident — `conftest._point_dsa_at` exports
  `DSA_FAMILIES_DIR` and `TestNothingHereWritesIntoTheRepository` asserts
  `git status --porcelain -- families` is empty.

---

# Integration — the seams the four batches left

Every item under "What the integration stage must still wire up" above is
closed here, and the two entries in batch C's "Deliberately not ported" are
closed with it. Commits `ae5f93a`…`96f7379` on `feat/gui-workbench`.

## The MCP surface: thirteen tools to sixteen, and a third scope on four of them

`get_audit`, `list_families` and `get_family_index` are declared, and the
tool-count assertions moved with them — a set that says thirteen when sixteen
are registered has stopped describing the server. `test_mcp_server.py` carries
sixteen entries in its declared-tool set, in `ALL_CALLS` and in the duplicate
parametrize table, so no cap assertion can skip a tool.

| tool | default 6000-token cap, fixture corpus | at 400 | at 40 |
|---|---|---|---|
| `list_families` | 174 tok | fits | `over_cap`, announced |
| `get_family_index` | 575 tok | sheds to 399, `truncated` | `over_cap`, announced |
| `get_audit` | 1942 tok, grade B on 8 graded / 5 excluded | sheds to 359, `truncated` | `over_cap`, announced |

Measured against the **committed** corpora rather than only the fixture:
`list_families` 233 tok; `get_family_index AFE795x` 4695 tok (39 sections, 14
shared, 384 deltas, no unbuilt member); `get_audit AFE7950` 1931 tok, grade
**B**, score 3.25, 10 metrics graded and 3 `n/a`, 13 of 13 shown. All three
validate against their own declared `_meta.response_schema`, and every
truncation notice names `DSA_MCP_MAX_TOKENS`.

`get_family_index` derives the index **live** rather than reading
`families/<NAME>/`, for the reason `get_card` builds a card on demand: that
directory is a cache of this call, not its source. Measured: the call writes
nothing to disk.

**Deferred at the time, and closed on 2026-09-02 after the argument was
re-measured.** The deferral read: the envelope `scope` object stays
`{part, project}`; both family tools name their family in their own body,
following `compare_parts`, because widening `scope` would change the declared
shape of all sixteen tools to carry a key only two can fill.

Both halves of that turned out to be wrong on the merits.

- **The premise moved with the work.** "Only two can fill it" was true while
  the fan-out was missing. With `family` on `search`, `find_spec`,
  `find_plots` and `ask`, **seven** of the sixteen can fill `scope.family`.
- **The principle proves too much.** `scope.part` is already declared on
  `list_projects`, which can never fill it. That is what an envelope is for: a
  caller reads *what answered* without knowing which tool it called — the same
  argument `staleness` was put on the envelope under.
- **The cost was 4 tokens**, measured with `tokens.count_tokens` over the
  indented JSON the SDK ships: a 65-token envelope becomes 69, 0.067 % of the
  6000-token cap. The one real consequence: the fixture's `read_section`
  citation floor moved 168 → 172 tokens, so the cap in
  `test_a_truncated_text_body_names_the_setting` moved 170 → 175.
- **And the alternative was worse.** A `family` key in four tool bodies writes
  the same fact in two places and leaves `scope` reading
  `{"part": "", "project": ""}` for an answer a family gave — the same reading
  `compare_parts` returns for *no* corpus in scope. A response that
  misreports which scope produced it is the one failure the envelope exists to
  prevent.

Measured against the committed corpora after the change:
`search --family AFE795x "sysref setup"` 3 hits across both members, 876 tok;
`find_spec --family AFE795x` on junction temperature 8 hits, 1154 tok;
`find_plots --family AFE795x q="output power"` 22 of 46 kept, `truncated`,
notice naming `DSA_MCP_MAX_TOKENS`; `ask --family AFE795x` 973 tok. Naming two
scopes is `FAMILY_SCOPE_ERROR` with both names echoed on `scope`; an
undeclared family is the registry's own refusal. Only `ask` folds — the record
lists have nowhere to say whose page a folded row carries.

`find_pin` and `find_register` were deliberately **not** given a `family`: the
CLI refuses `--family` on `dsa pins` / `dsa regs` / `dsa card` (each carries
its own `_part_dirs` that never learned the third scope), and giving MCP a
scope the CLI refuses swaps one asymmetry for its mirror. That CLI gap is
recorded in `KNOWN_SHORTCOMINGS.md`.

## The workbench: two one-liners, and the frontend work that is not one

`ScopeRef.kind` widens to `part | project | family` and `deps.get_retriever`
splits three ways, so `POST /api/chat/{id}/message` answers a whole series when
a caller names one. Measured: a `family` scope returns a `FamilyRetriever` over
both members with the reference first, and an undeclared family is a 400
carrying the registry own refusal, "never inferred from a part number".
`LibraryDocumentOut` carries `revision_state` **whole**, not flattened to a
`staleness` string, with `Staleness` and `RevisionState` twins in
`web/src/api/types.ts`, so `GET /api/library` reports freshness per document.

Nothing renders either. `DocumentRow` meta line is a fixed four-span list with
no slot for a freshness badge, and `scope_resolver.py` proposes only parts and
projects so no pane can offer a family. Both need new components; both are
recorded rather than half-built.

**The chat agent's tool surface, closed 2026-09-02.** `app/tools.py` was left
at phase 5's nine and is now twelve: `list_families`, `get_family_index` and
`get_audit`. They are *adapted*, not copied — the scope is injected on this
surface, so `get_family_index` takes no family name and `get_audit` no part
name, and both refuse a scope they cannot answer for. Driving that path found
two defects a declared-only surface hides: `FamilyRetriever` subclasses
`ProjectRetriever`, so every family payload reported `kind: "project"` and
every part-only refusal called the series a design; and `build_tools` bound
`scope=` to every tool, so `list_parts` and `list_projects` had been coming
back to the model as `TypeError: … unexpected keyword argument 'scope'` since
ticket 12. What remains is the picker: `scope_resolver.py` and `ScopeChip`,
recorded and not made — `web/` belongs to another wave.

## Decision — is `families/` committed?

**Ignored**, and deliberately *not* the way `projects/` is handled. A project
directory mixes authored and derived: `project.json` is the only record of who
is on that board. A family directory holds `FAMILY_INDEX.md` and `family.json`
and nothing else, both derived in full from tracked records, and the authored
half — membership — is the tracked `registry/families.yaml`. `config.py`
already says of `FAMILY_SCHEMA_VERSION` that a family index "is *not* part of
any publish cache key … there is no stale file for a version to invalidate";
committing one would manufacture that stale file.

**And ignoring it defanged the guard that watched it.**
`TestNothingHereWritesIntoTheRepository` asserted
`git status --porcelain -- families` was empty, which an ignored path always
is. Verified: `dsa family build AFE795x` writes 39 sections, 14 shared, 763
rows aligned, 2290 tokens of a 4000 budget into the working tree and
`git status` stays silent. Replaced with a git-independent detector —
`conftest` snapshots the repository own `families/` listing at collection time
and the test asserts it is unchanged — which is sharper, because a *user's*
build is legitimate and only a change **during** a run is a test writing into
the tree it asserts against. Negative control run both ways.

## Decision — does the collapse extend beyond `ask`?

**No, deliberately**, and the family this repo declares says why. `_collapse`
keeps one member citation and *says whose*; a record list has nowhere to say
it, so folding two members into one `SpecHit` ships a page number that is wrong
for the other member.

| measured on AFE795x | |
|---|---|
| spec rows the family returns | 1155 |
| distinct printed rows | 763 |
| common to both members | 387 |
| **of those, citations disagree** | **177 (45.7%)** |

`ADC resolution` is §4.6, p.14 in AFE7950 and §4.6, p.13 in AFE7953. The other
two verbs would not pay for themselves either: `plots(q="output power")`
returns 46 hits with 46 distinct (caption, citation) pairs, and a `SearchHit`
carries a BM25 score `retrieve/project.py` already documents as not comparable
across corpora. The record-level view exists under the verb built for it —
`dsa family build` lists shared sections once and tabulates only deltas, with
both operands' pages. Pinned by four tests so it cannot drift either way.

## The agent protocol

`VERBS` and `NETWORK_RULE` join `RULES` and `CONFIDENCE_ROWS` as canonical
strings, rendered by `verbs_block()` into all three destinations, and
`_mcp_block` names the three new tools. `PROTOCOL_VERSION` 1 to 2: a v1
`AGENT.md` is not wrong, but it tells an agent the corpus can only be read.
The two tracked corpora are brought current (ADR 0008) by rewriting `AGENT.md`
and the one measurement that rewrite invalidated — `stats.agent_doc_tokens`,
1450 to 1799 — and nothing else in either manifest. **No extraction ran, no
corpus was rebuilt, and no `PdfLayoutBackend.output_version`,
`STRUCTURE_STAGE_VERSION` or payload schema version moved.**

Confirmed identical across destinations: 20 canonical strings appear verbatim
in `parts/AFE7950/AGENT.md`, `parts/AFE7953/AGENT.md`, a rendered project
`AGENT.md` and `.claude/skills/datasheet-corpus/SKILL.md` — **20/20 in each, 0
missing** — and `SKILL.md` is byte-for-byte `build_skill_markdown()`.

`AGENT_DOC_TOKEN_BUDGET` 1700 to 2200. Re-measured at v2: part **1799**,
three-part project 1887, worst case the renderers allow **2045**, skill 1987.
The old ceiling sat 4 tokens above its own worst case.

## The gate, measured on the final tree

| | tests | passed | failed | errors | skipped | time |
|---|---|---|---|---|---|---|
| working tree, 11 parts built | **2915** | **2881** | 0 | 0 | 34 | 580 s |
| fresh `git clone` of `96f7379` | **2915** | **2812** | 0 | 0 | **103** | 570 s |

`ruff check .` and `ruff format --check .` clean over 350 files. +36 tests on
the 2879 batch D recorded, all of them added by this wave.

The clone carries only the two tracked corpora, and every one of its 103 skips
**names what was missing** rather than asserting on data a clone does not
have: 18 for LMX1204 not built, 17 for the register-map PDF not in the
checkout, 12 for AD9081, 9 for no cached extractions, 3 for the phase-6 gates
that already carry this pattern (each naming the parts that *are* built), 1
for no `ANTHROPIC_API_KEY`, 1 for no `web/node_modules`, and the ticket-owner
placeholders. Nothing new was added to that list by this wave.

Frontend, from `web/`: `npm run typecheck` clean, `npm test` **193 passed**
across 6 files.
