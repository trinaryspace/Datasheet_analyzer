# 0001 — Evidence-pinned vendor routing shapes backend selection

Backends were chosen by a single global default (`ti_html`) for every
datasheet, so multi-vendor support needed a per-document vendor concept.
We decided the vendor is a **routing record, not a rulebook**: every
vendor-specific rule — revision formats, doc-number prefixes, page
furniture, TOC styles, table-header wordings, unit glyphs — was
genericized into the vendor-neutral layout core with shared lexicons, so
no layout behavior hangs off the vendor string.

Vendor identity itself is detected at acquire time by a shared brand-mark
lexicon + generic fingerprints, **pinned in sources.json with its evidence**
and surfaced in the manifest; a later build whose detection contradicts the
pinned value warns loudly (identity drift). `--vendor` on `dsa build` /
`add-doc` is the explicit override. Default `ti` keeps the reference parts
bit-for-bit unchanged.

This is hard to reverse (v1 of the layout core is being built to this
contract), surprising without context (vendor feels like the obvious key,
but it must stay inert), and was a genuine trade-off against richer
per-vendor dialect profiles — which we rejected because vendor N+1 always
arrives with unknown conventions, and the engine must survive it unchanged.

**Update (phase 6.5 follow-up).** "Default `ti`" was the one clause of this
decision that contradicted the rest of it: an unmatched document was pinned
`ti` with *empty* evidence, which is the silent runtime guess this ADR
forbids, and it routed four brand-less Mini-Circuits datasheets to `ti_html`
where they 404'd against ti.com. Detection now reads three sources in
strength order — page-1 text, the document's own PDF metadata (a cover page
that prints its brand as a logo still carries it; every TI datasheet in this
repo is that shape), then the filename — and a document that matches none of
them is pinned `unknown`, which routes to the vendor-neutral layout floor.
The reference parts are unchanged because their evidence is real: TI's
`author` metadata, recorded as `brand:"texas instruments" (metadata)`.

**Update (2026-09-02, corpus scale-up).** The clause above that the four
Mini-Circuits datasheets "match none of them" was true only because
`VENDOR_PROFILES` had no Mini-Circuits entry to match against. It had four:
`ti`, `adi`, `qorvo`, `unknown`. Adding `minicircuits` and `skyworks` was the
data change this ADR says vendor N+1 must be — two profile entries, no code —
and it moved all four of those parts from `unknown` on empty evidence to
`minicircuits` on `brand:"minicircuits" (p.1)`, taken from the
`www.minicircuits.com  P.O. Box 350166 …` banner every one of them prints. The
extraction did not move (cache hit on all four; identical sections, tables,
specs and plots), because `minicircuits` prefers the same `pdf_layout` floor
`unknown` fell back to — which is the ADR's point restated: the vendor string
carries identity, and identity that changes without changing routing changes
nothing else.

The lesson for the next vendor: the profile is a **lexicon**, and a vendor's
brand mark is whatever its page-1 *text* prints, which is not always its name.
Mini-Circuits sets its wordmark as a logo image on four of six cover pages; its
domain in the address banner is the mark that is always there.
