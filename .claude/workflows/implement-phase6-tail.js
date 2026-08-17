export const meta = {
  name: 'implement-phase6-tail',
  description: 'Finish Phase 6 tickets 08-10 (plot axes, compare, MCP surface + gate) with bounded structured output',
  whenToUse: 'Tickets 01-07 are already committed and pushed. This finishes the phase without depending on workflow resume cache.',
  phases: [
    { title: '08 Plot axis catalog' },
    { title: '09 Cross-part compare' },
    { title: '10 MCP surface + gate' },
    { title: 'Wrap-up' },
  ],
}

// ---------------------------------------------------------------------------
// Why this script exists
// ---------------------------------------------------------------------------
// The full phase-6 run stopped twice in the tail, both times for harness
// reasons rather than engineering ones:
//   1. A 529 Overloaded killed ticket 08's implementer AFTER it had finished
//      its edits. agent() returns null there, so the loop treated finished work
//      as a dead ticket. Fixed by withRetry below.
//   2. Ticket 08's re-run then blew the StructuredOutput retry cap: the return
//      object had no size bounds, phase-6 agents write very long open_items,
//      and the oversized tool call truncated into invalid JSON five times.
//      Fixed by bounding EVERY field below and telling agents the return value
//      is a short handle, not a report.
// Tickets 01-07 are committed and pushed, so this runs fresh with no cache
// dependency - safer than resuming and risking invalidation of that work.

const PY = '.venv/Scripts/python.exe'
const PYTEST = `${PY} -m pytest tests/`
const RUFF = `${PY} -m ruff check src tests`
const TRACKER = '.scratch/design-time-content'
const MAX_REPAIRS = 2

const BASELINE_TESTS = (args && args.baselineTests) || 1506

const TICKETS = [
  {
    id: '08', phase: '08 Plot axis catalog', file: '08-plot-axis-catalog.md', title: 'Plot axis catalog',
    notes: [
      'THIS TICKET IS ALREADY SUBSTANTIALLY DONE and its work is sitting UNCOMMITTED in the',
      'working tree. Two previous agents worked on it; the second finished, verified both gates',
      'green, and then died trying to submit an oversized result. Nothing is wrong with the code.',
      '',
      'Verified state right now: 1506 passed, 1 skipped, ruff clean.',
      '',
      'START BY READING WHAT IS THERE:',
      '  git status --short',
      '  git diff',
      'New files: src/datasheet_analyzer/structure/plot_axes.py, tests/unit/test_plot_axes.py,',
      'scripts/measure_axis_coverage.py.',
      '',
      'Reported by the previous agent, and worth confirming rather than trusting:',
      '  - AFE7950 axis coverage 458/514 = 89% high-confidence (ticket floor is 60%)',
      '  - figures 4-1 (p.29) and 4-492 (p.129, the log-scale case) checked against printed pages',
      '  - a fresh walk found 0 of 491 published axis strings missing from their cited page',
      '  - it found and fixed one real hole in the reader around how `scale` is derived',
      '',
      'YOUR JOB: audit that work against the ticket checkbox by checkbox, spot-check at least',
      'two of its numeric claims yourself, finish anything incomplete, and own the result.',
      'Do NOT restart from scratch and do NOT assume it is correct because the suite is green.',
      'Re-run the suite and ruff before reporting.',
    ].join('\n'),
  },
  { id: '09', phase: '09 Cross-part compare', file: '09-compare.md', title: 'Cross-part compare' },
  { id: '10', phase: '10 MCP surface + gate', file: '10-mcp-surface-and-gate.md', title: 'MCP surface + phase gate',
    notes: [
      'Two device-table MCP tools were deliberately deferred to this ticket by their own tickets:',
      '  - find_pin      (deferred by ticket 04)',
      '  - find_register (deferred by ticket 05)',
      'The retrieval seams they need already exist (Retriever.pins, PinHit.as_dict, pin_gap).',
      'Both belong in this ticket. Do not defer them further.',
      '',
      'This ticket also closes the phase: goldens extended, docs updated, and',
      'Reports/PHASE_6_REPORT.md carrying the measured numbers. That report already exists and',
      'has been written incrementally by earlier tickets - extend it, do not overwrite it.',
      '',
      'If the register work left anything parked (ticket 06 was permitted to fail closed on bit',
      'fields), the report must say so plainly at the top rather than burying it.',
    ].join('\n'),
  },
]

// ---------------------------------------------------------------------------
// Schemas - EVERY field bounded. This is the fix for the retry-cap failure.
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
    detail: { type: 'string', maxLength: 3000, description: 'Verbatim tail of failing output (truncate to 3000 chars), or "clean"' },
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
  files_changed / tests_added  <= 40 entries each
Put full detail - measurements, tables, rationale, caveats - in
Reports/PHASE_6_REPORT.md and in code comments, where it belongs and persists.
An earlier agent on this phase lost a completed ticket by trying to return a
multi-thousand-character result. Be disciplined here.
`.trim()

const CONTEXT = `
You are working in a git worktree of the datasheet_analyzer repo. Read these FIRST:

  1. AGENTS.md                          - architecture contract, INVARIANTS, definition of done
  2. CONTEXT.md                         - domain vocabulary
  3. Reports/PHASE_6_PLAN.md            - execution contract for this phase
  4. ${TRACKER}/SPEC.md                 - problem, solution, user stories, decisions
  5. docs/adr/0005-deterministic-derived-artifacts.md - the binding contract for THIS phase

