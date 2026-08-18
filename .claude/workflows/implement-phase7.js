export const meta = {
  name: 'implement-phase7',
  description: 'Implement Phase 7 (Reach & Trust) tickets 01-08 from .scratch/reach-and-trust',
  whenToUse: 'Phases 5 and 6 are landed. This is the breadth phase: fetch registry, revision staleness, diff-rev, errata links, audit scorecard, golden generation, families, scale gate.',
  phases: [
    { title: '01 Registry + fetch' },
    { title: '02 Revision awareness' },
    { title: '03 diff-rev' },
    { title: '04 Errata cross-linking' },
    { title: '05 Audit scorecard' },
    { title: '06 Golden generation' },
    { title: '07 Families' },
    { title: '08 Scale gate + report' },
    { title: 'Wrap-up' },
  ],
}

// ---------------------------------------------------------------------------
// Harness lineage
// ---------------------------------------------------------------------------
// Same spine as implement-phase6-tail.js, which is the version that survived:
// sequential ticket loop (the tickets are a dependency chain, not a fan-out),
// parallelism routed into read-only verification where there are no file
// conflicts, withRetry around every agent call so a transient 529 cannot kill
// finished work, and EVERY schema field bounded so a long-winded return value
// cannot blow the StructuredOutput retry cap.
//
// What is new for phase 7: this phase's headline features are the ones that
// touch the network, and agents run OFFLINE. The offline boundary is stated
// explicitly in CONTEXT below and re-stated per ticket, because the failure
// mode here is not a crash - it is an agent quietly inventing a URL, a hash,
// or an upstream revision to make a criterion look met.

const PY = '.venv/Scripts/python.exe'
const PYTEST = `${PY} -m pytest tests/`
const RUFF = `${PY} -m ruff check src tests`
const TRACKER = '.scratch/reach-and-trust'
const MAX_REPAIRS = 2

const BASELINE_TESTS = (args && args.baselineTests) || 1663

const NETWORK = `
THE OFFLINE BOUNDARY - READ THIS TWICE.

You have NO NETWORK. Phase 7 is the phase whose features are *about* the network,
so this is where the temptation to fabricate is highest. The rules:

  - NEVER write a URL you cannot justify from something already in this repo.
    A plausible-looking vendor URL that 404s is worse than no entry at all: it
    puts a wrong document in front of a hardware designer.
    Legitimate sources for a URL:
      (a) a URL literally present in the repo already (grep for it), or
      (b) the TI document-viewer / literature pattern already encoded in
          src/datasheet_analyzer/extract/ti_html.py, derived from a literature
          number you actually parsed out of the PDF in this repo.
    Anything from (b) is a DERIVED url and MUST be recorded as unverified
    (e.g. url_verified: false) and reported as unconfirmed by the CLI until a
    live fetch confirms it.
  - NEVER invent a sha256, an upstream revision, an HTTP response, or a
    retrieved_at date. A sha256 computed from a PDF that is actually in this
    repo is real and welcome - compute it. One you "expect" upstream is a lie.
  - Tests stay hermetic (invariant 4). Use the existing injectable Fetcher
    seam in src/datasheet_analyzer/extract/http.py and the recorded fixtures in
    tests/fixtures/recorded_http/ and tests/fixtures/recorded_http_bin/.
    Do NOT invent a second replay mechanism.
  - When a criterion genuinely cannot be met offline, IMPLEMENT THE MACHINERY
    AND SAY SO. Write the code, test it against a recorded or synthetic
    fixture, and record the live step in Reports/PHASE_7_LIVE_RUN.md as
    something the repo owner runs with network. Honest degradation is invariant
    7 and it is the correct outcome here - a criterion marked met by a
    fabricated fixture is a defect that outlives this run.
`.trim()

