export const meta = {
  name: 'implement-phase6',
  description: 'Implement Phase 6 (design-time content) ticket by ticket: implement, objective gate, parallel review, repair, architectural escalation, commit',
  whenToUse: 'Autonomous implementation of .scratch/design-time-content/ tickets 01-10 against Reports/PHASE_6_PLAN.md. Run only after Phase 5 has landed.',
  phases: [
    { title: '01 Derived-artifact contract' },
    { title: '02 Numeric layer' },
    { title: '03 Device-table abstraction' },
    { title: '04 Pins' },
    { title: '05 Register summary' },
    { title: '06 Register bit fields' },
    { title: '07 Design cards' },
    { title: '08 Plot axis catalog' },
    { title: '09 Cross-part compare' },
    { title: '10 MCP surface + gate' },
    { title: 'Wrap-up' },
  ],
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PY = '.venv/Scripts/python.exe'
const PYTEST = `${PY} -m pytest tests/ -q`
const RUFF = `${PY} -m ruff check src tests`
const TRACKER = '.scratch/design-time-content'
const MAX_REPAIRS = 2

// Passed in at launch so the gate can detect test removal against the real
// post-Phase-5 count rather than a number hardcoded before Phase 5 finished.
const BASELINE_TESTS = (args && args.baselineTests) || 787
const REGMAP_PDF = (args && args.regmapPdf) || 'LMX1204_registermap.pdf'
const REGMAP_PART = (args && args.regmapPart) || 'LMX1204'

const TICKETS = [
  {
    id: '01', phase: '01 Derived-artifact contract', file: '01-derived-artifact-contract.md',
    title: 'Derived-artifact contract',
    notes: [
      'The ADR text has ALREADY BEEN DRAFTED AND APPROVED by the repo owner.',
      'It is at docs/adr/0005-deterministic-derived-artifacts.md in this worktree.',
      'Do NOT rewrite its Decision section or re-litigate the options - that decision is made.',
      'Your job for the ADR part is to make sure it is consistent with the code you build,',
      'and to fix the Status line from "proposed" to "accepted".',
      'The pin-count "Open question" at the bottom was resolved as: WARN, record the mismatch',
      'in the manifest, and surface it in dsa audit later. Update the ADR to state that as',
      'the decision and remove the open-question framing.',
      'Everything else in the ticket - invariant 8 in AGENTS.md, the DerivedValue model,',
      'stable record ids, the source-resolving test helper, DSA_CARD_VERSION - is yours to build.',
    ].join('\n'),
  },
  { id: '02', phase: '02 Numeric layer', file: '02-numeric-layer.md', title: 'Numeric layer' },
  { id: '03', phase: '03 Device-table abstraction', file: '03-device-table-abstraction.md', title: 'Device-table abstraction' },
  { id: '04', phase: '04 Pins', file: '04-pins.md', title: 'Pins' },
  {
    id: '05', phase: '05 Register summary', file: '05-register-summary.md', title: 'Register summary tables',
    notes: [
      `The reference documents are REAL and BOTH are present as committed fixtures:`,
      `  - datasheet:     tests/fixtures/pdf/lmx1204.pdf`,
      `  - register map:  tests/fixtures/pdf/${REGMAP_PDF}`,
      'Read the register map before designing the parser. This is the document the ticket is',
      'gated against, and a parser designed without reading it will be fiction.',
      '',
      `BUILD THE GATE PART PROPERLY. ${REGMAP_PART} now has its own datasheet, so build it as a`,
      'real part and attach the register map as a companion - that is the honest fixture:',
      `  dsa build tests/fixtures/pdf/lmx1204.pdf --part ${REGMAP_PART} --vendor unknown`,
      `  dsa add-doc tests/fixtures/pdf/${REGMAP_PDF} --part ${REGMAP_PART} --type register_map`,
      'Do NOT attach the register map to an unrelated part like AFE7950 - that would be a',
      'dishonest fixture and a worthless gate.',
      '',
      'WHY --vendor unknown: LMX1204 is a TI part, so detection would pin `ti` and prefer the',
      '`ti_html` backend, which needs NETWORK. There are no recorded HTTP fixtures for LMX1204,',
      'so a `ti`-routed build cannot run in the hermetic suite. Pinning `unknown` routes it',
      'through the offline pdf_layout floor. This is the exact precedent the Phase 4 gate set',
      'for LM741 (also a TI part, also pinned `--vendor unknown`, recorded as cli-override',
      'evidence) - follow it, and record the same reasoning in the fixture/test comments.',
      'If you find the vendor chain already falls back to pdf_layout offline without the flag,',
      'verify that by test rather than assuming it, and say which behaviour you relied on.',
      '',
      'This ticket ALSO changes routing: DocType.REGISTER_MAP currently prefers pdf_text.',
      'Route it to pdf_layout so tables exist at all, bump PIPELINE_VERSION so cached',
      'register-map extractions invalidate, and rewrite the now-false caveats in README.md',
      'and AGENTS.md in the same change.',
      'Companion documents that are NOT register maps must keep pdf_text behaviour unchanged.',
    ].join('\n'),
  },
  {
    id: '06', phase: '06 Register bit fields', file: '06-register-bitfields.md', title: 'Register bit fields',
    notes: [
      'THIS TICKET IS EXPLICITLY PERMITTED TO FAIL CLOSED, and doing so is a success.',
      'If bit-field extraction cannot pass its 100% accuracy gate against a hand-verified',
      'sample from the reference document, ship NOTHING for bit fields, write a',
      'KNOWN_SHORTCOMINGS.md entry recording what was attempted and exactly what broke, keep',
      'the summary records with fields: [] and a recorded reason, and report that outcome.',
      'Wrong bit positions are worse than absent ones: a driver written against a wrong bit',
      'range silently misconfigures silicon. Approximate output here is a defect, not partial credit.',
    ].join('\n'),
  },
  { id: '07', phase: '07 Design cards', file: '07-design-cards.md', title: 'Design cards' },
  { id: '08', phase: '08 Plot axis catalog', file: '08-plot-axis-catalog.md', title: 'Plot axis catalog' },
  { id: '09', phase: '09 Cross-part compare', file: '09-compare.md', title: 'Cross-part compare' },
  { id: '10', phase: '10 MCP surface + gate', file: '10-mcp-surface-and-gate.md', title: 'MCP surface + phase gate' },
]

// ---------------------------------------------------------------------------
// Schemas (identical contract to the Phase 5 harness)
// ---------------------------------------------------------------------------

const IMPL_SCHEMA = {
  type: 'object',
  required: ['summary', 'files_changed', 'tests_added', 'self_gate_green'],
  properties: {
    summary: { type: 'string', description: 'What was built, in 3-6 sentences' },
    files_changed: { type: 'array', items: { type: 'string' } },
    tests_added: { type: 'array', items: { type: 'string' } },
    self_gate_green: { type: 'boolean', description: 'True only if you personally ran pytest AND ruff and both passed' },
    deviations: { type: 'array', items: { type: 'string' } },
    open_items: { type: 'array', items: { type: 'string' } },
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
    failures: { type: 'array', items: { type: 'string' } },
    detail: { type: 'string' },
  },
}

const REVIEW_SCHEMA = {
  type: 'object',
  required: ['blocking', 'summary', 'findings'],
  properties: {
    blocking: { type: 'boolean' },
    summary: { type: 'string' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['what', 'severity', 'evidence'],
        properties: {
          what: { type: 'string' },
          severity: { type: 'string', enum: ['blocking', 'should-fix', 'note'] },
          evidence: { type: 'string' },
          fix: { type: 'string' },
        },
      },
    },
  },
}

