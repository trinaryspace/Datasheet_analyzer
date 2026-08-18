export const meta = {
  name: 'implement-phase8',
  description: 'Implement Phase 8 (Design-Loop Integration) tickets 01-08 from .scratch/design-loop',
  whenToUse: 'Phases 5-7 are landed. This joins the corpus to an actual design: netlist ingest, pin join, deterministic design checks, layout cards, expert packs, retrieval eval, live-use performance.',
  phases: [
    { title: '01 Design ingest' },
    { title: '02 Pin-level join' },
    { title: '03 Design rules + check' },
    { title: '04 Layout card' },
    { title: '05 Expert packs' },
    { title: '06 Retrieval eval' },
    { title: '07 Live-use performance' },
    { title: '08 Phase gate + report' },
    { title: 'Wrap-up' },
  ],
}

// ---------------------------------------------------------------------------
// Harness lineage
// ---------------------------------------------------------------------------
// Same spine as implement-phase7.js: sequential ticket loop, parallel read-only
// reviewers, bounded schemas, withRetry around every agent call.
//
// What is different for phase 8: this phase's output is consumed as ENGINEERING
// ADVICE about a real board. The failure mode is not a crash and not (as in
// phase 7) a fabricated URL - it is a check that quietly reads as "clean"
// because it silently failed to evaluate anything. That hazard is stated in the
// shared context and is a standing blocking finding for the invariant reviewer.

const PY = '.venv/Scripts/python.exe'
const PYTEST = `${PY} -m pytest tests/`
const RUFF = `${PY} -m ruff check src tests`
const TRACKER = '.scratch/design-loop'
const MAX_REPAIRS = 2

const BASELINE_TESTS = (args && args.baselineTests) || 1663

const ADVISORY = `
THE ADVISORY BOUNDARY - THE MOST IMPORTANT RULE IN THIS PHASE.

What you build here is read as engineering advice about a real circuit board.
Two failure modes matter more than anything else:

  1. SILENT NON-EVALUATION. A rule that could not assess a site - no pin table,
     an unparsed value, no declared rail - and therefore reports nothing, reads
     to a human as "checked, and fine". That is the single most dangerous
     output this repo can produce. EVERY rule, report, and joined view MUST
     state its unevaluated population and why. A rule that evaluated 3 of 400
     sites and found nothing must render as "evaluated 3 of 400", never as a
     clean pass. If you find yourself unable to count the population you
     skipped, the design is wrong - fix the design, do not ship the count-less
     version.

  2. SIGNING OFF. Nothing in this phase certifies, approves, validates, or
     passes a design. Findings are advisory, cite the printed page, and hand
     the judgement to the designer. Do not write output that says a design is
     correct, safe, or compliant. Do not name anything 'validate' or 'verify'
     in a way that implies it. \`dsa check\` FLAGS; it does not bless.

Also binding here:
  - A wrong refdes -> part bind answers confidently about the wrong silicon.
    Binds come from the netlist's own fields or an explicit override. NEVER
    fuzzy-match a value string to a part number.
  - Inferring a rail voltage from a net NAME is a convenience, not a fact.
    Off by default, and labelled as inferred wherever it appears.
  - Invariant 8 extends to every check path: no model call, and every finding
    resolves to a record id and a printed page.
`.trim()

