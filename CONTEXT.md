# datasheet_analyzer

Turns IC datasheet PDFs into token-efficient, citation-verified markdown
corpora, organized into parts. This context covers everything from the CLI
down to publish; extraction backends live behind one interface.

## Language

**Vendor**:
The semiconductor manufacturer whose documents we consume (e.g. TI,
Analog Devices). An attribute of a SourceDocument, pinned once at acquire
with recorded evidence; it only routes backend preference — no layout rules
hang off it.
_Avoid_: manufacturer, supplier, chip vendor

**VendorProfile**:
The registry entry that routes one vendor's documents: an identity detector
(shared brand-mark lexicon + generic doc fingerprints, evidence pinned at
acquire time — never a silent runtime guess), a backend preference chain
(e.g. ti → ti_html, then pdf_layout; everyone else → pdf_layout), and the
pinned evidence. It is a routing record, not a rulebook; all layout
intelligence lives in the vendor-neutral layout core.
_Avoid_: adapter, plugin, vendor config, dialect

**Layout core**:
The vendor-neutral offline extraction engine (backend `pdf_layout`):
furniture by slot repetition, tables by structural inference with
self-verification, shared unit/role lexicons, bookmark-first structure.
No per-vendor layout assumptions; vendor-specific code only inside backends
that consume a vendor's digital format (e.g. ti_html).
_Avoid_: extractor, parser, scanner

**Furniture**:
Recurring page-decoration bands (headers, footers, brand marks) detected by
slot repetition — y-position + style recurrence across pages, not string
matches. Constant text or universal page-machinery patterns ("N of M",
"Page N", "Rev." captions) count as furniture; a section-title echo counts
only outside the body region. PDFs with no consistent slots get no
stripping.
_Avoid_: header, footer, chrome, noise

**Alias**:
A phrase a designer types for a quantity a datasheet prints under a symbol
("junction temperature" for `TJ`). Aliases live as data in the alias
lexicon (`registry/aliases.yaml`), grouped under a canonical symbol with an
optional expected unit and an optional prefix family; adding one is a YAML
edit, never a code change.
_Avoid_: synonym table, keyword, mapping, tag

**Resolution ladder**:
The ordered rungs a spec query walks — exact symbol, alias phrase, alias
prefix family, substring, token-overlap fuzzy — where the first rung that
returns anything wins and names itself back to the caller as `matched_via`.
An expected unit only *ranks* candidates inside a rung; it never removes one.
Nothing on any rung means an explicit no-match with nearest candidates, never
a guess.
_Avoid_: search, ranking, scoring, matcher chain

**Confidence**:
The per-record grade (`high` / `medium` / `low`, or `unknown` when a corpus
predates grading) that says how far one extracted row can be trusted without
opening the printed page. Computed once, at structure time, from evidence
that exists only there — how the grid was reconstructed, whether the page is
pinned or a section range, whether the row printed a value and a unit. It is
metadata about the extraction, never a filter and never a claim about the
datasheet: a `low` record is still returned, still verbatim, still cited.
_Avoid_: score, quality, accuracy, probability, trust level

**Quantity**:
A printed value read as a number: its shape (`point`, `range`, `bound`,
`tolerance`), its magnitude in an SI base unit, and the unit it was scaled to.
It is *additive* — the string the datasheet printed remains the answer, and
where the two disagree the string wins — and it is allowed not to exist:
`See Figure 7` and `—` parse to nothing, recorded as `parse_confidence: none`,
which is a legitimate outcome rather than a gap. A quantity exists so rows can
be sorted, compared and given margins; any consumer that does so must report
the rows it could not read instead of dropping them.
_Avoid_: value, number, measurement, float, magnitude

**Device table**:
A wide, repetitive table keyed by its first column — a pin table or a register
summary — read through one abstraction rather than one parser each. What makes
it a device table is a checked-in lexicon of the words its headers and caption
print, never a vendor rule; what makes it *accepted* is validation it cannot
half-pass. A key cell holding several keys (`A1, A2, B1`) expands into one
individually citable record per key, each still quoting the row the datasheet
printed. A table that fails validation is rejected whole, with a recorded
reason, because a half-parsed pin table reads as a complete one to whoever
greps it.
_Avoid_: pin map, register map, lookup table, matrix

**Pin**:
One pin of one package as a record: its designator, the name the datasheet
printed beside it, what the lexicon says it is *for*, the printed I/O
direction, the description, and the page it appears on. It is the unit a
designer works in during schematic capture, so a printed row naming several
pins (`A1, A2, B1`) becomes one record each — a pin search must not miss a pin
that shared a row — and each of them still quotes the row it came from.
Everything on it is verbatim except the type, which is a label from
`registry/pin_types.yaml` and therefore carries the phrase that decided it.
A part with no readable pin table has no pins rather than some of them.
_Avoid_: ball, net, terminal, signal, connection

**Pin type**:
What a pin is for — `power | ground | analog | digital | clock | rf | nc |
reserved | unknown` — decided by a checked-in lexicon over the pin's name and
description, name first and longest phrase wins. It is not the `I/O` column a
datasheet prints; that is the pin's *direction* and travels verbatim beside
it. `unknown` is a legitimate answer and appears whenever the lexicon matched
nothing or matched two categories equally well: a pin the corpus does not
understand must never read as a supply. Closing a gap is a YAML edit — a
longer, more specific phrase.
_Avoid_: category, class, function, role, direction