const EXPLORE_SCHEMA = {
  type: 'object',
  required: ['diagnosis', 'alternatives', 'applied'],
  properties: {
    diagnosis: { type: 'string' },
    alternatives: {
      type: 'array',
      items: {
        type: 'object',
        required: ['approach', 'tradeoffs', 'recommended'],
        properties: {
          approach: { type: 'string' },
          tradeoffs: { type: 'string' },
          recommended: { type: 'boolean' },
          violates_invariant: { type: 'string' },
        },
      },
    },
    applied: { type: 'boolean' },
    applied_approach: { type: 'string' },
    spec_amendment: { type: 'string' },
  },
}

// ---------------------------------------------------------------------------
// Shared prompt fragments
// ---------------------------------------------------------------------------

const CONTEXT = `
You are working in a git worktree of the datasheet_analyzer repo. Read these FIRST,
in this order, before writing any code:

  1. AGENTS.md                          - architecture contract, INVARIANTS, conventions, definition of done
  2. CONTEXT.md                         - the project's domain vocabulary
  3. Reports/PHASE_6_PLAN.md            - the execution contract for this whole phase
  4. ${TRACKER}/SPEC.md                 - problem, solution, user stories, decisions
  5. docs/adr/0005-deterministic-derived-artifacts.md - the binding contract for THIS phase

ENVIRONMENT (Windows, Git Bash available):
  - Use the venv python EXPLICITLY: ${PY}
  - Tests:  ${PYTEST}
  - Lint:   ${RUFF}
  - Baseline at the start of this phase: ${BASELINE_TESTS} tests passing, ruff clean.
    Your work must NEVER reduce that count or break those tests.

NON-NEGOTIABLE RULES:
  - The repo invariants in AGENTS.md are binding, INCLUDING invariant 8 (deterministic
    derived artifacts). No model call may appear in any derivation path. Every derived
    field carries source (record id + page) and derivation (the named rule).
  - A field that cannot be filled stays null and says so. Never interpolate, never default
    to a plausible value, never omit in a way that makes an artifact look complete.
  - Verbatim strings are authoritative and are NEVER mutated. The numeric layer is additive.
  - Any consumer that sorts, compares, or computes margins MUST report its unparsed
    population explicitly. Silently dropping unparseable rows from a decision is a defect.
  - Tests are HERMETIC: no network, no real LLM, no subprocess, no machine-state dependence.
  - Schema changes are ADDITIVE ONLY. Existing corpora must still load.
  - Land tests WITH the code, in the same change.
  - NEVER weaken or delete an existing test to make something pass. NEVER change a golden
    file's expected answer or page. If an existing test genuinely must change, that is a
    finding to report, not an edit to make quietly.
  - Do NOT run git commit, git push, git checkout, or git stash. The workflow handles git.
  - Do NOT modify .env, .venv/, or anything under .cache/.
  - If a ticket criterion is genuinely impossible, say so in open_items with the reason.
    Do not fake it and do not silently drop it.
`.trim()

