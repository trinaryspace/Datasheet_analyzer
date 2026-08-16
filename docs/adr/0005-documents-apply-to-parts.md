# 0005 — Documents apply to parts; parts do not own documents

The batch model builds one part from one PDF, keyed on the filename stem, and
`SourceDocument` was defined as "a registered input file *of a part*" —
containment, exactly one owner. Real shelves break that immediately: an
application note titled "AFE79xx JESD204C Interface Guide" covers a whole
family, and a layout-guidelines note covers everything a vendor ships. Under
containment the only ways to register such a file are to duplicate it per part
or to pick one owner and be wrong for the rest, and both corrupt the thing the
project exists to do — answer a question about *one device* from every document
that describes it.

Containment is replaced by an **applicability** relation. Every SourceDocument
lands in one flat Library and carries the set of parts it is about: named part
numbers, a family prefix, or all parts. A Part becomes a view — the documents
whose applicability includes it — so one document contributes to many part
corpora without being copied or arbitrated. Applicability is inferred at build
time from the document's own text (part-number sweep plus a classification
pass) and is correctable by hand; a document whose applicability cannot be
determined becomes "all parts", which is the honest, non-lossy default and
degrades to the previous flat behaviour rather than to a wrong owner. This is
additive to the corpus layout, which already holds one directory per source
document; what changes is which part directories a document may appear in.

Hard to reverse: applicability sits under acquire, so the manifest, the batch
report, and every retrieval scope read it, and returning to containment later
means re-deciding an owner for every multi-part document. Surprising without
context: `Job` still says "build one part from one PDF", and a reader meeting a
part directory assembled from documents that live in no single part will want
to know why. A real trade-off: the alternative was a two-tier model —
part-scoped documents plus a shelf-scoped bucket — which needs no per-document
inference and no review UI, and was rejected because it cannot express the
family case (`AFE79xx` applies to some parts, not all), which is the common one
rather than the exotic one. The cost accepted in exchange is an inference step
that can be wrong and therefore needs a human-correctable surface.
