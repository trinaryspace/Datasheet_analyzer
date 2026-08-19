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
A named device, identified by its part number (e.g. AFE7950). Its corpus is
every SourceDocument that applies to it; a Part owns no documents — it is
named by them.
_Avoid_: device, chip, family

**Project**:
A design: a human-curated list of parts plus the free text that joins them
(each part's one-line role, an `interfaces` note, project notes), stored as
`projects/<name>/project.json`. It is the noun above `part` — the unit a
designer actually works in. Membership may be *seeded* by opening a Batch
directory, which names the project after the folder and adds what it built;
it is never inferred from a design artifact, no BOM or netlist is parsed, and
every seeded member can be removed by hand. Its directory is also its
**shelf**: the folder holds copies of the source PDFs it was built from, so a
project is portable on its own. That makes it a container of *sources* and
still only a view of *parts* — removing a part deletes nothing, and removing a
document offers to delete the copy rather than doing it. A part with no built corpus is
refused rather than pointed at. Asking a project a question fans the lookup
out across its members and labels every hit with the part it came from.
_Avoid_: board, design file, group, BOM, assembly, folder, workspace

**Project index**:
`PROJECT_INDEX.md`: the single always-loadable file for a whole project —
each member with its revision, its one-line role, and a pointer to its own
`INDEX.md` — written under a hard token budget. Under budget pressure it
drops its least-important block first and says that it did; the part list and
the index pointers are the product and are never what a budget removes.
_Avoid_: summary, dashboard, manifest, catalog

**SourceDocument**:
A registered input file (datasheet, register map, errata, app note).
Identity is the sha256 of its bytes. It belongs to the Library, not to any
one Part.
_Avoid_: PDF, file, doc

**Library**:
Every *processed* SourceDocument, as one flat set — a document enters when a
Build registers it and never before, so "in the Library" and "has a corpus"
are the same fact. A Batch is one directory processed in a single run; the
Library is what has accumulated across runs, and is what a question is asked
against. One processed document may sit on many project shelves; the Library
holds it once, keyed by content hash.
_Avoid_: corpus, collection, database, shelf (a shelf is one project's folder)

**Applicability**:
The set of Parts a SourceDocument is about: named part numbers, a family
prefix (e.g. `AFE79xx`), a Category, or every part. Inferred at build time
from the document's own text and correctable by hand. A document may apply to
many parts, and a part is constituted by the documents that apply to it.
_Avoid_: ownership, assignment, grouping, scope

**Category**:
The one slot a Part occupies in the user's taxonomy — amplifiers, mixers,
data converters. A build may *propose* one by reading the built corpus; only
a person may set one, and a person's answer survives every later rebuild,
which is why it is recorded beside the Library and never in the manifest. One
per part, always: a part that belongs in two places wants a Label, not a
second category. A Family is read off the page (`AFE79xx` is printed in the
datasheet); a category is a decision about a shelf.
_Avoid_: tag, label, folder, type, group

**Supporting document**:
A SourceDocument that applies to a whole Category rather than to any part —
an app note on high-frequency amplifier layout, a JESD204B primer. It is
filed, never built into a part of its own, and it joins each part's corpus the
next time that part is built, because a build resolves its documents from
every Library record covering the part. Refiling the part into another
category takes it back out.
_Avoid_: general document, shared doc, appnote (as a kind), attachment

**Tag**:
A machine-derived facet of a PlotRecord — signal path (`tx`, `rx`), a
normalized frequency, or a measurement keyword — computed from the section
title and figure caption at build time. Reproducible and never hand-edited;
its human counterpart is a Label.
_Avoid_: label, keyword, topic

**Label**:
Short text a person attaches to a SourceDocument to organize their own shelf
(e.g. `reviewed`, `thermal`, `jesd204`). Free-form and mutable; it records
what a human thinks, never what the pipeline derived. Its machine
counterpart is a Tag.
_Avoid_: tag, keyword, annotation, category

**Exclusion**:
A SourceDocument a person has told one Project never to build, recorded on
that project by content hash. It is the answer to "this PDF is in my folder
but is not mine" — a competitor's app note, a purchase order, a mechanical
drawing — and it survives a rescan, because a recursive walk would otherwise
re-propose the same rejected files every time. Scoped to the project on
purpose: the same document may be noise in one design and the subject of
another. Excluding is not deleting and not removing a part; the file is
untouched and any other project may still build it.
_Avoid_: ignore, blocklist, filter, hidden

**Shelf**:
One project's directory, seen as the documents sitting in it. It is what the
rail lists and what "the files in this project" means — distinct from the
Library, which is every processed document everywhere. A shelf may hold a PDF
that has never been built; the Library, by definition, cannot.
_Avoid_: library, folder, workspace, collection

**Needle**:
The record's own printed text, carried on a Citation so a reader can be shown
*the row an answer came from* rather than the heading above it — a spec row's
parameter name, a figure's caption, a section's title. It is never parsed and
never printed; it exists to be handed to `/locate`, which is free to miss.
Page furniture is not a needle: a section titled `Page 3` names nothing on the
page except the running footer, and highlighting that is worse than
highlighting nothing.
_Avoid_: query, search term, anchor, selector

**Build**:
The pipeline run that turns one source document set into one part corpus:
acquire → extract → structure → enrich → publish.
_Avoid_: run, compile, generate

**Job**:
One unit of work in a batch: one PDF taken through the Build. Which Parts it
contributes to is its Applicability's answer, not the job's — one job may
serve many Parts — and the part number it carries is read from the document's
own text, falling back to the filename stem only when the text yields none.
_Avoid_: task, item, work item

**Batch**:
The set of PDFs under one directory (e.g. `datasheets/`), each becoming a
job; the directory is the batch's identity and its only specification. The
CLI reads direct children only; the workbench walks subdirectories too,
skipping what could not be a source document — dot-directories, symlinks, and
the tool's own `parts/`, `library/`, `projects/` and `.cache/`. What it
skipped is reported, never silently dropped. A Batch is a set of documents,
not a design: opening one may *seed* a Project, but the two remain separate
nouns — excluding a document from a Batch stops it being built, whereas
removing a part from a Project only narrows the view. How many Parts a Batch
yields is a fact about its documents, never a count of its jobs.
_Avoid_: bulk, campaign, queue, spec file, project, folder

**Quantity**:
The parsed numeric reading of one printed spec cell: a magnitude in SI units,
a kind (`point`, `range`, `bound`, `tolerance`) and the confidence of the
parse. It is a *second* layer, never a replacement — the verbatim string
stays authoritative and unmutated, and a cell that does not parse (`See
Figure 7`, `—`) yields no Quantity at all, which is a first-class outcome
rather than an error. Nothing may present a Quantity without the printed
text it came from.
_Avoid_: value, number, float, parsed value, normalized value

**Device table**:
A wide, repetitive table keyed by its first column — a pin table or a
register-summary table. One structural animal with two consumers, read by
identify → map columns → validate → emit. A device table that fails
validation is rejected **whole**, with the reason recorded: half a pin table
reads as "this pin does not exist", which is worse than no pin table.
_Avoid_: grid, matrix, listing, table (unqualified)

**Design card**:
A task-shaped view over records that already exist — power, thermal,
interface, limits — published per Part rather than per document, because the
question ("what rails does this need?") is about the device, not about one
PDF. Every cell carries the record it was copied from, the printed page, and
the named rule that produced it; a cell that could not be filled is null and
says why. An empty card is a real answer about the datasheet, not a failure
of the tool. Its rules are versioned by `card_version`, which participates in
the publish cache key — changing a rule regenerates the card.
_Avoid_: report, summary, dashboard, view, digest