function implPrompt(t, priorSummaries) {
  const prior = priorSummaries.length
    ? `\nWHAT ALREADY LANDED IN THIS PHASE (build on it, do not redo it):\n${priorSummaries.map((s) => `  - ${s}`).join('\n')}\n`
    : ''
  const notes = t.notes ? `\nTICKET-SPECIFIC NOTES YOU MUST HEED:\n${t.notes}\n` : ''
  return `${CONTEXT}

YOUR TASK: implement ticket ${t.id} - ${t.title}.

Read the ticket file in full: ${TRACKER}/issues/${t.file}
Its checkbox list is the acceptance criteria. Every single box must be genuinely satisfied
by code and by a test that would FAIL if the behaviour regressed.
${prior}${notes}
METHOD:
  1. Read the five context files above, then the ticket.
  2. Explore the existing code you are extending. Match its style, naming, comment density,
     and error-handling idiom. Read neighbouring modules before inventing shapes.
  3. Implement, writing tests alongside the code.
  4. Run ${PYTEST} and ${RUFF} yourself. Iterate until BOTH are clean.
  5. Update AGENTS.md / CONTEXT.md / README.md only where THIS ticket's criteria say to.

Set self_gate_green true only if you actually ran both commands and both passed.
Report honestly: a truthful partial result is far more useful than a false green.`
}

function gatePrompt(t) {
  return `Run the objective gate for ticket ${t.id} (${t.title}) in the datasheet_analyzer worktree.

Run EXACTLY these two commands from the repo root and report what happened:
  1. ${PYTEST}
  2. ${RUFF}

Rules:
  - green is true ONLY if pytest exited 0 AND ruff reported no issues.
  - Report the pytest exit code verbatim. Do not infer it from output text.
  - If tests failed, list failing node ids exactly and include the verbatim output tail.
  - Baseline at the start of this phase was ${BASELINE_TESTS} tests. If tests_collected is
    LOWER than that, treat it as a failure and say so - it means tests were removed.

Do NOT fix anything. Do NOT edit any file. You are a measuring instrument, nothing else.`
}