ENVIRONMENT (Windows, Git Bash available):
  - Use the venv python EXPLICITLY: ${PY}
  - Tests:  ${PYTEST}      (note: addopts already has -q; do NOT add another -q or
                            pytest prints no summary line at all)
  - Lint:   ${RUFF}
  - Baseline entering this run: ${BASELINE_TESTS} tests passing, ruff clean.
    Your work must NEVER reduce that count or break those tests.

NON-NEGOTIABLE RULES:
  - AGENTS.md invariants are binding, INCLUDING invariant 8 (deterministic derived
    artifacts): no model call in any derivation path; every derived field carries source
    (record id + page) and derivation (the named rule).
  - A field that cannot be filled stays null and says so. Never interpolate or default.
  - Verbatim strings are authoritative and NEVER mutated.
  - Any consumer that sorts, compares, or computes margins MUST report its unparsed
    population explicitly. Silently dropping unparseable rows from a decision is a defect.
  - Tests are HERMETIC: no network, no real LLM, no subprocess, no machine-state dependence.
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

    invariants: `INVARIANT LENS - special attention to invariant 8.
Read AGENTS.md's invariants and docs/adr/0005-deterministic-derived-artifacts.md, then audit
the diff for:
  - ANY model call in a derivation path (the cardinal sin of this phase)
  - a derived value without a resolvable source (record id + page) or derivation name
  - an unfillable field interpolated, defaulted, or omitted instead of left null
  - a verbatim string mutated by the numeric layer
  - a consumer that sorts/compares/computes margins WITHOUT reporting unparsed population
  - a test that reaches the network, spawns a subprocess, calls a real LLM, or depends on
    machine state, wall-clock time, or filesystem ordering
  - a non-additive schema change that breaks loading an existing corpus
  - a device table emitted PARTIALLY instead of rejected with a recorded reason
Mark blocking:true for any real breach. Cite file:line.`,

    tests: `TEST-QUALITY AND REGRESSION LENS.
Audit tests added, and what happened to tests that already existed. Look for:
  - tautological or vacuous assertions
  - a test that would still pass if the feature were deleted or stubbed
  - any EXISTING test deleted, skipped, xfailed, or with a loosened assertion
  - any golden file whose expected answer or page was altered
  - for this phase: does a test actually walk every card's source field and resolve it to a
    real record and printed page? A weak version of that invariant-8 test is blocking.
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
  (c) criteria unachievable or self-contradictory as written
  (d) a reviewer is wrong and the work is correct

STEP 2 - propose 2-4 genuinely different approaches satisfying the ticket's INTENT (read the
SPEC's user stories; criteria are a means, not the end). For each: approach, tradeoffs,
whether it breaches an invariant. Proposing that the ticket be re-scoped is a valid outcome.

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
  if (live.length === 3 && reviews[0] && reviews[0].blocking) return true
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
let stoppedAt = null
let stopReason = ''
const openItems = []

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

p6-${t.id}: ${t.title.toLowerCase()}

${impl.summary}
${caveats.length ? `\nReviewer notes carried forward:\n${caveats.map((c) => `- ${c}`).join('\n')}` : ''}
${(impl.open_items || []).length ? `\nOpen items:\n${(impl.open_items || []).map((o) => `- ${o}`).join('\n')}` : ''}

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
  `Close out Phase 6 and push.

THIS RUN (tickets 08-10; 01-07 were committed and pushed earlier):
  - Completed here: ${completed.length ? completed.join(', ') : 'none'}
  - Stopped at: ${stoppedAt || 'nothing - the tail completed'}
  ${stoppedAt ? `- Reason: ${stopReason}` : ''}
  - Open items reported:
${openItems.length ? openItems.map((o) => `      * ${o}`).join('\n') : '      (none)'}

DO THIS:
  1. \`git log --oneline -15\` to see the phase's commits.
  2. Run \`${PYTEST}\` and \`${RUFF}\` once more; record the true result.
  3. Update Reports/PHASE_6_RUN_REPORT.md (it exists - extend it, note this was a second
     run finishing tickets 08-10 after two harness failures in the tail) covering: what
     landed per ticket, final test count vs the ${BASELINE_TESTS} baseline, pin counts and
     cross-check results, numeric parse rate, card coverage, axis coverage, and the register
     outcome (shipped or parked, with reason). Include every open item and reviewer note.
     If anything stopped early, say so prominently at the top and point at STOPPED.md.
  4. Mark Reports/PHASE_6_PLAN.md superseded by Reports/PHASE_6_REPORT.md if the phase closed.
  5. Commit ("docs: phase 6 tail run report") and push: \`git push -u origin HEAD\`.
     Do NOT open a pull request. Do NOT push to main.

Be accurate and unvarnished. If the final test run is not green, say so at the very top.
The repo owner reads this cold and needs the truth, not reassurance.`,
  { label: 'wrap-up', phase: 'Wrap-up' }
)

return { completed, total: TICKETS.length, stoppedAt, stopReason, openItems }