const TICKETS = [
  {
    id: '01',
    phase: '01 Design ingest',
    file: '01-design-ingest.md',
    title: 'Design ingest (dsa design import)',
    notes: [
      'You have no real KiCad export, so write a SYNTHETIC netlist fixture to the documented',
      'format. That is legitimate and expected. What is NOT legitimate is guessing at format',
      'details and presenting the parser as validated: parse only the `(components ...)` and',
      '`(nets ...)` blocks, record anything you do not understand, and add "validate the parser',
      'against a real KiCad export" to Reports/PHASE_8_LIVE_RUN.md and to live_steps.',
      '',
      'Support a fixture that deliberately contains an unsupported construct, and assert it is',
      'RECORDED rather than dropped. A parser that silently ignores what it does not know is',
      'how a design ends up half-understood without anyone noticing.',
      '',
      'The BOM CSV path is the trivially-correct one - make it produce exactly the same',
      'design.json shape so downstream tickets never branch on input format.',
      '',
      'unbound is not an error path. A real board is mostly passives. Design the output so a',
      'reader immediately sees how much of the board has a corpus behind it.',
    ].join('\n'),
  },
  {
    id: '02',
    phase: '02 Pin-level join',
    file: '02-pin-join.md',
    title: 'Pin-level join + coverage reporting',
    notes: [
      'Reuse the Phase 6 pin records and the checked-in registry/pin_types.yaml lexicon. Do',
      'NOT introduce a second pin-type vocabulary - a divergent second vocabulary would let',
      'two parts of the system disagree about what "power" means.',
      '',
      'Coverage reporting is the point of this ticket, not a nicety. A part with no pin table',
      'must produce a clear non-fatal coverage entry. Test it with a part that genuinely has',
      'no pin table in this repo rather than a mock - find one first.',
      '',
      'AFE7950/AFE7953 may still be at an old schema depending on how Phase 7 ticket 07 went.',
      'Check Reports/PHASE_7_REPORT.md before designing around them.',
    ].join('\n'),
  },
  {
    id: '03',
    phase: '03 Design rules + check',
    file: '03-design-rules-and-check.md',
    title: 'Design rules + dsa check',
    notes: [
      'THE HEADLINE TICKET. Re-read the advisory boundary before you start.',
      '',
      'Rules are DATA. If a reviewer cannot change behaviour by editing',
      'registry/design_rules.yaml alone, the ticket is not met. Follow the idiom already',
      'established by registry/cards.yaml, device_tables.yaml and audit_rubric.yaml rather',
      'than inventing a fourth shape for checked-in rule data.',
      '',
      'EVERY rule needs a PAIR of fixtures: one built to trip it, one built not to. A rule with',
      'only a positive test is not tested - it might fire on everything.',
      '',
      'The unevaluated-population test is the one that must not be skipped: construct a case',
      'where a rule can barely evaluate anything, and assert the OUTPUT does not read as clean.',
      'Assert on the rendered DESIGN_REVIEW.md text, not just on a JSON field, because the',
      'rendered text is what a human actually reads.',
      '',
      'missing-decoupling depends on ticket 04. If 04 has not landed when you reach it, ship',
      'the rule with its requirement source marked unavailable and its whole population',
      'unevaluated - which is exactly the honest behaviour the rest of the ticket demands.',
    ].join('\n'),
  },
  {
    id: '04',
    phase: '04 Layout card',
    file: '04-layout-card.md',
    title: 'Layout & assembly card',
    notes: [
      'This is a SURFACING ticket. Every field is verbatim from a printed page or it is null',
      'with a stated reason. Do not compute a thermal via count, do not infer an MSL, do not',
      'normalise a package name into something the datasheet never printed.',
      '',
      'Spot-check every populated field on at least two real corpora against the printed page,',
      'and put the page numbers you checked in the report. A card that is 90% right is worse',
      'than one that is 60% populated and honest about the rest.',
    ].join('\n'),
  },
  {
    id: '05',
    phase: '05 Expert packs',
    file: '05-expert-packs.md',
    title: 'Expert packs (dsa pack / unpack)',
    notes: [
      'The acceptance test that matters: pack a part, unpack into a CLEAN temporary directory,',
      'and answer a real question there with NO access to the source corpus. If the answer',
      'needs a file the pack did not carry, the pack format is incomplete - fix the format,',
      'do not relax the test.',
      '',
      'Verify every hash BEFORE writing anything. A partial import of a corrupted pack leaves a',
      'designer with a corpus they think is whole. Assert the refusal is total and names the',
      'failing file.',
      '',
      'Include the Phase 5 agent protocol document in the pack. A cold agent that finds a pack',
      'and does not know the retrieval protocol has an expert corpus it cannot drive.',
    ].join('\n'),
  },
  {
    id: '06',
    phase: '06 Retrieval eval',
    file: '06-retrieval-eval.md',
    title: 'Retrieval eval + unanswered log',
    notes: [
      'The seeded-regression test is the acceptance criterion that gives the budget meaning: a',
      'budget nothing can trip is decoration. Seed a real degradation (perturb the ranking in a',
      'test-local way) and assert the budget test fails.',
      '',
      'Ground truth is the EXISTING goldens. Do not build a new relevance corpus and do not',
      'edit a golden to make a metric look better - that is the one unacceptable move here.',
      '',
      'The unanswered log touches user questions. Keep it opt-in or clearly announced, record',
      'nothing beyond the question and the retrieval outcome, and keep it out of any path that',
      'runs during tests by default.',
    ].join('\n'),
  },
  {
    id: '07',
    phase: '07 Live-use performance',
    file: '07-live-use-performance.md',
    title: 'Live-use performance',
    notes: [
      'The correctness half outranks the speed half. BYTE-IDENTICAL is the word in the ticket',
      'and it is meant literally: assert a full rebuild and an incremental rebuild produce',
      'identical bytes, not merely corpora that pass the same tests. Faster-but-different is a',
      'correctness bug wearing a performance costume.',
      '',
      'All three invalidation triggers need their own test: changed source PDF, bumped',
      'PIPELINE_VERSION, changed extractor version. Missing one means a stale corpus survives a',
      'change that should have rebuilt it.',
      '',
      'Reuse the existing cache identity rules. A second caching scheme alongside the first is',
      'how a corpus ends up half-invalidated.',
      '',
      'Budget ceilings live in registry/perf_budget.yaml and must be generous. A tight number',
      'that flakes on a loaded machine teaches everyone to ignore the gate, which is worse than',
      'having no gate.',
    ].join('\n'),
  },
  {
    id: '08',
    phase: '08 Phase gate + report',
    file: '08-phase-gate-and-report.md',
    title: 'Phase gate + PHASE_8_REPORT',
    notes: [
      'The walkthrough runs IN THE SUITE against a checked-in synthetic design, end to end.',
      '',
      'Three demonstrations are required and each is separate: a real finding on a real corpus',
      'hand-verified against the printed page; a deliberately injected fault that IS caught;',
      'and a deliberately clean design that produces NO findings. The third is what proves the',
      'rules are not simply firing on everything.',
      '',
      'PIPELINE_VERSION: confirm the entering value in src/datasheet_analyzer/config.py before',
      'changing it. Earlier phases moved it ahead of plan (phase 6 went to 0.5.0, not 0.4.0),',
      'so trust the file, not the plan document.',
      '',
      'Reports/PHASE_8_REPORT.md carries measured numbers, not adjectives. If a number is bad,',
      'print the bad number. The repo owner is about to run a full-scale test against this and',
      'needs to know where it is weak BEFORE they find out the hard way.',
      '',
      'Reports/PHASE_8_LIVE_RUN.md consolidates every step needing network or a real EDA',
      'export into an ordered runbook the owner executes cold.',
    ].join('\n'),
  },
]