function reviewPrompt(t, lens, implSummary) {
  const lenses = {
    criteria: `ACCEPTANCE-CRITERIA LENS.
Open ${TRACKER}/issues/${t.file} and walk its checkbox list ONE BOX AT A TIME.
For each box, find the specific code and the specific test that satisfies it, cited as
file:line. A box is satisfied only if BOTH exist. If a test merely asserts that code runs
without asserting the behaviour the box describes, the box is NOT satisfied.
Mark blocking:true if any box is unmet or only cosmetically met.`,

    invariants: `INVARIANT LENS - with special attention to invariant 8.
Read AGENTS.md's invariants and docs/adr/0005-deterministic-derived-artifacts.md, then audit
the diff. Look specifically for:
  - ANY model call in a derivation path (this is the phase's cardinal sin)
  - a derived value without a resolvable source (record id + page) or without a derivation name
  - an unfillable field that was interpolated, defaulted, or omitted instead of left null
  - a verbatim string that was mutated by the numeric layer
  - a consumer that sorts/compares/computes margins WITHOUT reporting its unparsed population
  - a test that reaches the network, spawns a subprocess, calls a real LLM, or depends on
    machine state, wall-clock time, or filesystem ordering
  - a non-additive schema change that would break loading an existing corpus
  - a cache key that does not change when derived output shape changes
  - a device table emitted PARTIALLY instead of being rejected with a recorded reason
Mark blocking:true for any real breach. Cite file:line.`,

    tests: `TEST-QUALITY AND REGRESSION LENS.
Audit the tests added by this ticket, and what happened to tests that already existed.
Look specifically for:
  - tautological or vacuous assertions (asserting a mock, asserting True, asserting a value
    the test itself computed the same way the code does)
  - a test that would still pass if the feature were deleted or stubbed
  - any EXISTING test deleted, skipped, xfailed, or with a loosened assertion
  - any golden file whose expected answer or page was altered
  - for this phase specifically: does a test actually walk every card's source field and
    resolve it to a real record and printed page? That is the invariant-8 enforcement test
    and a weak version of it is blocking.
Run \`git diff --stat\` and \`git diff\` against the previous commit to see what changed.
Deleting or weakening an existing test is ALWAYS blocking. Cite file:line.`,
  }

  return `You are reviewing a just-completed implementation of ticket ${t.id} (${t.title})
in the datasheet_analyzer repo. You are a REVIEWER: read and run read-only commands only.
DO NOT EDIT ANY FILE. Do not run git commit/push/checkout/stash.

The implementer reported:
"""
${implSummary}
"""
Treat that claim with professional skepticism - verify it against the actual code.

YOUR LENS:
${lenses[lens]}

Be specific and evidence-based. A finding without a file:line or verbatim quote is not a
finding. Do not invent problems to seem thorough: if the work is sound under your lens, say
so plainly and set blocking:false. A false blocking verdict stalls the run.`
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

Fix these problems properly. Rules:
  - Fix the ROOT CAUSE. Do not silence a failing test, loosen an assertion, add a skip, or
    delete a test to make the gate pass. That is the one unacceptable outcome here.
  - If a reviewer finding is WRONG, do not "fix" it - explain in deviations why it is wrong,
    with evidence. Reviewers can be mistaken and you are allowed to say so.
  - Re-run ${PYTEST} and ${RUFF} until both pass.
  - Do not run git commit/push/checkout/stash.`
}

function explorePrompt(t, gate, reviews) {
  return `${CONTEXT}

ESCALATION for ticket ${t.id} - ${t.title}.
Ticket file: ${TRACKER}/issues/${t.file}

Implementation plus ${MAX_REPAIRS} repair passes have NOT satisfied this ticket as written.
Rather than halting, work out WHY and propose a way through.

STEP 1 - DIAGNOSE. Find the real root cause. Distinguish between:
  (a) the ticket is fine, the implementation approach was wrong
  (b) the ticket's design conflicts with something real in the existing codebase
  (c) the acceptance criteria are unachievable or self-contradictory as written
  (d) a reviewer is wrong and the work is actually correct

STEP 2 - EXPLORE ALTERNATIVES. Propose 2-4 genuinely different architectural approaches
that satisfy the ticket's INTENT (read the SPEC's user stories - the criteria are a means,
not the end). For each: approach, tradeoffs, and whether it breaches any AGENTS.md invariant.
Be willing to propose changing the plan itself - it is a document, not physics. A well-argued
"this ticket should be re-scoped this way" is a valid and valuable outcome.

STEP 3 - ACT.
  - If one alternative is clearly right AND breaches no invariant, IMPLEMENT it, run
    ${PYTEST} and ${RUFF} until green, set applied:true.
  - If the right call needs human judgment - it breaches an invariant, changes phase scope,
    or trades off something only the repo owner should trade off - do NOT implement.
    Set applied:false and write up the options. Stopping with a good analysis beats guessing.

NOTE: for ticket 06 (register bit fields), "ship nothing and record a KNOWN_SHORTCOMINGS
entry" is a CORRECT and expected outcome, not a failure. Do not force it through.

