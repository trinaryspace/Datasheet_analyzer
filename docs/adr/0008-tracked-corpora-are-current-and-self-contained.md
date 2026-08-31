# 0008 — A tracked corpus is current, and self-contained

Phase 6 shipped, and merging it into `feat/gui-workbench` turned eight
integration gates red without a line of code being wrong. Every failure was
corpus staleness: the branch's local `parts/LMX1204` had been built at pipeline
0.4.0 against code at 0.5.0, and the derived artifacts those gates read
(`pins.json`, `registers.json`) lived in a shared library the branch's store
did not have. Refreshing the untracked corpora and merging the library turned
all eight green with no code change.

Underneath that was a durable version problem this repository has carried since
commit `c1d6180` ("data: rebuild AFE7950 and AFE7953 at pipeline 0.4.0") was
reverted by `a8f93f8`: **the two tracked reference corpora sat at pipeline
0.1.0 while the code was at 0.5.0**, and the gates that read them got their
0.4.0-or-better material from untracked local data and a gitignored library —
neither of which a fresh clone has. Phase 6.5's wave 2 is the moment this gets
decided, because wave 2 is what rebuilds.

Three questions, answered here rather than in passing.

## 1. A tracked corpus is at the current `PIPELINE_VERSION`

A corpus committed to this repository is a **fixture**: something a gate reads
in order to make a claim about the pipeline. A fixture built by an older
pipeline has quietly stopped testing what it says it tests — every rule the
pipeline has learned since is absent from the bytes, and the gate that reads it
passes on the strength of a build nobody can reproduce from this tree.

So: **`parts/<PART>/manifest.json` for a tracked corpus carries
`pipeline_version == PIPELINE_VERSION`, and a test asserts it.** A version bump
that changes published output is not landed until the tracked corpora are
rebuilt in the same change. That is a real cost — Phase 6.5 paid it, at roughly
20 minutes of figure fetching per reference part — and it is smaller than the
cost of a green suite that proves nothing.

The alternative, pinning the tracked corpora as historical artifacts and
testing only freshly built ones, was rejected for a reason specific to this
tool: the AFE7953 benchmark's ground truth *cannot* be checked against a fresh
build (no recorded TI document-viewer pages exist for that part), so the
committed corpus is the only substrate its 13 golden questions have. A pinned
fixture would freeze that benchmark against a pipeline nobody runs.

## 2. `library/` is not tracked; tracked corpora are published self-contained

Today's mixture is the one thing that is not defensible: `/library/` is
gitignored while committed manifests reference `@library/docs/…`, so a corpus
published to the shared store is **unreadable on a fresh clone**. That is
exactly what `c1d6180` shipped and what `a8f93f8` reverted, and the measured
cost was recorded: the golden corpus check scored 3/21 for AFE7950 and 1/13 for
AFE7953, every failure "corpus has answer ❌, page cite ✅" — the corpus could
not be read at all.

Both halves of the mixture are individually defensible. Tracking the library
would make `@library/` references resolvable everywhere. It is rejected on what
the library actually is: `.gitignore` already says it — *"a local shelf — whose
PDFs it describes differs per machine"*. On this machine it holds 200+
documents from a GUI test round, most of which have nothing to do with this
repository's fixtures. A shelf is working state; committing it would put one
developer's reading list in everyone's clone, and the two reference corpora
would be a rounding error inside it.

So: **the shared store stays untracked, and a corpus that is committed is
published self-contained** — every section, `specs.json`, `plots.json`,
`pins.json`, `registers.json`, `search_index.json` and figure under
`parts/<PART>/docs/<doc>/`, with `library_root` empty and no `@library/`
reference in the manifest. `dsa build --self-contained` is that mode, and it is
the mode the tracked reference corpora are built in.

Publish-once/reference-many is untouched for the working shelf, which is where
it earns its keep: a vendor note applying to 40 parts is stored once. The rule
is only about what gets committed.

The corollary is the shadowing rule that hid a complete library copy behind a
stale part-local one (`retrieve.index._doc_dirs` prefers `parts/<PART>/docs/`):
for a self-contained corpus the part-local copy *is* the corpus, so the
preference is right rather than dangerous.

## 3. A corpus-reading gate skips, with the version in the reason

Failing is loud but breaks a clone that has not built anything; skipping is
portable but can hide a genuine regression. The resolution is to split the two
jobs:

- **A gate that reads a corpus skips when the corpus is absent or predates the
  code, and names the version it found in the skip reason.** "AFE7950 is built
  at pipeline 0.1.0, this code is 0.5.0" is a sentence a developer can act on;
  a red gate on a fresh clone is one they learn to ignore.
- **One test asserts, unconditionally, that the tracked corpora are current**
  (`tests/integration/test_corpus_currency.py`). It cannot be skipped, because
  its inputs are committed. That is where the regression that skipping could
  hide is caught instead.

The two together mean a stale corpus is always reported somewhere, and never
reported as a failure of the code that reads it.

## Consequences

- Phase 6.5 rebuilds `parts/AFE7950` and `parts/AFE7953` at pipeline 0.5.0,
  self-contained, and commits them. Their `@library/` references are gone.
- Both parts gain a `search_index.json` for the first time, so the
  `search unavailable` gap recorded in `KNOWN_SHORTCOMINGS.md` closes and
  `PARTS_WITHOUT_SEARCH` becomes empty.
- Every future pipeline-version bump owns the rebuild of the tracked corpora.
  The `--self-contained` flag exists so that rebuild cannot accidentally
  reintroduce a reference the clone cannot follow.
- **Design cards are the one exception**, and `/parts/*/cards/` is gitignored.
  A card is a derived cache keyed by `DSA_CARD_VERSION` and the corpus it was
  computed from; `load_or_build_card` rebuilds it on demand and `dsa build`
  retires it, so committing it would churn on every rules change and never be
  the artifact a reader cites. Everything a citation can land on — sections,
  `specs.json`, `plots.json`, `pins.json`, `registers.json`,
  `search_index.json`, figures — is tracked.
- The rebuild's diff is small, which is the other reason this is affordable:
  514 figures and most section markdown came back byte for byte, and 40 files
  changed across the two parts.
