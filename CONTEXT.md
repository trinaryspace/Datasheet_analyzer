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

**Part**:
A named device, identified by its part number (e.g. AFE7950). Its corpus is
every SourceDocument that applies to it; a Part owns no documents — it is
named by them.
_Avoid_: device, chip, family

**SourceDocument**:
A registered input file (datasheet, register map, errata, app note).
Identity is the sha256 of its bytes. It belongs to the Library, not to any
one Part.
_Avoid_: PDF, file, doc

**Library**:
Every SourceDocument registered so far, as one flat set. A Batch is one
directory processed in a single run; the Library is what has accumulated
across runs, and is what a question is asked against.
_Avoid_: corpus, collection, shelf, database

**Applicability**:
The set of Parts a SourceDocument is about: named part numbers, a family
prefix (e.g. `AFE79xx`), or every part. Inferred at build time from the
document's own text and correctable by hand. A document may apply to many
parts, and a part is constituted by the documents that apply to it.
_Avoid_: ownership, assignment, grouping, scope

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