**Register**:
One addressable configuration word of a device as a record: its address —
printed exactly as the document prints it *and* as an integer — the acronym
beside it, what the document says the register is for, the printed access
column where there is one, and the reset value where the document states one.
It is the unit a firmware engineer works in during bring-up, so it must be
findable by every notation an address is written in; that is why the integer
travels beside the string, and why a cell the grammar cannot read keeps the
string and publishes no integer rather than a guessed one. A register the
document states no reset or access for has none — never a zero, never `R/W`.
A part with no readable register summary has no registers rather than some of
them.
_Avoid_: field, bit, setting, parameter, address

**Search index**:
The precomputed inverted index of one document's section files
(`search_index.json`, written at publish): per section, how often each token
appears and how long the section is. It is derived data with a
`schema_version`, rebuilt with the corpus, never hand-edited, and never a
substitute for the sections themselves — it holds counts, not content.
_Avoid_: database, cache, embeddings, vector store

**Snippet**:
The excerpt a search hit quotes back: the text around the best-scoring term,
grown to sentence boundaries, cut from the section file at query time rather
than stored. It is evidence for the hit, never the answer — the answer is on
the cited page.
_Avoid_: summary, preview, abstract, description

**Answer pack**:
What one `dsa ask` call returns: a single payload holding the answer rows,
one supporting excerpt, and a verify footer — every part of it cited, the
whole of it inside a stated token budget. It is assembled deterministically
(routed by feature hits, filled greedily over a reserved tail) and never
generated: every line in it is a record or verbatim text the corpus already
held. A pack that had to drop something says so; a pack with no answer says
that instead of guessing.
_Avoid_: response, result, summary, report, completion

**Route**:
Which retrieval path an answer pack took — `spec`, `plot`, `search`,
`unavailable`, or `none`. Chosen by feature hits in a fixed order, with no
model in the decision, and reported back in the pack so a caller can tell a
parametric answer from a quoted paragraph. `none` is a finding about the
datasheet (nothing in this corpus answers it); `unavailable` is a finding
about the *corpus* (the full-text path could not run because there is no
current search index) — an answer pack must never spend one for the other.
_Avoid_: intent, classification, dispatch, mode

**Response cap**:
The hard token limit on everything one MCP call hands back
(`DSA_MCP_MAX_TOKENS`, default 6000). It is the answer pack's budget applied
to a transport: a client cannot bound a payload it did not build, so the
server bounds it, and what a cap removes is extra rows or excerpt prose —
never a citation. A capped response always *says* it was capped and names the
setting; silent loss is the one failure a caller cannot detect. An image
block is exempt because it is atomic: trimming base64 yields a corrupt PNG,
not a shorter one.
_Avoid_: limit, quota, page size, throttle

**Agent protocol**:
The retrieval discipline itself, as an artifact: `AGENT.md`, emitted beside
every part's `INDEX.md` and every project's `PROJECT_INDEX.md`, and checked
into this repo as the `datasheet-corpus` skill. Index first, never bulk-read,
prefer `ask`, quote units, cite `p.N`, check the grade, and on `low` open the
printed page — plus a worked example of each access path, CLI and MCP. It is
written once in `protocol.py` and rendered into all three destinations, so
there is one protocol rather than three copies; the index files point at it
instead of restating it.
_Avoid_: README, docs, instructions, prompt, guidelines

**Golden question**:
One benchmark question with a verifiable answer: the words a designer would
use, the verbatim substrings a correct answer must contain, and the printed
page it must cite — all read off the PDF by hand, per part, in
`tests/fixtures/golden_qa_<PART>.yaml`. It is the project's objective
function: `dsa verify` fails the corpus, not the question.
_Avoid_: test case, sample, example, prompt

**Path marker**:
The field on a golden question that says which retrieval path must answer it
— `spec_query`, `plot_query`, `ask_query`, `search_query`. A marker adds a
path, never a standard: each one is judged against that question's existing
cited page and verbatim substrings, so an ask-path question is the
designer's-words *twin* of a symbol-path question rather than a second
objective function. A path that cannot run (no search index) fails and says
why; it never passes quietly.
_Avoid_: tag, mode, category, test type

**Part**:
A named device (e.g. AFE7950) and its corpus: a folder under `parts/`
holding an index, inventory, manifest, and one document directory per source
document.
_Avoid_: device, chip, family

**Project**:
A design: an explicit, human-curated list of parts plus the free text that
joins them (each part's one-line role, an `interfaces` note, project notes),
stored as `projects/<name>/project.json`. It is the noun above `part` — the
unit a designer actually works in. Membership is chosen, never inferred: no
BOM or netlist is parsed, and a part with no built corpus is refused rather
than pointed at. Asking a project a question fans the lookup out across its
members and labels every hit with the part it came from.
_Avoid_: board, design file, group, BOM, assembly

**Project index**:
`PROJECT_INDEX.md`: the single always-loadable file for a whole project —
each member with its revision, its one-line role, and a pointer to its own
`INDEX.md` — written under a hard token budget. Under budget pressure it
drops its least-important block first and says that it did; the part list and
the index pointers are the product and are never what a budget removes.
_Avoid_: summary, dashboard, manifest, catalog

**SourceDocument**:
A registered input file of a part (datasheet, register map, errata, app
note). Identity is the sha256 of its bytes.
_Avoid_: PDF, file, doc

**Build**:
The pipeline run that turns one source document set into one part corpus:
acquire → extract → structure → enrich → publish.
_Avoid_: run, compile, generate

**Job**:
One unit of work in a batch: build one part from one PDF. The part number
is the PDF's filename stem, uppercased.
_Avoid_: task, item, work item

**Batch**:
The set of PDFs in one directory (e.g. `datasheets/`), each becoming a job;
the directory is the batch's identity and its only specification.
_Avoid_: bulk, campaign, queue, spec file