const TICKETS = [
  {
    id: '01',
    phase: '01 Registry + fetch',
    file: '01-document-registry-and-fetch.md',
    title: 'Document registry + dsa fetch',
    notes: [
      'This is the ticket where fabrication is most tempting. Re-read the offline boundary.',
      '',
      'SEED THE REGISTRY FROM WHAT IS PHYSICALLY HERE. These PDFs are in the repo root:',
      '  afe7950.pdf  afe7953.pdf  ad9081.pdf  hmc520a.pdf  lm741.pdf  QPA1003P.pdf',
      'For each, the sha256 is REAL and computable offline - compute and record it. That',
      'gives `dsa fetch` a genuine hash-verification path to test against, with no network.',
      'The LMX1204 datasheet was used by phase 6; find where it lives before assuming it is',
      'absent (check .scratch/tmp/build/LMX1204 and git history for the source path).',
      '',
      'The url field for those entries: derive it only per the rules above, and mark derived',
      'URLs unverified. It is completely acceptable for a seed entry to carry a null url with',
      'a recorded reason - `dsa fetch` then tells the owner to supply `--url`. That is the',
      'designed growth path, not a gap.',
      '',
      'The fetch seam: reuse the Fetcher Protocol in src/datasheet_analyzer/extract/http.py.',
      'That one is typed URL -> str (HTML). Binary documents need a sibling seam; add it in',
      'the same module and in the same idiom rather than starting a parallel abstraction, and',
      'point it at tests/fixtures/recorded_http_bin/ for tests.',
      '',
      'Do NOT let `dsa build` acquire anything over the network as a side effect. Builds stay',
      'offline by construction; fetch is the only command that may reach out.',
    ].join('\n'),
  },
  {
    id: '02',
    phase: '02 Revision awareness',
    file: '02-revision-awareness.md',
    title: 'Revision awareness + staleness surfacing',
    notes: [
      'The plan calls the answer-pack staleness footer "the single most dangerous behaviour',
      'this tool can have" if it is missing. All FOUR surfaces are acceptance criteria and all',
      'four need a test: dsa status, the INDEX.md banner, dsa audit (ticket 05 consumes the',
      'field - make sure the field exists and is documented even though audit lands later),',
      'and the answer-pack footer.',
      '',
      '`dsa check-revisions` is explicitly opt-in and network-touching. Build it against the',
      'injectable fetcher and test it with a recorded/synthetic response. NEVER let build,',
      'ask, query, search, or verify call it implicitly.',
      '',
      'staleness has three states and `unknown` is the honest default for every corpus that',
      'has never been checked. A corpus that has not been checked must NOT read as `current`.',
      'That inversion is the whole safety argument of this ticket.',
    ].join('\n'),
  },
  {
    id: '03',
    phase: '03 diff-rev',
    file: '03-diff-rev.md',
    title: 'dsa diff-rev',
    notes: [
      'You have exactly one revision of every part in this repo, so the honest test fixture is',
      'a SYNTHETIC second revision: take a built corpus, derive a modified copy with known',
      'edits (a changed spec value, a retitled section, an added pin, a changed register reset',
      'value), and assert diff-rev finds exactly those and nothing else. That is a stronger',
      'test than a real second revision would give you, because the expected delta is exact.',
      'Put the generator under tests/fixtures/synthetic/ in the existing idiom.',
      '',
      'Use the phase 6 numeric layer for the human-readable delta ("TJ max 105 -> 125 C").',
      'Anything not numerically comparable goes under "review by hand" VERBATIM. Do not score',
      'it, do not guess a direction, and report the unparsed population explicitly - that rule',
      'from AGENTS.md applies to diff-rev exactly as it applies to compare.',
    ].join('\n'),
  },
  {
    id: '04',
    phase: '04 Errata cross-linking',
    file: '04-errata-cross-linking.md',
    title: 'Errata cross-linking',
    notes: [
      'Independent of 01-03. If no real errata document is in the repo, build the linker',
      'against a synthetic errata fixture with hand-checked expected targets, and say so.',
      'Check first: `dsa add-doc` already registers companion documents, so grep the repo and',
      'the built corpora for an errata doc before assuming there is none.',
      '',
      'THE CRITICAL BEHAVIOUR: an errata item the matcher could not place must still be',
      'published, under an explicit "unlinked errata" heading. Losing an erratum silently is',
      'the worst failure this ticket can produce, and it needs a test that would fail if the',
      'unlinked list were dropped.',
      '',
      'Matching is deterministic and every link records what it matched on. No model call',
      'anywhere in this path (invariant 8).',
    ].join('\n'),
  },
  {
    id: '05',
    phase: '05 Audit scorecard',
    file: '05-audit-scorecard.md',
    title: 'dsa audit scorecard + rubric',
    notes: [
      'The rubric must be DATA-DRIVEN: a test that edits registry/audit_rubric.yaml and',
      'asserts the grade moves is an acceptance criterion, not a nicety. Thresholds hardcoded',
      'in Python fail this ticket.',
      '',
      'A metric that cannot be computed for a corpus is `null` and is reported as unavailable.',
      'It must NOT be silently treated as 0 (which would defame a good corpus) or as full',
      'marks (which would flatter a bad one). State the chosen convention in the grade output.',
      '',
      'parts/AFE7950 and parts/AFE7953 are published at an OLDER schema than the current',
      'pipeline - no record ids, no search_index.json - so several metrics will be null for',
      'them and `dsa verify` currently exits 1 on both. Do not paper over that: it is exactly',
      'the fleet-honesty case audit exists to expose. Grade them, show the nulls, and let the',
      'output say the corpus needs a rebuild.',
      '',
      'get_audit(part) as an MCP tool is part of this ticket per the plan. The deliverable',
      'sentence is an agent being able to downgrade its own confidence language before',
      'answering.',
    ].join('\n'),
  },
  {
    id: '06',
    phase: '06 Golden generation',
    file: '06-golden-generation-assist.md',
    title: 'Golden suggest/confirm',
    notes: [
      'Invariant 5 gains a clause in this ticket: generated candidates NEVER count toward',
      '`dsa verify` until a human confirms them. The test that asserts an unconfirmed',
      'candidate does not move the verify result is the single most important test here.',
      '',
      '`golden confirm` is interactive by design, and hermetic tests cannot drive a TTY. Split',
      'it: a pure, testable core that applies a list of accept/edit/reject decisions to a',
      'candidate file, plus a thin interactive shell over it. Give the core a non-interactive',
      'entry point (a decisions file or --accept-ids) so tomorrow it can also be scripted for',
      'a 20-part fleet. Test the core directly.',
      '',
      'Candidate generation is deterministic and stratified across sections, backends, and',
      'confidence grades - assert the stratification, not just the count. An all-easy-lookup',
      'candidate set technically satisfies "n=20" and defeats the purpose.',
      '',
      'Generation is templated from records that already carry verbatim answers and pages.',
      'No model call (invariant 8).',
    ].join('\n'),
  },
  {
    id: '07',
    phase: '07 Families',
    file: '07-families.md',
    title: 'Part families + delta index',
    notes: [
      'AFE7950 and AFE7953 are the real family and share 39 identically-named sections - that',
      'is the intended demonstration. BUT both are published at an old schema.',
      '',
      'FIRST, spend real effort on this question: can they be rebuilt OFFLINE? There are many',
      'recorded HTTP fixtures in tests/fixtures/recorded_http/ named by sha1(url)[:16].html,',
      'which is exactly the CachingFetcher cache layout in src/datasheet_analyzer/extract/',
      'http.py. If pointing the cache at those fixtures rebuilds AFE7950/AFE7953 offline, do',
      'it - it unblocks this ticket, ticket 05s fleet table, and the phase gate. If the',
      'fixtures are incomplete, do NOT fake it: record precisely which URLs are missing in',
      'Reports/PHASE_7_LIVE_RUN.md as a live step, and build the family demonstration from',
      'whatever members you CAN build offline.',
      '',
      'Family membership is declared explicitly in registry/families.yaml. An auto-suggest',
      'helper may PROPOSE groupings; it must never assume one. Silent family membership would',
      'let a designer read the wrong parts spec.',
      '',
      'The token win is a criterion, not a claim: measure the family index against the sum of',
      'its members indexes and record the real numbers.',
    ].join('\n'),
  },
  {
    id: '08',
    phase: '08 Scale gate + report',
    file: '08-scale-gate-and-report.md',
    title: 'Scale gate + PHASE_7_REPORT',
    notes: [
      'READ THIS BEFORE ANYTHING ELSE - THIS TICKET IS RESCOPED, DELIBERATELY, BY THE REPO',
      'OWNER, AND THE RESCOPE IS BINDING.',
      '',
      'The ticket as written requires >=20 parts onboarded through `dsa fetch` across >=3',
      'vendors. That needs NETWORK, which you do not have. There are six datasheet PDFs in',
      'this repo. You CANNOT satisfy the literal criterion and you MUST NOT pretend to.',
      'Fabricating a fleet - synthetic "parts" dressed up as onboarded silicon, invented URLs,',
      'made-up hashes - would corrupt the one artifact this whole roadmap exists to produce.',
      '',
      'WHAT YOU BUILD INSTEAD, in full:',
      '',
      '  1. `dsa scale-gate` - a real command that EXECUTES the gate against whatever fleet is',
      '     present and reports pass/fail per criterion with the measured number beside it:',
      '     part count, distinct vendor count, project size, family delta correctness, audit',
      '     grade distribution, golden coverage and verify rate across the fleet, and measured',
      '     token numbers (per-part corpus, family index vs sum of member indexes, answer-pack',
      '     mean). --json for tooling. It must be able to FAIL and say why.',
      '  2. Run it offline on the parts that exist. Record the true result. A red gate with',
      '     honest numbers is a PASS for this ticket; a green gate with invented ones is not.',
      '  3. Reports/PHASE_7_LIVE_RUN.md - the runbook the owner executes tomorrow WITH network',
      '     to close the criteria you could not. Exact commands in order, what each should',
      '     print, what a failure looks like, and how to recover. Consolidate every live step',
      '     that earlier tickets deferred into this one document.',
      '  4. Reports/PHASE_7_REPORT.md - the phase report, with the rescope stated plainly at',
      '     the very top, not buried.',
      '',
      'Also close the phase properly: goldens extended, AGENTS.md invariant 5 clause landed,',
      'CONTEXT.md nouns (Family, Registry entry, Staleness, Audit grade), README updated.',
      '',
      'PIPELINE_VERSION: the plan says 0.4.0 -> 0.5.0, but phase 6 already moved it to 0.5.0.',
      'The correct move for phase 7 is 0.5.0 -> 0.6.0. Verify the current value in',
      'src/datasheet_analyzer/config.py before changing it.',
    ].join('\n'),
  },
]

