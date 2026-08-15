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

**Part**:
A named device (e.g. AFE7950) and its corpus: a folder under `parts/`
holding an index, inventory, manifest, and one document directory per source
document.
_Avoid_: device, chip, family

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