// ---------------------------------------------------------------------------
// Schemas - EVERY field bounded.
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
      description: 'Steps needing network or a real EDA export, deferred to the owner. One line each.',
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
Reports/PHASE_8_REPORT.md and in code comments, where it belongs and persists.
An agent on an earlier phase lost a completed ticket by trying to return a
multi-thousand-character result. Be disciplined here.
`.trim()

const CONTEXT = `
You are working in a git worktree of the datasheet_analyzer repo. Read these FIRST:

  1. AGENTS.md                          - architecture contract, INVARIANTS, definition of done
  2. CONTEXT.md                         - domain vocabulary
  3. Reports/PHASE_8_PLAN.md            - execution contract for this phase
  4. ${TRACKER}/SPEC.md                 - problem, solution, user stories, decisions
  5. docs/adr/0005-deterministic-derived-artifacts.md - invariant 8, still binding

Also skim Reports/PHASE_7_REPORT.md: it records what actually landed in the phase
directly beneath you, including anything that had to be deferred.

ENVIRONMENT (Windows, Git Bash available):
  - Use the venv python EXPLICITLY: ${PY}
  - Tests:  ${PYTEST}      (note: addopts already has -q; do NOT add another -q or
                            pytest prints no summary line at all)
  - Lint:   ${RUFF}
  - Baseline entering this run: ${BASELINE_TESTS} tests passing, ruff clean.
    Your work must NEVER reduce that count or break those tests.
  - You have NO NETWORK. This phase is designed to be almost entirely offline-testable.
    Never invent a URL, a hash, or an upstream fact. If a step genuinely needs network or
    a real EDA export, implement the machinery, test it against a synthetic fixture, and
    record the live step in Reports/PHASE_8_LIVE_RUN.md and in live_steps.

${ADVISORY}

NON-NEGOTIABLE RULES:
  - AGENTS.md invariants are binding, including invariant 8 (deterministic derived
    artifacts): no model call in any derivation path; every derived field carries source
    (record id + page) and derivation (the named rule).
  - A field that cannot be filled stays null and says so. Never interpolate or default.
  - Verbatim strings are authoritative and NEVER mutated.
  - Any consumer that sorts, compares, computes margins, or EVALUATES A RULE must report
    its unparsed / unevaluated population explicitly.
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
  6. Append any deferred live step to Reports/PHASE_8_LIVE_RUN.md (create it if absent)
     AND list it in live_steps.

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
Mark blocking:true if any box is unmet or only cosmetically met.`,

    invariants: `INVARIANT LENS - special attention to the ADVISORY BOUNDARY.