// ---------------------------------------------------------------------------
// Schemas - EVERY field bounded (this is what killed the first phase-6 tail).
// ---------------------------------------------------------------------------

const IMPL_SCHEMA = {
  type: 'object',
  required: ['summary', 'files_changed', 'tests_added', 'self_gate_green'],
  properties: {
    summary: { type: 'string', maxLength: 1200, description: 'What was built. 3-6 sentences, MAX 1200 chars.' },
    files_changed: { type: 'array', maxItems: 40, items: { type: 'string', maxLength: 120 } },
    tests_added: { type: 'array', maxItems: 40, items: { type: 'string', maxLength: 120 } },
    self_gate_green: { type: 'boolean', description: 'True only if you personally ran pytest AND ruff and both passed' },
    deviations: { type: 'array', maxItems: 8, items: { type: 'string', maxLength: 300 } },
    open_items: { type: 'array', maxItems: 8, items: { type: 'string', maxLength: 400 } },
    live_steps: {
      type: 'array',
      maxItems: 8,
      items: { type: 'string', maxLength: 300 },
      description: 'Steps that need NETWORK and were therefore deferred to the owner. One line each.',
    },
  },
}

const GATE_SCHEMA = {
  type: 'object',
  required: ['green', 'pytest_exit', 'ruff_clean', 'detail'],
  properties: {
    green: { type: 'boolean' },
    pytest_exit: { type: 'integer' },
    ruff_clean: { type: 'boolean' },
    tests_collected: { type: 'integer' },
    failures: { type: 'array', maxItems: 25, items: { type: 'string', maxLength: 200 } },
    detail: { type: 'string', maxLength: 3000, description: 'Verbatim tail of failing output, truncated to 3000 chars, or "clean"' },
  },
}

