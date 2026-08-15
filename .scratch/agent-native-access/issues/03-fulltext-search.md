# 03 — Full-text search with citations attached

**What to build:** A precomputed inverted index (`search_index.json`, one per
document, built in `publish/`) and BM25 ranking in `retrieve/search.py`,
exposed as `dsa search --part X "…" [--limit N] [--json]`.

Precomputed beats shelling out to ripgrep: deterministic, dependency-free, and
usable inside the MCP server without spawning a process. Tokens are
lowercased and stopword-stripped with **no stemming** — `SYSREF`, `θJA`, and
`dBc/Hz` must survive intact.

Every hit carries the section's page range from its `<!-- source: … -->`
header, so search results are cited **by construction** and no caller ever
attributes a page itself.

**Blocked by:** 01 — Retrieval core seam

**Status:** ready-for-agent

- [ ] `search_index.json` is written at publish for every document, with a
      `schema_version` field; it participates in the publish cache key
- [ ] BM25 (k1=1.2, b=0.75) ranking; ties broken deterministically so results
      are stable across runs
- [ ] Every result carries doc, section, page range, score, and a ±240-char
      snippet expanded to sentence boundaries
- [ ] Symbols and unit strings are searchable verbatim (`SYSREF`, `dBc/Hz`,
      both ohm glyphs) — asserted per glyph
- [ ] Index size is recorded per part for the phase report; it must not
      dominate the corpus (report the ratio)
- [ ] Search over a part with no index (older corpus) degrades with a clear
      "rebuild to enable search" message, not a crash
- [ ] Rebuilds are byte-identical for identical input (determinism)

---

Source: `.scratch/agent-native-access/SPEC.md`