Fill spec_amendment with the exact prose to record in the ticket or SPEC.
Do not run git commit/push/checkout/stash.`
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

async function runGate(t) {
  return await agent(gatePrompt(t), { label: `gate:${t.id}`, phase: t.phase, schema: GATE_SCHEMA, effort: 'low' })
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

  const impl = await agent(implPrompt(t, priorSummaries), { label: `impl:${t.id}`, phase: t.phase, schema: IMPL_SCHEMA })

  if (!impl) {
    stoppedAt = t.id
    stopReason = 'Implementation agent died or was skipped; no result returned.'
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
    log(`Ticket ${t.id}: repairs exhausted, escalating to architectural exploration`)
    escalation = await agent(explorePrompt(t, gate, reviews), { label: `explore:${t.id}`, phase: t.phase, schema: EXPLORE_SCHEMA, effort: 'high' })
    if (escalation && escalation.applied) {
      gate = await runGate(t)
      reviews = gate && gate.green ? await runReviews(t, impl.summary) : []
    }
  }

  if (blockedBy(gate, reviews)) {
    stoppedAt = t.id
    stopReason = escalation
      ? `Escalation did not resolve it. Diagnosis: ${escalation.diagnosis}`
      : 'Gate still failing after repairs, and escalation produced no result.'

    await agent(
      `Ticket ${t.id} (${t.title}) could not be completed. Write a handover report to STOPPED.md
at the repo root so the repo owner can pick this up cold.

Include, in this order:
  1. Exactly where the run stopped and the last green commit (\`git log --oneline\`).
  2. The objective gate state: ${JSON.stringify(gate)}
  3. What was tried across ${attempt} repair pass(es).
  4. ${escalation ? `The architectural analysis: ${JSON.stringify(escalation)}` : 'No escalation analysis was produced.'}
  5. The concrete decision the repo owner must now make, as a question with options.
  6. The working tree state (\`git status --short\`) so they know what is uncommitted.

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
    `Commit the completed work for ticket ${t.id} (${t.title}) in the datasheet_analyzer worktree.

Steps:
  1. \`git status --short\` and \`git diff --stat\` to see what changed.
  2. Verify nothing ignored is staged: .venv/, .cache/, .env, __pycache__, *.pyc must NOT
     be added. If any appear, do not stage them.
  3. \`git add -A\` the legitimate source, test, registry, fixture, and doc changes.
  4. Commit with this message body (subject line under 72 chars):

p6-${t.id}: ${t.title.toLowerCase()}

${impl.summary}
${caveats.length ? `\nReviewer notes carried forward:\n${caveats.map((c) => `- ${c}`).join('\n')}` : ''}
${(impl.open_items || []).length ? `\nOpen items:\n${(impl.open_items || []).map((o) => `- ${o}`).join('\n')}` : ''}

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>

  5. Confirm with \`git log --oneline -1\`.

Do NOT push. Do NOT checkout or stash. Commit only.`,
    { label: `commit:${t.id}`, phase: t.phase, effort: 'low' }
  )

  completed.push(t.id)
  priorSummaries.push(`Ticket ${t.id} (${t.title}): ${impl.summary}`)
  log(`Ticket ${t.id} committed. ${completed.length} of ${TICKETS.length} done.`)
}

// ---------------------------------------------------------------------------
// Wrap-up
// ---------------------------------------------------------------------------

phase('Wrap-up')

await agent(
  `Write the run report for the autonomous Phase 6 implementation, then push.

RESULT:
  - Tickets completed and committed: ${completed.length ? completed.join(', ') : 'none'}
  - Stopped at: ${stoppedAt || 'nothing - the full run completed'}
  ${stoppedAt ? `- Reason: ${stopReason}` : ''}
  - Open items reported by implementers:
${openItems.length ? openItems.map((o) => `      * ${o}`).join('\n') : '      (none)'}

DO THIS:
  1. \`git log --oneline\` to list this run's commits.
  2. Run \`${PYTEST}\` and \`${RUFF}\` once more and record the true result.
  3. Write Reports/PHASE_6_RUN_REPORT.md covering: what landed per ticket, final test count
     vs the ${BASELINE_TESTS} baseline, pin counts and package cross-check results per part,
     numeric parse rate, card coverage, axis coverage, and the register outcome (shipped or
     parked, with the reason). Include every open item and reviewer note carried forward.
     If the run stopped early, say so prominently at the top and point at STOPPED.md.
  4. Commit that report (message: "docs: phase 6 autonomous run report").
  5. Push: \`git push -u origin HEAD\`. Do NOT open a pull request. Do NOT push to main.

Be accurate and unvarnished. If the final test run is not green, say that at the very top.
The repo owner is reading this cold and needs the truth, not reassurance.`,
  { label: 'wrap-up', phase: 'Wrap-up' }
)

return { completed, total: TICKETS.length, stoppedAt, stopReason, openItems }
