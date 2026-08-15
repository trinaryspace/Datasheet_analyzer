# 05 — Answer packs (`dsa ask`)

**What to build:** `dsa ask --part X "question" [--budget N] [--json]` — one
call returning a complete, cited, budget-bounded payload instead of the three
or four round trips an agent makes today.

Routing is **deterministic, no LLM in the path**, classified by feature hits
in order: alias/symbol hit → spec lookup; plot vocabulary
(`plot|curve|vs\.?|versus|graph|figure`) → plot lookup; otherwise full-text
search plus a section excerpt.

The pack is filled greedily by score against the budget with a **reserved tail
so citations can never be truncated away**. Sections: answer, supporting
excerpt, verify footer (printed page + confidence).

**Blocked by:** 02 — Alias lexicon; 03 — Full-text search; 04 — Confidence

**Status:** ready-for-agent

- [ ] `dsa ask --part AFE7950 "max junction temperature" --budget 3000`
      returns the `TJ` record with `§4.3, p.6` and a confidence grade
- [ ] Every golden question across all six parts, asked in natural language,
      resolves to the same verbatim answer and page as its symbol-path twin
- [ ] Pack size is **at or under budget** for every golden question, asserted
      numerically over the whole set (not spot-checked)
- [ ] Citations are never the truncated part — asserted with a deliberately
      tiny budget
- [ ] Truncation emits an explicit notice naming the flag that would raise the
      budget
- [ ] A no-match question returns an explicit no-match plus nearest alias
      candidates; it never degrades into a full-text dump or a guess
- [ ] Each of the three routes (spec / plot / search) is exercised by a
      dedicated test asserting which route fired
- [ ] `--json` output validates against a declared schema (the MCP tool in
      ticket 07 reuses it)

---

Source: `.scratch/agent-native-access/SPEC.md`
