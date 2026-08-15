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

- [ ] `dsa fetch AFE7950` resolves, downloads, verifies sha256, registers into
      the part inventory, and is ready for `dsa build`
- [ ] A sha256 mismatch **warns loudly and stops**, naming the likely cause (a
      new upstream revision); `--accept-new-revision` records the new hash and
      revision — asserted against a recorded fixture
- [ ] A registry miss errors with a message naming `--url`; it never guesses a
      URL and never falls back to a search
- [ ] `--url` writes a well-formed registry entry including the fetched
      revision and hash
- [ ] `dsa fetch --project X` fetches only what is missing, and reports what
      it skipped
- [ ] All tests run through `ReplayFetcher`; an unrecorded URL is a hard error
- [ ] Registry entries for the six existing parts are seeded, so the registry
      ships non-empty

---

Source: `.scratch/reach-and-trust/SPEC.md`
