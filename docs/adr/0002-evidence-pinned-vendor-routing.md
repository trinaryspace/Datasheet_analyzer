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
