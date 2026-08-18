# 05 — Expert packs (`dsa pack` / `dsa unpack`)

**What to build:** Make a corpus portable. A pack is a self-describing
directory (with an optional archive form) containing the index, records,
cards, pins, registers, plot catalog, the Phase 5 agent protocol document, the
Phase 7 audit grade, and a `MANIFEST.json` with a sha256 per file plus the
`PIPELINE_VERSION` it was built at.

The point: an agent working in the designer's **own** schematic repository
drops in a pack and is immediately an expert on those parts — no clone of this
repo, no network.

**Blocked by:** Phase 7 tickets 05 (audit) and 07 (families)

**Status:** ready-for-agent

- [ ] `dsa pack --part X --out X.dsapack` produces a pack; `--family` and
      `--project` produce the family and project variants
- [ ] `MANIFEST.json` lists every file with its sha256, the pack's part/family
      /project identity, the `PIPELINE_VERSION`, and the audit grade
- [ ] `dsa unpack` verifies **every** hash before writing **anything**
- [ ] A pack with one corrupted file is **refused whole**, naming the failing
      file, leaving no partial import — asserted
- [ ] A pack round-trips: pack → unpack into a clean temporary directory →
      `dsa ask` answers correctly there with no access to the source corpus —
      asserted end to end
- [ ] A pack built at an older `PIPELINE_VERSION` is loadable or refused with
      a clear message; whichever is chosen is documented and asserted
- [ ] The pack carries enough of the agent protocol that a cold agent knows
      how to use it without this repo's docs
- [ ] Pack size is measured and recorded for the phase report

---

Source: `.scratch/design-loop/SPEC.md`