const REVIEW_SCHEMA = {
  type: 'object',
  required: ['blocking', 'summary', 'findings'],
  properties: {
    blocking: { type: 'boolean' },
    summary: { type: 'string', maxLength: 800 },
    findings: {
      type: 'array',
      maxItems: 12,
      items: {
        type: 'object',
        required: ['what', 'severity', 'evidence'],
        properties: {
          what: { type: 'string', maxLength: 400 },
          severity: { type: 'string', enum: ['blocking', 'should-fix', 'note'] },
          evidence: { type: 'string', maxLength: 400 },
          fix: { type: 'string', maxLength: 400 },
        },
      },
    },
  },
}

const EXPLORE_SCHEMA = {
  type: 'object',
  required: ['diagnosis', 'alternatives', 'applied'],
  properties: {
    diagnosis: { type: 'string', maxLength: 1200 },
    alternatives: {
      type: 'array',
      maxItems: 4,
      items: {
        type: 'object',
        required: ['approach', 'tradeoffs', 'recommended'],
        properties: {
          approach: { type: 'string', maxLength: 500 },
          tradeoffs: { type: 'string', maxLength: 500 },
          recommended: { type: 'boolean' },
          violates_invariant: { type: 'string', maxLength: 200 },
        },
      },
    },
    applied: { type: 'boolean' },
    applied_approach: { type: 'string', maxLength: 400 },
    spec_amendment: { type: 'string', maxLength: 1500 },
  },
}

// ---------------------------------------------------------------------------
// Prompts
// ---------------------------------------------------------------------------

const BREVITY = `
YOUR STRUCTURED RETURN VALUE IS A SHORT HANDLE FOR THE ORCHESTRATOR, NOT A REPORT.
Hard limits, enforced by schema - exceeding them FAILS THE RUN:
  summary       <= 1200 chars
  open_items    <= 8 entries, <= 400 chars each
  deviations    <= 8 entries, <= 300 chars each
  live_steps    <= 8 entries, <= 300 chars each
  files_changed / tests_added  <= 40 entries each
Put full detail - measurements, tables, rationale, caveats - in
Reports/PHASE_7_REPORT.md and in code comments, where it belongs and persists.
An agent on the previous phase lost a completed ticket by trying to return a
multi-thousand-character result. Be disciplined here.
`.trim()

