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
