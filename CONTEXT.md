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
them. Where the document also prints the register's own field table, the
register carries its **bit fields** and the width they were checked against;
where it does not, or where that table could not be trusted, the register says so
and carries none.
_Avoid_: field, bit, setting, parameter, address

**Bit field**:
One named span of bits inside one register: the name the document printed, the
bits it occupies — as printed *and* as a `hi`/`lo` pair — the printed access
code, the printed reset value, and the description. It is the unit a driver is
written against, which is why it is the one artifact here that is absent rather
than approximate: a wrong bit range compiles, runs, and misconfigures silicon
silently. So a field set is published only once it has been checked against the
register's width and holds no overlap and no overflow; a set that fails is
refused **whole**, with a recorded reason, and the register keeps its record with
no fields rather than disappearing. `RESERVED` is a field like any other — the
document printed it — and bits no field claims are listed rather than assumed, so
a field list's coverage of the register is checkable by reading it.
_Avoid_: bit, flag, mask, bitmask, register bit

**Design card**:
A task-shaped view over records the corpus already publishes — `power`,
`thermal`, `interface`, `limits` — written as `cards/<name>.json` and
`cards/<name>.md` beside a part's index. It is the datasheet reorganised around
what someone needs open while drawing a schematic, and it owns no value: every
field is a cell quoted with its printed unit, a number computed from quoted
cells by a named rule, or a label from `registry/cards.yaml`, and each one
carries the record it came from, the page it was printed on and the rule that
produced it. A computed value has no verbatim, because no page printed it. Which
rows a card selects is data — the table's printed title, the physical quantity
its unit scales to, the words its symbol or name uses — so a new rail-naming
convention is a YAML edit. A card with nothing to show is **honestly empty**: it
states what it looked for and did not find, rather than inventing a row or
leaving a missing file that reads as "not built yet".
_Avoid_: summary, dashboard, report, datasheet extract

**Margin**:
The headroom between a parameter's absolute maximum and its recommended
operating maximum, computed on the `limits` card only where **both** sides
parsed as numbers in the same SI base. It is the one number here that exists in
no datasheet: two tables pages apart, subtracted. A margin of zero is flagged —
the recommended maximum *is* the rating, so any overshoot is out of
specification — and so is the reverse, a recommended limit above a rating. Where
the two tables cannot be paired without guessing (three ratings against three
rails), no margin is computed and the pair is listed as uncomparable with the
reason, because a margin between the wrong two rows is worse than none.
_Avoid_: headroom, delta, difference, derating, safety factor

**Comparison**:
Two or more parts answered as one question — `dsa compare AFE7950 AFE7953
--symbol Pdiss`. It is a derived artifact like a design card, built live and
never written to disk, and it owns exactly one number: the **delta**. Rows align
by alias-resolved symbol, so two datasheets that name a parameter differently
still line up, and every row records what it aligned on — a mis-alignment must be
readable rather than invisible. A parameter one part prints and another does not
is a row flagged `only in A`, because during part selection an absent parameter
is itself a finding; a part that prints several rows no shared printed name can
pair holds no column and is named, while the parts that *are* unambiguous still
compare. Everything it refused is listed with its printed values under one
heading, beside the unparsed population of each part.
_Avoid_: diff, matrix, table, benchmark, shortlist

**Delta**:
The difference between two parts' printed values for one parameter, in the SI
base both parsed to. The only number a comparison adds, and it exists only where
both sides parsed the **same printed column**: a typical against a maximum is not
a delta, two units with different bases are not a delta, and a printed range is
not reduced to one of its endpoints to make one. Its sign is fixed — the part
minus the reference, which is the first part named — and it carries no verbatim,
because no page printed a difference between two datasheets. Where it cannot be
computed, both values are still shown, still cited, and the reason is stated.
_Avoid_: diff, margin, gap, difference, delta value

**Axis catalog**:
What one figure's two axes say, as fields on its plot record: the printed axis
title, the unit it printed in brackets, the first and last **tick label**, and
whether those ticks are spaced linearly or logarithmically. It exists so a figure
can be chosen from text — 514 of them narrow to a handful before an agent spends a
vision call on one — and it is read geometrically off the text inside the figure's
own caption-anchored region, never inferred from the caption. Each half stands
alone: a figure may publish a readable y axis and no x axis, and says so with its
own grade beside the plot's. An axis that could not be read is **null with a
stated reason**, not approximate: a range nobody named is not published, a tick
sequence that is neither linear nor logarithmic has no scale rather than a
plausible one, and a y column paired with the neighbouring plot's x row is refused
outright, because a wrong axis pair looks exactly like a right one. A figure is
never lost to a failed axis reading — its caption, conditions, page and image are
untouched — and any lookup that filters on an axis says how many figures it could
not consider.
_Avoid_: axes, scale, calibration, plot data, digitization

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
Which retrieval path an answer pack took — `pin`, `register`, `plot`, `spec`,
`search`, `unavailable`, or `none`. Chosen by feature hits in a fixed order,
with no model in the decision, and reported back in the pack so a caller can
tell a parametric answer from a quoted paragraph. The order is *specificity*,
not preference: a question that names a pin or a register named the entry it
wants, and the row that answers it lives in that artifact with its own
citation, so answering it from a paragraph that shares a word would cite the
wrong table. An artifact's vocabulary alone never routes anything — the lookup
must also find something — so a routing rule can never cost an answer that
exists. `none` is a finding about the datasheet (nothing in this corpus answers
it); `unavailable` is a finding about the *corpus* (a path the question needed
could not run at all: no search index, no pin table, no register map) — an
answer pack must never spend one for the other.
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
— `spec_query`, `plot_query`, `pin_query`, `reg_query`, `card_query`,
`ask_query`, `search_query`. A marker adds a path, never a standard: each one
is judged against that question's existing cited page and verbatim substrings,
so an ask-path question is the designer's-words *twin* of a symbol-path
question rather than a second objective function. `card_query` is the first
whose answer is a **derived** artifact and it is held to the same rule for that
very reason — a row of the named card must carry a value printed on a page the
question cites, so a selector that picked the wrong row fails the benchmark
instead of passing it with a plausible number. A path that cannot run (no
search index, no pin table, no register map) fails and says why; it never
passes quietly.
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