const CONTEXT = `
You are working in a git worktree of the datasheet_analyzer repo. Read these FIRST:

  1. AGENTS.md                          - architecture contract, INVARIANTS, definition of done
  2. CONTEXT.md                         - domain vocabulary
  3. Reports/PHASE_7_PLAN.md            - execution contract for this phase
  4. ${TRACKER}/SPEC.md                 - problem, solution, user stories, decisions
  5. docs/adr/0005-deterministic-derived-artifacts.md - invariant 8, still binding

ENVIRONMENT (Windows, Git Bash available):
  - Use the venv python EXPLICITLY: ${PY}
  - Tests:  ${PYTEST}      (note: addopts already has -q; do NOT add another -q or
                            pytest prints no summary line at all)
  - Lint:   ${RUFF}
  - Baseline entering this run: ${BASELINE_TESTS} tests passing, ruff clean.
    Your work must NEVER reduce that count or break those tests.

${NETWORK}

NON-NEGOTIABLE RULES:
  - AGENTS.md invariants are binding, including invariant 8 (deterministic derived
    artifacts): no model call in any derivation path; every derived field carries source
    (record id + page) and derivation (the named rule).
  - A field that cannot be filled stays null and says so. Never interpolate or default.
  - Verbatim strings are authoritative and NEVER mutated.
  - Any consumer that sorts, compares, or computes margins MUST report its unparsed
    population explicitly. Silently dropping unparseable rows from a decision is a defect.
  - Tests are HERMETIC: no network, no real LLM, no subprocess, no machine-state dependence,
    no dependence on wall-clock time or filesystem ordering.
  - Schema changes are ADDITIVE ONLY.
  - Land tests WITH the code.
  - NEVER weaken or delete an existing test, or change a golden's expected answer or page,
    to make something pass. That is a finding to report, not an edit to make quietly.
  - Do NOT run git commit, push, checkout, or stash. The workflow handles git.
  - Do NOT create git worktrees. Work in this one.
  - Do NOT modify .env, .venv/, or anything under .cache/.
  - Scratch files belong in .scratch/tmp/ (gitignored), never elsewhere in the tree.

${BREVITY}
`.trim()

function implPrompt(t, priorSummaries) {
  const prior = priorSummaries.length
    ? `\nWHAT ALREADY LANDED IN THIS RUN:\n${priorSummaries.map((s) => `  - ${s}`).join('\n')}\n`
    : ''
  const notes = t.notes ? `\nTICKET-SPECIFIC NOTES YOU MUST HEED:\n${t.notes}\n` : ''
  return `${CONTEXT}

YOUR TASK: implement ticket ${t.id} - ${t.title}.

Read the ticket file in full: ${TRACKER}/issues/${t.file}
Its checkbox list is the acceptance criteria. Every box must be genuinely satisfied by code
and by a test that would FAIL if the behaviour regressed.
${prior}${notes}
METHOD:
  1. Read the five context files, then the ticket.
  2. Explore the code you are extending. Match its style, naming, and idiom.
  3. Implement, writing tests alongside the code.
  4. Run ${PYTEST} and ${RUFF} yourself. Iterate until BOTH are clean.
  5. Update AGENTS.md / CONTEXT.md / README.md only where THIS ticket's criteria say to.
  6. Append any network-requiring step you had to defer to Reports/PHASE_7_LIVE_RUN.md
     (create it if absent) AND list it in live_steps.

Set self_gate_green true only if you actually ran both commands and both passed.`
}

function gatePrompt(t) {
  return `Run the objective gate for ticket ${t.id} (${t.title}) in the datasheet_analyzer worktree.

Run EXACTLY these two commands from the repo root:
  1. ${PYTEST}
  2. ${RUFF}

Rules:
  - green is true ONLY if pytest exited 0 AND ruff reported no issues.
  - Report the pytest exit code verbatim; do not infer it from output text.
  - Baseline entering this run was ${BASELINE_TESTS} tests. If tests_collected is LOWER,
    treat it as a failure and say so - it means tests were removed.
  - Truncate the detail field to 3000 chars. Do not paste a whole log.

Do NOT fix anything. Do NOT edit any file. You are a measuring instrument.`
}

