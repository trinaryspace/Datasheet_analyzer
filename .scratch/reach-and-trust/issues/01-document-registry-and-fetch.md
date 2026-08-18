# 01 — Document registry + `dsa fetch`

**What to build:** A checked-in registry (`registry/datasheets.yaml`) mapping
part → vendor, doc type, url, revision, sha256, retrieved_at, and companion
documents; plus `dsa fetch` to resolve, download, hash-verify, and register.

Deterministic and hermetically testable, with no scraping and no search API —
the scope decision recorded in the SPEC. The registry grows by use:
`dsa fetch --url <u> --part X` adds an entry, and an agent that finds a URL
can call it itself.

`dsa fetch --project rf-frontend` fetches everything a project needs that is
not already present — the BOM → corpora path, end to end.

**Blocked by:** —

**Status:** ready-for-agent

> **Measured note added mid-run by the repo owner (2026-08-18, with network).**
> All four derived `ti_lit_ds(<LIT>)` URLs in the seeded registry resolve
> HTTP 200, so the derivation rule is sound. But TI **regenerates the
> "PACKAGE MATERIALS INFORMATION" addendum with the current date on every
> download**, so a TI datasheet's sha256 changes daily while its revision
> identifier stays put (LM741 p.15 reads `10-Aug-2026` upstream vs
> `15-Jul-2025` locally; only LMX1204 hashed identically).
>
> A `sha256` recorded with `sha256_origin: local_file:` will therefore
> mismatch a fresh fetch of the same revision, essentially always, for TI
> parts. Treat "hash differs" as *document regenerated*, not *new revision*:
> the mismatch warning must not assert a new revision when the parsed
> revision identifier is unchanged. Ticket 02 carries the full evidence table
> and owns the staleness decision.

- [x] `dsa fetch AFE7950` resolves, downloads, verifies sha256, registers into
      the part inventory, and is ready for `dsa build`
- [x] A sha256 mismatch **warns loudly and stops**, naming the likely cause (a
      new upstream revision); `--accept-new-revision` records the new hash and
      revision — asserted against a recorded fixture
- [x] A registry miss errors with a message naming `--url`; it never guesses a
      URL and never falls back to a search
- [x] `--url` writes a well-formed registry entry including the fetched
      revision and hash
- [x] `dsa fetch --project X` fetches only what is missing, and reports what
      it skipped
- [x] All tests run through `ReplayFetcher`; an unrecorded URL is a hard error
- [x] Registry entries for the six existing parts are seeded, so the registry
      ships non-empty

---

Source: `.scratch/reach-and-trust/SPEC.md`
