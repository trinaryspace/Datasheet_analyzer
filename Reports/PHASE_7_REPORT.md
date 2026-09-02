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
`KNOWN_SHORTCOMINGS.md`. This report covers **batch C**: tickets 05 and 06.

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
