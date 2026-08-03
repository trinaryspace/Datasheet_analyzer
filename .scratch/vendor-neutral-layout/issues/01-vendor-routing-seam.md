# 01 — Vendor routing seam + additive schema

**What to build:** The VendorProfile registry (routing record: detector,
preference chain, evidence) wired for `ti → ti_html`, evidence-pinned
vendor detection at acquire time, `--vendor` override on build/add-doc,
status surfacing, additive schema fields (vendor + evidence on the
inventory record; vendor + extraction stats slot on the manifest),
`PIPELINE_VERSION` bump, and atomic extraction-cache writes. Behavior on
the TI path is unchanged — this is the seam every other ticket builds on.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] A build of an existing TI part produces an identical corpus; `dsa status` shows vendor `ti` with its detection evidence
- [ ] `dsa build <pdf> --part X --vendor adi` pins vendor `adi` (with the override recorded as evidence) into the part's inventory
- [ ] Pinning persists across builds; a re-run without `--vendor` keeps the pinned vendor, and a detection that contradicts the pinned value logs a loud warning instead of re-routing
- [ ] A rebuilt part's manifest carries the vendor and the new pipeline version
- [ ] Two concurrent writes to the same extraction-cache entry never leave a corrupt file (atomic write-temp + rename)
- [ ] All existing tests pass unchanged (behavioral parity on the TI path)

---

Source: `.scratch/vendor-neutral-layout/SPEC.md`
