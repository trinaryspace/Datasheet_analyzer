# 06 — Register bit fields (gated; may park)

**What to build:** Shape (b) of the register problem — the hard one. A bit
position header row (`7 6 5 4 3 2 1 0`) over field-name cells that span
columns, followed by field description rows.

```json
"fields": [{"name": "NCO_EN", "bits": {"verbatim": "[3]", "hi": 3, "lo": 3},
            "access": "R/W", "reset": "0", "description": "Enable NCO"}]
```

**This ticket is explicitly permitted to fail closed.** If bit-field
extraction cannot pass its accuracy gate against the reference document, it
parks with a `KNOWN_SHORTCOMINGS.md` entry and ships nothing. Wrong bit
positions are worse than absent ones: a designer who trusts a wrong bit range
writes a driver that silently misconfigures silicon.

**Blocked by:** 05 — Register summary tables

**Status:** needs-info — waiting on the reference register-map PDF

- [ ] Column-span → bit-range mapping is derived geometrically from the bit
      header row's cell boundaries, not from cell text alone
- [ ] Accuracy gate: every field of a hand-verified sample of registers from
      the reference document matches name, bit range, access, and reset
      exactly — **100%, no partial credit**
- [ ] Registers whose bit fields cannot be extracted keep their summary record
      with `fields: []` and a recorded reason; they are not dropped
- [ ] Reserved and unnamed bit ranges are represented honestly rather than
      omitted, so a field list's coverage of the register width is checkable
- [ ] Bit ranges are validated against the register width; an overlap or
      overflow rejects the register's field set with a reason
- [ ] If the gate fails: no partial bit-field data ships, a
      `KNOWN_SHORTCOMINGS.md` entry records what was attempted and what broke,
      and the ticket closes as parked rather than as done

---

Source: `.scratch/design-time-content/SPEC.md`
