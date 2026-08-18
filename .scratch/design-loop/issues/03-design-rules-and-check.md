# 03 — Design rules + `dsa check`

**What to build:** The headline capability of the phase. Declarative,
checked-in design rules (`registry/design_rules.yaml`) evaluated over the
Phase 8 connections view, producing `designs/<NAME>/DESIGN_REVIEW.md` and
`--json`.

Ship these rules:

| Rule | Flags |
|---|---|
| `floating-power-pin` | a `power`/`ground` pin on a net with one node |
| `unconnected-required-pin` | a must-connect pin on no net |
| `supply-out-of-range` | a rail voltage outside the pin's recommended range |
| `logic-level-mismatch` | a driver's VOH/VOL against a receiver's VIH/VIL |
| `abs-max-margin` | a net voltage within a configured margin of abs-max |
| `missing-decoupling` | fewer decoupling caps than the datasheet asks for |

**Nothing here signs off on a design.** Findings are advisory and cite the
printed page. The tool informs; the designer decides.

**Blocked by:** 02 — Pin-level join (04 for `missing-decoupling`)

**Status:** ready-for-agent

- [ ] Rules are **data**: adding or editing a rule in
      `registry/design_rules.yaml` changes behaviour with no Python change —
      asserted by a test that edits the YAML and observes a different result
- [ ] Every finding carries rule id, severity, the refdes/pin/net involved,
      the **verbatim** datasheet text it derives from, the record id, and the
      printed page
- [ ] **Every rule reports its unevaluated population and why** (no pin table,
      unparsed value, no rail declared). A test asserts that a rule which
      could evaluate almost nothing does **not** render as clean output. This
      is the most important criterion in the ticket
- [ ] Each shipped rule has a **pair** of fixtures — one designed to trip it,
      one designed not to — and both are asserted
- [ ] Rail voltages come from `designs/<NAME>/rails.yaml`; `--infer-rails`
      derives them from net names, is **off by default**, and every inferred
      rail is labelled as inferred in the output — asserted
- [ ] `logic-level-mismatch` resolves VOH/VOL/VIH/VIL through the Phase 5
      alias lexicon and the Phase 6 numeric layer; unparseable thresholds go
      to the unevaluated population, never to a silent pass
- [ ] `DESIGN_REVIEW.md` states plainly, near the top, that findings are
      advisory and that the tool does not certify the design
- [ ] MCP `check_design(name)` exposes the findings to an agent
- [ ] No model call in any rule path (invariant 8)

---

Source: `.scratch/design-loop/SPEC.md`
