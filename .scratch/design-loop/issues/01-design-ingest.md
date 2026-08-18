# 01 — Design ingest (`dsa design import`)

**What to build:** The entry point for the whole phase. Read a KiCad netlist
(documented subset) or a plain BOM CSV, bind each component to a built corpus,
and write `designs/<NAME>/design.json` holding components, nets, and — as a
first-class output — everything that could **not** be bound.

Binding is explicit: it comes from the netlist's own value/MPN fields or from
a manual override written by `dsa design bind`. There is no fuzzy matching on
value strings. A wrong bind answers confidently about the wrong silicon, which
is the worst failure this phase could produce.

**Blocked by:** —

**Status:** ready-for-agent

- [ ] `dsa design import <file>.net --name X` parses the `(components …)` and
      `(nets …)` blocks of a KiCad netlist and writes `designs/X/design.json`
- [ ] `dsa design import <file>.csv --name X --format bom` produces the same
      `design.json` shape from a BOM CSV (refdes, value/MPN columns)
- [ ] Components that bind to a built corpus record `part` and `bound_by`
      (which field or override supplied the bind)
- [ ] Components that do **not** bind appear under `unbound` with a reason —
      never dropped, never guessed. Asserted with a fixture containing both a
      passive and an unknown IC
- [ ] Netlist constructs the parser does not support are **recorded** in the
      output rather than silently ignored — asserted with a fixture that
      contains one
- [ ] `dsa design bind X U7=LMX1204` writes a manual override that survives a
      re-import, so the join improves by use
- [ ] `dsa design status` lists designs, component counts, and the
      bound/unbound split
- [ ] The source file's sha256 and format are recorded in `design.json`
- [ ] Tests use a **checked-in synthetic netlist fixture** written to the
      documented format; validating the parser against a real KiCad export is
      recorded as a live step in `Reports/PHASE_8_LIVE_RUN.md`, not assumed

---

Source: `.scratch/design-loop/SPEC.md`
