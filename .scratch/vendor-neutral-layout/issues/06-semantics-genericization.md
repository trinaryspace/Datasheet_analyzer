# 06 — Semantics genericization

**What to build:** The shared lexicons and positional inference that make
semantics vendor-neutral — conditions-header suffix variants
("Test Conditions/Comments"), universal unit canonicalization covering
both ohm glyphs (verbatim preserved in the corpus, canonicalized in
specs.json), revision shapes ("Rev. A"-style and document-id style),
doc-type prefixes (`ug-` alongside TI's), and the "General Description"
brief matcher. All applied without per-vendor branches.

**Blocked by:** 03 — Tables: caption-anchored hypotheses + reconstruction gate

**Status:** ready-for-agent

- [ ] ADI tables headed "Test Conditions/Comments" classify as parametric with conditions landing in the conditions role
- [ ] Both ohm glyphs canonicalize to ohm in ADI specs.json while corpus text stays verbatim; regenerated TI specs are unchanged
- [ ] "Rev. A"-style revisions appear in inventory for ADI/Hittite-era parts; `ug-`-named companion PDFs classify as app notes unless they carry register/regmap words, which classify as register maps
- [ ] A part whose description section is titled "General Description" yields a proper brief and features list
- [ ] TI golden verify stays 100% after the role/unit changes

---

Source: `.scratch/vendor-neutral-layout/SPEC.md`
