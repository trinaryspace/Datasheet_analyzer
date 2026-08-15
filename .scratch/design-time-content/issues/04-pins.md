# 04 — Pins (`pins.json`, `dsa pins`)

**What to build:** The first consumer of the device-table abstraction, and the
single most-needed missing artifact for schematic capture.

```json
{ "pin": "A1", "name": "VSSA", "type": "ground", "direction": "—",
  "description": "Analog ground", "page": 4,
  "table_index": 2, "row_index": 0, "confidence": "high" }
```

Type classification from a checked-in lexicon over name + description:
`power | ground | analog | digital | clock | rf | nc | reserved | unknown`.
`unknown` is a legitimate output; a guess is not.

Package cross-check: where a pin count is parseable from the package or
ordering-information section, compare it to the record count and warn on
mismatch — honest, non-fatal, surfaced later in `dsa audit`.

CLI `dsa pins --part X [--q VDD] [--type power] [--json]`; MCP `find_pin`.

**Blocked by:** 03 — Device-table abstraction

**Status:** ready-for-agent

- [ ] Pin tables extract for all six built parts **or are honestly rejected
      with a recorded reason**; a part with no parseable pin table produces no
      `pins.json` rather than a partial one — asserted
- [ ] Multi-pin rows expand and each expanded pin is individually citable
- [ ] Type classification is lexicon-driven; ambiguous rows yield `unknown`,
      asserted with a fixture designed to be ambiguous
- [ ] Package pin-count cross-check runs on every part; a mismatch produces a
      warning (and at least one real or synthetic mismatch is asserted)
- [ ] Golden pin questions per part — pin→name, name→pins, count by type —
      verify at 100% with page cites
- [ ] `dsa pins --type power` on AFE7950 returns a plausible, hand-checked
      supply pin set (recorded in the phase report)
- [ ] Package drawings remain retrievable as figures; nothing in this ticket
      parses a drawing

---

Source: `.scratch/design-time-content/SPEC.md`
