# 10 — MCP surface, goldens, and phase-6 gate

**What to build:** Expose the phase's new artifacts through the Phase 5 MCP
seam, extend the goldens, and close the phase with a measured report.

New MCP tools: `find_pin`, `find_register`, `get_card`, `compare_parts`;
`find_plots` gains axis filters. Answer packs learn to route pin and register
questions.

**Blocked by:** 04, 07, 08, 09 (05/06 join if they are unblocked in time; if
the register work is still `needs-info`, the phase closes without it and the
report says so)

**Status:** ready-for-agent

- [ ] New MCP tools exercised in-process; responses carry citations and
      confidence like every other tool
- [ ] `dsa ask` routes pin questions ("which pins are ground?") and register
      questions ("what is the reset value of TXDIG_CTRL0?") to the right
      artifact, asserted per route
- [ ] Golden sets gain pin, card, and (if unblocked) register questions;
      `dsa verify` at 100% across all six parts
- [ ] All Phase 5 goldens unchanged and still at 100%
- [ ] `pytest` fully offline; `ruff` clean
- [ ] `AGENTS.md`: invariant 8; module map gains `structure/device_tables.py`,
      `structure/quantities.py`, `cards/`; register-map caveat rewritten
- [ ] `README.md`: the "register maps stay paragraphs-only" caveat and the
      "spec values are never parsed" caveat are both amended — the latter
      becomes "verbatim values are authoritative; a parsed layer is additive
      and may be absent"
- [ ] `CONTEXT.md` gains **Design card**, **Device table**, **Quantity**
- [ ] `Reports/PHASE_6_REPORT.md` with measured numbers: pin counts and
      cross-check results per part, numeric parse rate, card coverage, axis
      coverage, register outcome (shipped or parked, with the reason)
- [ ] `PHASE_6_PLAN.md` marked superseded by the report

---

Source: `.scratch/design-time-content/SPEC.md`