Read AGENTS.md's invariants and docs/adr/0005-deterministic-derived-artifacts.md, then audit
the diff for:
  - A CHECK, REPORT, OR JOINED VIEW THAT CAN READ AS CLEAN WITHOUT STATING WHAT IT COULD NOT
    EVALUATE. This is the cardinal sin of phase 8 and it is ALWAYS blocking. For each rule
    and each report, find the code that counts and renders the unevaluated population. If a
    rule silently skips sites, that is a finding even if every test passes.
  - Output that certifies, approves, validates, or otherwise blesses a design rather than
    flagging for human review. Check the rendered text, not just the code.
  - A refdes -> part bind made by fuzzy matching a value string.
  - A rail voltage inferred from a net name by default, or inferred without being labelled.
  - ANY model call in a derivation or check path (invariant 8).
  - a derived value or finding without a resolvable source (record id + page)
  - an unfillable field interpolated, defaulted, or omitted instead of left null
  - a verbatim string mutated
  - a second pin-type vocabulary, a second caching scheme, or a fourth shape for checked-in
    rule data instead of reusing the existing idioms
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
  - phase-8 specific: does EVERY shipped rule have BOTH a trips-it and a does-not-trip-it
    fixture? Is there a test that would fail if the unevaluated population stopped being
    rendered? if an incremental rebuild stopped being byte-identical? if a corrupted pack
    were partially imported? if the retrieval budget stopped being trippable?
    A missing test for any of those, in the ticket that owns it, is blocking.
  - a performance assertion against a constant embedded in test code rather than the budget
    file, or a ceiling tight enough to flake
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
  - Never resolve a coverage problem by hiding it. If a rule cannot evaluate something, the
    fix is to report that, not to stop counting it.
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
  (c) criteria unachievable with the corpora that actually exist, or self-contradictory
  (d) a reviewer is wrong and the work is correct

STEP 2 - propose 2-4 genuinely different approaches satisfying the ticket's INTENT (read the
SPEC's user stories; criteria are a means, not the end). For each: approach, tradeoffs,
whether it breaches an invariant or the advisory boundary. Proposing a re-scope is valid.

STEP 3 - ACT.
  - If one alternative is clearly right AND breaches nothing, IMPLEMENT it, run
    ${PYTEST} and ${RUFF} until green, set applied:true.
  - If the call needs human judgment - breaches an invariant, weakens the advisory boundary,
    changes phase scope, or trades off something only the repo owner should decide - do NOT
    implement. Set applied:false and write up the options. Stopping with good analysis beats
    guessing, and this phase's output is read as engineering advice.

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

p8-${t.id}: ${t.title.toLowerCase()}

${impl.summary}
${caveats.length ? `\nReviewer notes carried forward:\n${caveats.map((c) => `- ${c}`).join('\n')}` : ''}
${(impl.open_items || []).length ? `\nOpen items:\n${(impl.open_items || []).map((o) => `- ${o}`).join('\n')}` : ''}
${(impl.live_steps || []).length ? `\nNeeds a live step (deferred to the owner):\n${(impl.live_steps || []).map((s) => `- ${s}`).join('\n')}` : ''}

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
  `Close out Phase 8 and push.

THIS RUN:
  - Completed: ${completed.length ? completed.join(', ') : 'none'} of ${TICKETS.length}
  - Stopped at: ${stoppedAt || 'nothing - the phase completed'}
  ${stoppedAt ? `- Reason: ${stopReason}` : ''}
  - Open items reported:
${openItems.length ? openItems.map((o) => `      * ${o}`).join('\n') : '      (none)'}
  - Steps deferred to the owner (network or a real EDA export):
${liveSteps.length ? liveSteps.map((s) => `      * ${s}`).join('\n') : '      (none)'}

DO THIS:
  1. \`git log --oneline -15\` to see the phase's commits.
  2. Run \`${PYTEST}\` and \`${RUFF}\` once more; record the true result.
  3. Write/extend Reports/PHASE_8_RUN_REPORT.md: what landed per ticket, final test count vs
     the ${BASELINE_TESTS} baseline, design coverage percentages, findings produced, pack
     sizes, retrieval metrics, latency p50/p95, and every open item and reviewer note. If
     anything stopped early, say so prominently at the top and point at STOPPED.md.
  4. Make sure Reports/PHASE_8_LIVE_RUN.md exists and consolidates every deferred step into
     an ordered runbook the owner can execute cold, with expected output per command.
  5. Mark Reports/PHASE_8_PLAN.md superseded by Reports/PHASE_8_REPORT.md if the phase closed.
  6. Commit ("docs: phase 8 run report") and push: \`git push -u origin HEAD\`.
     Do NOT open a pull request. Do NOT push to main.

Be accurate and unvarnished. If the final test run is not green, say so at the very top. The
repo owner is about to run a full-scale test of the whole system against this work and needs
to know where it is weak before they find out the hard way.`,
  { label: 'wrap-up', phase: 'Wrap-up' }
)

return { completed, total: TICKETS.length, stoppedAt, stopReason, openItems, liveSteps }
