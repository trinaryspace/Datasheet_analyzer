# 02 — Revision awareness + staleness surfacing

**What to build:** The phase's safety feature. Revisions are parsed today
(`SBASA41E`, `Rev. I`) and then never questioned — so the tool would answer
from a superseded datasheet with full confidence and a valid page cite.

Additive inventory fields: `revision_checked_at`, `upstream_revision`,
`staleness` (`current | stale | unknown`).

`dsa check-revisions [--part X | --all]` is an **explicit, opt-in, network**
command — never part of `build`, so builds stay offline by construction.

Staleness surfaces in four places, and the fourth is the one that protects a
design decision:

```
⚠ This corpus is built from SBASA41E; SBASA41F is available upstream
  (checked 2026-08-15). Verify before committing to silicon.
```

## Empirical finding — read before designing the comparison

Measured against the live TI servers on 2026-08-18 (the repo owner ran this,
with network; the implementing agent has none):

| Part | Upstream URL | Result |
|---|---|---|
| LM741 | `lit/ds/snosc25d/snosc25d.pdf` | 200 — **same revision** SNOSC25D, **different sha256** |
| AFE7950 | `lit/ds/sbasa41e/sbasa41e.pdf` | 200 — **same revision** SBASA41E, **different sha256** |
| AFE7953 | `lit/ds/sbasan1a/sbasan1a.pdf` | 200 — same revision, different sha256 |
| LMX1204 | `lit/ds/snas800b/snas800b.pdf` | 200 — same revision, **sha256 identical** |

Root cause, confirmed by diffing the pages: TI **regenerates the "PACKAGE
MATERIALS INFORMATION" addendum with the current date on every download**.
LM741 printed page 15 reads `10-Aug-2026` upstream and `15-Jul-2025` in the
local copy; the rest of the document is byte-identical in content. AFE7950
additionally carries one *extra* local page (a tray addendum at printed
p.139), so local pages 139+ are offset by one against a fresh fetch while
pages 1–138 align exactly.

**Therefore a TI datasheet's sha256 is not stable over time — it changes
daily.** A design that treats "hash differs" as "a new revision is available"
will raise a false staleness alarm on every TI part every day, which trains
the user to ignore the one warning in this repo that protects a design
decision.

The comparison must therefore be **revision-first**: a corpus is `stale` only
when the parsed upstream *revision identifier* differs from the built one. A
hash difference with an identical revision is **not** staleness — it is at
most a `content-drift` note, and the honest wording says the document was
regenerated rather than revised.

### Blocking prerequisite — the revision parser is wrong for LMX1204

Revision-first comparison is only as good as the parse, and the parse is
broken for one of the seven documents in this repo. Verified by calling the
function directly:

```
sniff_revision('tests/fixtures/pdf/lmx1204.pdf')  ->  'SYSREFOUT0'   # WRONG
                                                       expected 'SNAS800B'
```

`src/datasheet_analyzer/extract/pdf_structure.py:78` defines

```python
_TI_DOC_ID = re.compile(r"\bS[A-Z]{2}[A-Z0-9]*\d[A-Z0-9]*\b")
```

which happily matches the signal name `SYSREFOUT0` (`S` + `YS` + `REFOUT` +
`0`), and `sniff_revision` takes `.search()` — the **first** match on the
page. On LMX1204 page 1 the matches are, in order:
`['SYSREFOUT0', 'SYSREFOUT1', 'SYSREFOUT2', 'SYSREFOUT3', 'SNAS800B']`, so a
pin name wins and the real literature number is last.

Confirmed correct for the other six: LM741 `SNOSC25D`, AFE7950 `SBASA41E`,
LMX1204 register map `SNAU269A`, AD9081 `Rev. 0`, HMC520A `Rev. A`,
QPA1003P `Rev. I`.

Real TI literature numbers are four letters followed by 3–4 alphanumerics
containing a digit (`SNAS800B`, `SBASA41E`, `SNOSC25D`, `SNAU269A` — all 8
characters). `SYSREFOUT0` is 10. Tightening the shape and preferring a
document-id-like token over a signal name fixes it; do not simply switch to
"last match", which is incidental rather than principled.

- [ ] `sniff_revision` returns `SNAS800B` for `tests/fixtures/pdf/lmx1204.pdf`
      — asserted, with the other six documents asserted unchanged as a
      regression guard
- [ ] Staleness is decided by the **parsed revision identifier**, never by a
      hash difference alone — asserted with a fixture whose hash differs and
      whose revision does not, which must NOT report `stale`
- [ ] A hash difference under an unchanged revision is reported distinctly
      (e.g. `content-drift`) with wording that does not imply a new revision
- [ ] `dsa check-revisions` detects a stale corpus against a recorded fixture
      and records `upstream_revision` + `revision_checked_at`
- [ ] `build` performs **no** network revision check — asserted, so offline
      builds stay offline
- [ ] The staleness banner appears in **all four** surfaces — `INDEX.md`,
      `dsa status`, `dsa audit`, and the answer-pack footer — each asserted
      separately. A warning present in only three is the failure mode this
      test exists to catch.
- [ ] A never-checked corpus reads `unknown`, distinct from `current`, and the
      answer footer says "revision not checked" rather than implying currency
- [ ] MCP responses carry the staleness state so a remote agent sees it too
- [ ] The check degrades honestly when the network is unavailable: `unknown`,
      a warning, no crash, no stale-to-current transition

---

Source: `.scratch/reach-and-trust/SPEC.md`