function reviewPrompt(t, lens, implSummary) {
  const lenses = {
    criteria: `ACCEPTANCE-CRITERIA LENS.
Open ${TRACKER}/issues/${t.file} and walk its checkbox list ONE BOX AT A TIME. For each box
find the specific code and the specific test that satisfies it, cited as file:line. A box is
satisfied only if BOTH exist. A test that asserts code merely runs, without asserting the
behaviour the box describes, does NOT satisfy it.

Ticket 08 is deliberately rescoped: its >=20-part fleet criterion cannot be met offline, and
the correct outcome there is honest machinery plus a recorded live runbook. Judge it against
that rescope, NOT against the literal box. Every OTHER ticket is judged as written.

Mark blocking:true if any box is unmet or only cosmetically met.`,

    invariants: `INVARIANT LENS - special attention to HONESTY UNDER OFFLINE CONSTRAINTS.
Read AGENTS.md's invariants and docs/adr/0005-deterministic-derived-artifacts.md, then audit
the diff for:
  - A FABRICATED URL, sha256, upstream revision, retrieved_at date, or HTTP response. This is
    the cardinal sin of phase 7. For every URL added, find its justification: is it already
    in the repo, or derived from a literature number actually parsed from a PDF that is here?
    A derived URL that is not marked unverified is a finding.
  - A criterion marked satisfied by a fixture that pretends to be real upstream data.
  - ANY model call in a derivation path (invariant 8).
  - a derived value without a resolvable source (record id + page) or derivation name
  - an unfillable field interpolated, defaulted, or omitted instead of left null
  - staleness defaulting to 'current' for a corpus that was never checked
  - a network call reachable from build / ask / query / search / verify
  - a verbatim string mutated
  - a consumer that sorts/compares/computes margins WITHOUT reporting unparsed population
  - a test that reaches the network, spawns a subprocess, calls a real LLM, or depends on
    machine state, wall-clock time, or filesystem ordering
  - a non-additive schema change that breaks loading an existing corpus
Mark blocking:true for any real breach. Cite file:line.`,

    tests: `TEST-QUALITY AND REGRESSION LENS.
Audit tests added, and what happened to tests that already existed. Look for:
  - tautological or vacuous assertions
  - a test that would still pass if the feature were deleted or stubbed
  - any EXISTING test deleted, skipped, xfailed, or with a loosened assertion
  - any golden file whose expected answer or page was altered
  - phase-7 specific: is there a test that would FAIL if an unlinked erratum were dropped?
    if an unconfirmed golden candidate started counting toward verify? if the audit rubric
    stopped being data-driven? if the staleness footer vanished from the answer pack?
    A missing test for any of those, in the ticket that owns it, is blocking.
Run \`git diff --stat\` and \`git diff HEAD\` to see what changed.
Deleting or weakening an existing test is ALWAYS blocking. Cite file:line.`,
  }

  return `You are reviewing a just-completed implementation of ticket ${t.id} (${t.title}).
You are a REVIEWER: read and run read-only commands only. DO NOT EDIT ANY FILE.
Do not run git commit/push/checkout/stash.

The implementer reported:
"""
${implSummary}
"""
Treat that with professional skepticism - verify it against the actual code.

YOUR LENS:
${lenses[lens]}

Be specific and evidence-based; a finding without a file:line or verbatim quote is not a
finding. If the work is sound under your lens, say so plainly and set blocking:false - a
false blocking verdict stalls the run.

${BREVITY}`
}

function repairPrompt(t, attempt, gate, reviews) {
  const gateText = gate && !gate.green
    ? `OBJECTIVE GATE FAILED:\n  pytest exit: ${gate.pytest_exit}\n  ruff clean: ${gate.ruff_clean}\n  failures: ${(gate.failures || []).join(', ') || '(none listed)'}\n  detail:\n${gate.detail}\n`
    : 'Objective gate (pytest + ruff) is currently GREEN.\n'

  const reviewText = reviews
    .filter(Boolean)
    .map((r, i) => {
      const blockers = (r.findings || []).filter((f) => f.severity === 'blocking' || f.severity === 'should-fix')
      if (!blockers.length) return ''
      return `REVIEWER ${i + 1} (blocking=${r.blocking}): ${r.summary}\n${blockers.map((f) => `  - [${f.severity}] ${f.what}\n    evidence: ${f.evidence}\n    suggested fix: ${f.fix || '(none given)'}`).join('\n')}`
    })
    .filter(Boolean)
    .join('\n\n') || '(no reviewer findings)'

  return `${CONTEXT}

REPAIR PASS ${attempt} of ${MAX_REPAIRS} for ticket ${t.id} - ${t.title}.
Ticket file: ${TRACKER}/issues/${t.file}

${gateText}
${reviewText}

Fix these properly:
  - Fix the ROOT CAUSE. Do not silence a failing test, loosen an assertion, add a skip, or
    delete a test to make the gate pass. That is the one unacceptable outcome.
  - Do NOT resolve an offline-impossible criterion by inventing data. Degrade honestly and
    record the live step instead.
  - If a reviewer finding is WRONG, do not "fix" it - explain in deviations why, with
    evidence. Reviewers can be mistaken and you are allowed to say so.
  - Re-run ${PYTEST} and ${RUFF} until both pass.`
}

