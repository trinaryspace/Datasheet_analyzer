# 06 — Semantics genericization

**What to build:** The shared lexicons and positional inference that make
semantics vendor-neutral — conditions-header suffix variants
("Test Conditions/Comments"), universal unit canonicalization covering
both ohm glyphs (verbatim preserved in the corpus, canonicalized in
specs.json), revision shapes ("Rev. A"-style and document-id style),
doc-type prefixes (`ug-` alongside TI's), and the "General Description"
brief matcher. All applied without per-vendor branches.

**Blocked by:** 03 — Tables: caption-anchored hypotheses + reconstruction gate

**Boundary (06/07/09 scope reconciliation, decided at kickoff):** the
ledger's 06-tagged items — merged-cell materialization ("high", deferral
note written at the 04/06 boundary), captionless-era tables (also high),
and continuation-row page attribution — are **not** in ticket 07's
letter either (07 is gate provisioning + per-part golden Q&A: SPEC
stories 26–27). All were re-ticketed to **09 — Layout materialization +
continuation-page attribution** (`.scratch/vendor-neutral-layout/issues/
09-layout-materialization.md`) at the 06/07/09 kickoff, and the ledger's
"→ ticket 07" pointers were corrected there. 06 is semantics
genericization (shared lexicons + positional inference, SPEC stories
22–25); grid *materialization* (SPEC story 12) and hallucination-guarded
heading-anchored hypotheses (SPEC story 10, "captionless doubles must
stay paragraphs") are reconstruction designs that deserve their own
probe-backed synthetic fixtures and a rejection-gate design, not a
lexicon change. The 04/06 note ("explicitly deferred to ticket 06") is
superseded by this entry. Title-anchored figures ride along to 09 for
the same reason.

**Status:** shipped (commit on `feat/pdf-layout-paragraph-core`, ticket 05
pattern: TDD at `build_part`, gate-PDF measured proof, ledger updated)

- [x] ADI tables headed "Test Conditions/Comments" classify as parametric with conditions landing in the conditions role — shipped in 03 (roles.py positional inference + shared `test conditions`-prefix lexicon); pinned by the gate (`rec.conditions == "AC coupling"`, `"50 Ω"` + `"shunt to GND"` row via `SpecQuery.find`, table header rendered in the corpus as `| Parameter | Test Conditions/Comments | Min | Typ | Max | Unit |`). Measured: AD9081 29/29 tables, conditions column fully mapped
- [x] Both ohm glyphs canonicalize to ohm in ADI specs.json while corpus text stays verbatim; regenerated TI specs are unchanged — shipped in 03 (`structure/units.py` canonicalizer covers U+2126 AND U+03A9; corpus keeps the verbatim glyph); pinned by the gate: `Differential Resistance` → canonical `ohm` while corpus rows keep the source glyphs. Regenerated TI specs unchanged = the AFE7950/AFE7953 integration suites (roles/units untouched by 06) — full suite green
- [x] "Rev. A"-style revisions appear in inventory for ADI/Hittite-era parts; `ug-`-named companion PDFs classify as app notes unless they carry register/regmap words, which classify as register maps — shipped in 06: shared revision lexicon in `pdf_structure.py` (capital-"Rev." + token shapes, "Rev. N to Rev. M" keeps the last token; TI doc-ids unchanged and now require a digit, killing the measured AD9081 "SUPPORT" false positive); `ug-` hint joined into `_HINTS`'s app_note line (order errata → register → note → datasheet means register/regmap words always win); `pdf_layout` extractor_version tables-05 → tables-06 invalidates stale caches so rebuilds pick up the new revision values (invariant #6). Measured on the real gate PDFs: AD9081 → "Rev. 0", HMC520A → "Rev. A", QPA1003P → "Rev. I" (embedded title line), LM741 keeps "SNOSC25D"; synthetic pins for `ug-1578.pdf` → app_note, `ug-1578 register map.pdf` → register_map, mid-word "ug" never counts
- [x] A part whose description section is titled "General Description" yields a proper brief and features list — shipped (pipeline `_brief_and_facts` matcher, index.py includes "Description"/"General Description"); pinned by the gate: AD9081's INDEX.md carries the "MxFE Quad" brief under its proper token budget
- [x] TI golden verify stays 100% after the role/unit changes — AFE7950 `dsa verify` golden (19 questions) green, AFE7950 build/plots/specs suites green, full suite 329 tests green (was 318 at ticket-05 handoff)

---

Source: `.scratch/vendor-neutral-layout/SPEC.md`
