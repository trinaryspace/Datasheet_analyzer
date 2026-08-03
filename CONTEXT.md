# datasheet_analyzer

Turns IC datasheet PDFs into token-efficient, citation-verified markdown
corpora, organized into parts. This context covers everything from the CLI
down to publish; extraction backends live behind one interface.

## Language

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
One unit of work in a batch: a single (pdf, part number) build of one part.
_Avoid_: task, item, work item

**Batch**:
A named, machine-readable set of jobs, submitted to the batch runner and
tracked as a unit.
_Avoid_: bulk, campaign, queue