function explorePrompt(t, gate, reviews) {
  return `${CONTEXT}

ESCALATION for ticket ${t.id} - ${t.title}.
Ticket file: ${TRACKER}/issues/${t.file}

Implementation plus ${MAX_REPAIRS} repair passes have NOT satisfied this ticket as written.
Work out WHY and propose a way through rather than halting.

STEP 1 - DIAGNOSE the real root cause. Distinguish:
  (a) ticket fine, implementation approach wrong
  (b) ticket design conflicts with something real in the codebase
  (c) criteria unachievable offline, or self-contradictory as written
  (d) a reviewer is wrong and the work is correct

STEP 2 - propose 2-4 genuinely different approaches satisfying the ticket's INTENT (read the
SPEC's user stories; criteria are a means, not the end). For each: approach, tradeoffs,
whether it breaches an invariant. Proposing that the ticket be re-scoped around the offline
boundary is a valid and often correct outcome.

STEP 3 - ACT.
  - If one alternative is clearly right AND breaches no invariant, IMPLEMENT it, run
    ${PYTEST} and ${RUFF} until green, set applied:true.
  - If the call needs human judgment - breaches an invariant, changes phase scope, or trades
    off something only the repo owner should decide - do NOT implement. Set applied:false and
    write up the options. Stopping with good analysis beats guessing.

Fill spec_amendment with the exact prose to record in the ticket or SPEC.`
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function blockedBy(gate, reviews) {
  if (!gate || !gate.green) return true
  const live = reviews.filter(Boolean)
  if (!live.length) return false
  // The criteria reviewer (index 0) is authoritative on "does this meet the ticket".
  if (live.length === 3 && reviews[0] && reviews[0].blocking) return true
  // Otherwise require a majority, so one over-eager reviewer cannot stall the run.
  return live.filter((r) => r.blocking).length >= 2
}

async function withRetry(fn, label, attempts = 3) {
  for (let i = 1; i <= attempts; i += 1) {
    const r = await fn()
    if (r) return r
    if (i < attempts) log(`${label}: attempt ${i} returned nothing (likely transient) - retrying`)
  }
  log(`${label}: nothing after ${attempts} attempts - treating as a real failure`)
  return null
}

async function runGate(t) {
  return await withRetry(
    () => agent(gatePrompt(t), { label: `gate:${t.id}`, phase: t.phase, schema: GATE_SCHEMA, effort: 'low' }),
    `gate:${t.id}`
  )
}

async function runReviews(t, implSummary) {
  return await parallel([
    () => agent(reviewPrompt(t, 'criteria', implSummary), { label: `review:criteria:${t.id}`, phase: t.phase, schema: REVIEW_SCHEMA }),
    () => agent(reviewPrompt(t, 'invariants', implSummary), { label: `review:invariants:${t.id}`, phase: t.phase, schema: REVIEW_SCHEMA }),
    () => agent(reviewPrompt(t, 'tests', implSummary), { label: `review:tests:${t.id}`, phase: t.phase, schema: REVIEW_SCHEMA }),
  ])
}

// ---------------------------------------------------------------------------
// Main loop
// ---------------------------------------------------------------------------

const completed = []
const priorSummaries = []
const openItems = []
const liveSteps = []
let stoppedAt = null
let stopReason = ''

for (const t of TICKETS) {
  phase(t.phase)
  log(`Ticket ${t.id} - ${t.title}: implementing`)

  const impl = await withRetry(
    () => agent(implPrompt(t, priorSummaries), { label: `impl:${t.id}`, phase: t.phase, schema: IMPL_SCHEMA }),
    `impl:${t.id}`
  )

  if (!impl) {
    stoppedAt = t.id
    stopReason = 'Implementation agent returned nothing after retries.'
    break
  }

  ;(impl.open_items || []).forEach((o) => openItems.push(`${t.id}: ${o}`))
  ;(impl.live_steps || []).forEach((s) => liveSteps.push(`${t.id}: ${s}`))

  let gate = await runGate(t)
  let reviews = gate && gate.green ? await runReviews(t, impl.summary) : []
  let attempt = 0

  while (blockedBy(gate, reviews) && attempt < MAX_REPAIRS) {
    attempt += 1
    log(`Ticket ${t.id}: repair pass ${attempt} of ${MAX_REPAIRS}`)
    await agent(repairPrompt(t, attempt, gate, reviews), { label: `repair${attempt}:${t.id}`, phase: t.phase })
    gate = await runGate(t)
    reviews = gate && gate.green ? await runReviews(t, impl.summary) : []
  }

  let escalation = null
  if (blockedBy(gate, reviews)) {
    log(`Ticket ${t.id}: repairs exhausted, escalating`)
    escalation = await agent(explorePrompt(t, gate, reviews), { label: `explore:${t.id}`, phase: t.phase, schema: EXPLORE_SCHEMA, effort: 'high' })
    if (escalation && escalation.applied) {
      gate = await runGate(t)
      reviews = gate && gate.green ? await runReviews(t, impl.summary) : []
    }
  }

  if (blockedBy(gate, reviews)) {
    stoppedAt = t.id
    stopReason = escalation ? `Escalation did not resolve it: ${escalation.diagnosis}` : 'Gate still failing after repairs.'

    await agent(
      `Ticket ${t.id} (${t.title}) could not be completed. Write a handover to STOPPED.md at the
repo root so the repo owner can pick it up cold.

Include: where it stopped and the last green commit (\`git log --oneline\`); the gate state
${JSON.stringify(gate).slice(0, 2000)}; what was tried across ${attempt} repair pass(es);
${escalation ? 'the architectural analysis produced' : 'that no escalation analysis was produced'};
the concrete decision the owner must make, as a question with options; and
\`git status --short\` so they know what is uncommitted.

Be honest and specific. Do not soften the failure. Do not run git commit/push/checkout/stash.`,
      { label: `handover:${t.id}`, phase: t.phase }
    )
    break
  }

  const caveats = reviews
    .filter(Boolean)
    .flatMap((r) => (r.findings || []).filter((f) => f.severity === 'should-fix'))
    .map((f) => f.what)

  await agent(
    `Commit the completed work for ticket ${t.id} (${t.title}).

  1. \`git status --short\` and \`git diff --stat\`.
  2. Verify nothing ignored is staged: .venv/, .cache/, .env, __pycache__, *.pyc,
     .scratch/tmp/ must NOT be added.
  3. \`git add -A\` the legitimate source, test, fixture, and doc changes.
  4. Commit with this body (subject under 72 chars):

p7-${t.id}: ${t.title.toLowerCase()}

${impl.summary}
${caveats.length ? `\nReviewer notes carried forward:\n${caveats.map((c) => `- ${c}`).join('\n')}` : ''}
${(impl.open_items || []).length ? `\nOpen items:\n${(impl.open_items || []).map((o) => `- ${o}`).join('\n')}` : ''}
${(impl.live_steps || []).length ? `\nNeeds network (deferred to the owner):\n${(impl.live_steps || []).map((s) => `- ${s}`).join('\n')}` : ''}

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>

  5. Confirm with \`git log --oneline -1\`.

Do NOT push. Do NOT checkout, stash, or create a worktree. Commit only.`,
    { label: `commit:${t.id}`, phase: t.phase, effort: 'low' }
  )

  completed.push(t.id)
  priorSummaries.push(`Ticket ${t.id} (${t.title}): ${impl.summary.slice(0, 400)}`)
  log(`Ticket ${t.id} committed. ${completed.length} of ${TICKETS.length} done.`)
}

// ---------------------------------------------------------------------------
// Wrap-up
// ---------------------------------------------------------------------------

phase('Wrap-up')

await agent(
  `Close out Phase 7 and push.

THIS RUN:
  - Completed: ${completed.length ? completed.join(', ') : 'none'} of ${TICKETS.length}
  - Stopped at: ${stoppedAt || 'nothing - the phase completed'}
  ${stoppedAt ? `- Reason: ${stopReason}` : ''}
  - Open items reported:
${openItems.length ? openItems.map((o) => `      * ${o}`).join('\n') : '      (none)'}
  - Steps needing NETWORK, deferred to the owner:
${liveSteps.length ? liveSteps.map((s) => `      * ${s}`).join('\n') : '      (none)'}

DO THIS:
  1. \`git log --oneline -15\` to see the phase's commits.
  2. Run \`${PYTEST}\` and \`${RUFF}\` once more; record the true result.
  3. Write/extend Reports/PHASE_7_RUN_REPORT.md: what landed per ticket, final test count vs
     the ${BASELINE_TESTS} baseline, the measured scale-gate result, audit grade distribution,
     family token numbers, and every open item and reviewer note. If anything stopped early,
     say so prominently at the top and point at STOPPED.md.
  4. Make sure Reports/PHASE_7_LIVE_RUN.md exists and consolidates EVERY deferred network
     step above into an ordered runbook the owner can execute cold, with expected output for
     each command. This document is a deliverable, not an appendix - the owner runs it
     tomorrow.
  5. Mark Reports/PHASE_7_PLAN.md superseded by Reports/PHASE_7_REPORT.md if the phase closed.
  6. Commit ("docs: phase 7 run report") and push: \`git push -u origin HEAD\`.
     Do NOT open a pull request. Do NOT push to main.

Be accurate and unvarnished. If the final test run is not green, say so at the very top.
The repo owner reads this cold and needs the truth, not reassurance.`,
  { label: 'wrap-up', phase: 'Wrap-up' }
)

return { completed, total: TICKETS.length, stoppedAt, stopReason, openItems, liveSteps }
