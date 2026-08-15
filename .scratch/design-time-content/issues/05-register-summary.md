# 05 — Register summary tables (`registers.json`, `dsa regs`)

**What to build:** Register maps as a first-class artifact — the thing that
makes an agent useful during bring-up rather than only during schematic
capture.

**Routing change, called out explicitly:** `DocType.REGISTER_MAP` currently
prefers `pdf_text` for every vendor (paragraphs only, no tables). This ticket
routes it to `pdf_layout` so tables exist at all. That is a deliberate change
to a caveat documented in both `README.md` and `AGENTS.md`, and it invalidates
cached extractions for register-map documents.

Scope here is shape (a) — the **register summary** table: address / name /
reset / access — handled directly by the device-table abstraction. Bit fields
are ticket 06.

CLI `dsa regs --part X [--name] [--addr 0x1A04] [--field] [--json]`;
MCP `find_register`.

**Blocked by:** 04 — Pins (proves the shared abstraction on the easier shape
first); **and on the reference register-map PDF being added to the repo**

**Status:** needs-info — waiting on the reference register-map PDF. A register
parser written without a real document to gate against would be fiction.
Synthetic PyMuPDF fixtures can begin at the unit level in the meantime.

- [ ] `REGISTER_MAP` documents route to `pdf_layout`; the `README.md` and
      `AGENTS.md` caveats are rewritten in the same change
- [ ] `PIPELINE_VERSION` bumped so cached register-map extractions invalidate
- [ ] Addresses carry both verbatim and parsed integer forms; a hex address
      that fails to parse stays verbatim-only rather than being guessed
- [ ] `dsa regs --addr 0x1A04` resolves by parsed value, so `0x1A04`,
      `0x1a04`, and `6660` all find the same register
- [ ] Golden register questions on the reference document — address→name,
      name→reset, name→access — verify at 100% with page cites
- [ ] A register table failing validation is rejected with a recorded reason,
      not partially emitted
- [ ] Companion documents that are *not* register maps keep their current
      `pdf_text` behaviour unchanged

---

Source: `.scratch/design-time-content/SPEC.md`
