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
