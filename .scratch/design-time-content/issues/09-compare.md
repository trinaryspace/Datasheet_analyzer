# 09 — Cross-part compare (`dsa compare`)

**What to build:** The part-selection question, answered in one call.

```
dsa compare AFE7950 AFE7953 --symbol Pdiss
dsa compare AFE7950 AFE7953 --card power
```

Rows align by alias-resolved symbol. Each row shows both verbatim values,
both page cites, and an SI delta **only where both sides parsed**. Rows
present in one part and absent from the other are reported as `only in A` —
never silently dropped, because an absent parameter is itself a finding during
part selection.

**Blocked by:** 02 — Numeric layer; 07 — Design cards

**Status:** ready-for-agent

- [ ] `dsa compare AFE7950 AFE7953 --symbol Pdiss` produces a table with both
      verbatim values and both page cites, hand-verified against the printed
      pages
- [ ] Deltas appear only where both sides parsed; unparsed pairs are listed
      under an explicit "not comparable" heading with their verbatim values
- [ ] `only in A` / `only in B` rows are reported, asserted with a parameter
      that genuinely exists in one part only
- [ ] `--card power` compares whole cards row-by-row
- [ ] More than two parts is supported or explicitly rejected with a clear
      message — no silent two-part truncation
- [ ] Alias resolution is used for alignment, so differently-named equivalents
      still line up (and a mis-alignment is impossible to produce silently:
      each aligned row records what it matched on)
- [ ] `--json` output for agent consumption; MCP `compare_parts`

---

Source: `.scratch/design-time-content/SPEC.md`
