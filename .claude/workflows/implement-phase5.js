export const meta = {
  name: 'implement-phase5',
  description: 'Implement Phase 5 (agent-native access) ticket by ticket: implement, objective gate, parallel review, repair, architectural escalation, commit',
  whenToUse: 'Autonomous implementation of .scratch/agent-native-access/ tickets 01-09 against Reports/PHASE_5_PLAN.md',
  phases: [
    { title: '01 Retrieval core seam' },
    { title: '02 Alias lexicon' },
    { title: '03 Full-text search' },
    { title: '04 Per-record confidence' },
    { title: '05 Answer packs' },
    { title: '06 Projects' },
    { title: '07 MCP server' },
    { title: '08 Agent protocol files' },
    { title: '09 Golden extension + gate' },
    { title: 'Wrap-up' },
  ],
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PY = '.venv/Scripts/python.exe'
const PYTEST = `${PY} -m pytest tests/ -q`
const RUFF = `${PY} -m ruff check src tests`
const BASELINE_TESTS = 384
const TRACKER = '.scratch/agent-native-access'
const MAX_REPAIRS = 2

const TICKETS = [
  { id: '01', phase: '01 Retrieval core seam', file: '01-retrieval-core-seam.md', title: 'Retrieval core seam' },
  { id: '02', phase: '02 Alias lexicon', file: '02-alias-lexicon.md', title: 'Alias lexicon' },
  { id: '03', phase: '03 Full-text search', file: '03-fulltext-search.md', title: 'Full-text search' },
  { id: '04', phase: '04 Per-record confidence', file: '04-per-record-confidence.md', title: 'Per-record confidence' },
  { id: '05', phase: '05 Answer packs', file: '05-answer-packs.md', title: 'Answer packs (dsa ask)' },
  { id: '06', phase: '06 Projects', file: '06-projects.md', title: 'Projects' },
  {
    id: '07', phase: '07 MCP server', file: '07-mcp-server.md', title: 'MCP server (local stdio)',
    notes: [
      'The `mcp` Python SDK is ALREADY INSTALLED in .venv at version 2.0.0.',
      'Its API is NOT the old FastMCP API. Do not write against memory. The facts:',
      '  - `from mcp.server import MCPServer` is the server class (also exported as `Server`).',
      '  - MCPServer has decorators `@tool` and `@resource`, plus `add_tool`/`add_resource`.',
      '  - For hermetic tests, call `await server.call_tool(...)` and `await server.list_tools()`',
      '    DIRECTLY in-process. `mcp.shared.memory` also provides an in-memory transport.',
      '  - `run_stdio_async()` is the stdio entry point.',
      'ALWAYS confirm a symbol exists by running python -c "import ...; help(...)" before using it.',
      'Add the `[mcp]` optional extra to pyproject.toml. Do NOT add mcp to the core dependencies.',
      'The criterion "verified by hand once against a real client" CANNOT be done unattended.',
      'Implement and test everything else, and record that single item as an open manual check',
      'in your summary. Do not fake it, and do not delete the criterion from the ticket.',
    ].join('\n'),
  },
  { id: '08', phase: '08 Agent protocol files', file: '08-agent-protocol-files.md', title: 'Agent protocol files' },
  { id: '09', phase: '09 Golden extension + gate', file: '09-golden-extension-and-gate.md', title: 'Golden extension + phase gate' },
]

// ---------------------------------------------------------------------------
// Schemas
// ---------------------------------------------------------------------------

const IMPL_SCHEMA = {
  type: 'object',
  required: ['summary', 'files_changed', 'tests_added', 'self_gate_green'],
  properties: {
    summary: { type: 'string', description: 'What was built, in 3-6 sentences' },
    files_changed: { type: 'array', items: { type: 'string' } },
    tests_added: { type: 'array', items: { type: 'string' }, description: 'Test names or node ids added' },
    self_gate_green: { type: 'boolean', description: 'True only if you personally ran pytest AND ruff and both passed' },
    deviations: { type: 'array', items: { type: 'string' }, description: 'Any place you deviated from the ticket or plan, and why' },
    open_items: { type: 'array', items: { type: 'string' }, description: 'Criteria you could not satisfy, with the reason' },
  },
}

const GATE_SCHEMA = {
  type: 'object',
  required: ['green', 'pytest_exit', 'ruff_clean', 'detail'],
  properties: {
    green: { type: 'boolean', description: 'True only if pytest exited 0 AND ruff reported no issues' },
    pytest_exit: { type: 'integer' },
    ruff_clean: { type: 'boolean' },
    tests_collected: { type: 'integer', description: 'Total tests collected, or -1 if not determinable' },
    failures: { type: 'array', items: { type: 'string' }, description: 'Failing test node ids, verbatim' },
    detail: { type: 'string', description: 'Verbatim tail of the failing output, or "clean"' },
  },
}

const REVIEW_SCHEMA = {
  type: 'object',
  required: ['blocking', 'summary', 'findings'],
  properties: {
    blocking: { type: 'boolean', description: 'True if something here MUST be fixed before this ticket can be called done' },
    summary: { type: 'string' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['what', 'severity', 'evidence'],
        properties: {
          what: { type: 'string' },
          severity: { type: 'string', enum: ['blocking', 'should-fix', 'note'] },
          evidence: { type: 'string', description: 'file:line or a verbatim quote proving the finding is real' },
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
    diagnosis: { type: 'string', description: 'Root cause of why the ticket as specified could not be completed' },
    alternatives: {
      type: 'array',
      items: {
        type: 'object',
        required: ['approach', 'tradeoffs', 'recommended'],
        properties: {
          approach: { type: 'string' },
          tradeoffs: { type: 'string' },
          recommended: { type: 'boolean' },
          violates_invariant: { type: 'string', description: 'Name any AGENTS.md invariant this would breach, or "none"' },
        },
      },
    },
    applied: { type: 'boolean', description: 'True if you implemented one alternative and it now passes the gate' },
    applied_approach: { type: 'string' },
    spec_amendment: { type: 'string', description: 'The exact text to add to the ticket/SPEC recording this decision' },
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
  3. Reports/PHASE_5_PLAN.md            - the execution contract for this whole phase
  4. ${TRACKER}/SPEC.md                 - problem, solution, user stories, decisions

ENVIRONMENT (Windows, Git Bash available):
  - Use the venv python EXPLICITLY: ${PY}
  - Tests:  ${PYTEST}
  - Lint:   ${RUFF}
  - Baseline before this phase started: ${BASELINE_TESTS} tests passing, ruff clean.
    Your work must NEVER reduce that count or break those tests.

NON-NEGOTIABLE RULES:
  - The repo invariants in AGENTS.md are binding. Especially: LLM writes indexes never
    content; tables are atomic; provenance everywhere; TESTS ARE HERMETIC (no network,
    no real LLM, no subprocess, no machine-state dependence); golden Q&A is the objective
    function; caching keyed by identity; honest degradation over guessing.
  - Schema changes are ADDITIVE ONLY. Existing corpora must still load.
  - Land tests WITH the code, in the same change. This is the repo's definition of done.
  - NEVER weaken or delete an existing test to make something pass. NEVER change a golden
    file's expected answer or page. If an existing test genuinely must change, that is a
    finding to report, not an edit to make quietly.
  - Do NOT run git commit, git push, git checkout, or git stash. The workflow handles git.
  - Do NOT modify .env, .venv/, or anything under .cache/.
  - If a ticket criterion is genuinely impossible, say so explicitly in open_items with the
    reason. Do not fake it and do not silently drop it.
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
  1. Read the four context files above, then the ticket.
  2. Explore the existing code you are extending. Match its style, its naming, its comment
     density, and its error-handling idiom. Read neighbouring modules before inventing shapes.
  3. Implement, writing tests alongside the code.
  4. Run ${PYTEST} and ${RUFF} yourself. Iterate until BOTH are clean.
     Do not report success until you have personally seen them pass.
  5. Update AGENTS.md / CONTEXT.md / README.md only where THIS ticket's criteria say to.

Set self_gate_green true only if you actually ran both commands and both passed.
Report honestly: a truthful partial result is far more useful than a false green.`
}

function gatePrompt(t) {
  return `Run the objective gate for ticket ${t.id} (${t.title}) in the datasheet_analyzer worktree.

Run EXACTLY these two commands from the repo root and report what happened:
  1. ${PYTEST}
  2. ${RUFF}

Then report the result. Rules:
  - green is true ONLY if pytest exited 0 AND ruff reported no issues.
  - Report the pytest exit code verbatim. Do not infer it from the output text.
  - If tests failed, list the failing node ids exactly and include the verbatim tail of the output.
  - Baseline before this phase was ${BASELINE_TESTS} tests. If tests_collected is now LOWER than
    that, treat it as a failure and say so in detail - it means tests were removed.

Do NOT fix anything. Do NOT edit any file. You are a measuring instrument, nothing else.`
}

function reviewPrompt(t, lens, implSummary) {
  const lenses = {
    criteria: `ACCEPTANCE-CRITERIA LENS.
Open ${TRACKER}/issues/${t.file} and walk its checkbox list ONE BOX AT A TIME.
For each box, find the specific code and the specific test that satisfies it, and cite them
as file:line. A box is satisfied only if BOTH exist. If a test merely asserts that code runs
without asserting the behaviour the box describes, the box is NOT satisfied.
Mark blocking:true if any box is unmet or only cosmetically met.`,

    invariants: `INVARIANT LENS.
Read AGENTS.md's invariant list, then audit the diff against it. Look specifically for:
  - content that is no longer verbatim-extracted, or an LLM touching corpus content
  - a test that reaches the network, spawns a subprocess, calls a real LLM, or depends on
    machine state, wall-clock time, or filesystem ordering
  - provenance loss: an answer path that can return a value without its page citation
  - a non-additive schema change that would break loading an existing corpus
  - a cache key that does not change when output shape changes
  - a guess where the repo's convention is honest degradation (empty + warning)
  - PHASE 5 SEAM: retrieval logic that has been left in, or added to, cli.py or the MCP
    server instead of living in retrieve/
Mark blocking:true for any real breach. Cite file:line.`,

    tests: `TEST-QUALITY AND REGRESSION LENS.
Audit the tests added by this ticket, and audit what happened to the tests that already existed.
Look specifically for:
  - tautological or vacuous assertions (asserting a mock, asserting True, asserting a value
    the test itself just computed the same way the code does)
  - a test that would still pass if the feature were deleted or stubbed
  - any EXISTING test that was deleted, skipped, xfailed, or had an assertion loosened
  - any golden file whose expected answer or page was altered
  - hidden coupling: a test that only passes because of another test's side effects
Run \`git diff --stat\` and \`git diff\` against the previous commit to see exactly what changed.
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

Be specific and evidence-based. A finding without a file:line or a verbatim quote is not a
finding. Do not invent problems to seem thorough: if the work is genuinely sound under your
lens, say so plainly and set blocking:false. Over-reporting is as costly as under-reporting,
because a false blocking verdict stalls the run.`
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
Rather than halting, your job is to work out WHY and propose a way through.

STEP 1 - DIAGNOSE. Find the real root cause. Distinguish carefully between:
  (a) the ticket is fine, the implementation approach was wrong
  (b) the ticket's design conflicts with something real in the existing codebase
  (c) the ticket's acceptance criteria are unachievable or self-contradictory as written
  (d) a reviewer is wrong and the work is actually correct

STEP 2 - EXPLORE ALTERNATIVES. Propose 2-4 genuinely different architectural approaches
that would satisfy the ticket's INTENT (read the SPEC's user stories for the intent - the
criteria are a means, not the end). For each: the approach, its tradeoffs, and whether it
breaches any AGENTS.md invariant. Be willing to propose changing the plan itself - the plan
is a document I wrote, not physics. A well-argued "this ticket should be re-scoped this way"
is a completely valid and valuable outcome.

STEP 3 - ACT.
  - If one alternative is clearly right AND breaches no invariant, IMPLEMENT it, run
    ${PYTEST} and ${RUFF} until green, and set applied:true.
  - If the right call needs a human judgment - it breaches an invariant, changes the phase's
    scope, or trades off something only the repo owner should trade off - do NOT implement.
    Set applied:false and write up the options clearly. Stopping with a good analysis beats
    guessing on an architectural decision.

Either way, fill spec_amendment with the exact prose that should be recorded in the ticket
or SPEC so this decision is not lost.

Do not run git commit/push/checkout/stash.`
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

async function runGate(t) {
  return await agent(gatePrompt(t), {
    label: `gate:${t.id}`,
    phase: t.phase,
    schema: GATE_SCHEMA,
    effort: 'low',
  })
}

async function runReviews(t, implSummary) {
  return await parallel([
    () => agent(reviewPrompt(t, 'criteria', implSummary), { label: `review:criteria:${t.id}`, phase: t.phase, schema: REVIEW_SCHEMA }),
    () => agent(reviewPrompt(t, 'invariants', implSummary), { label: `review:invariants:${t.id}`, phase: t.phase, schema: REVIEW_SCHEMA }),
    () => agent(reviewPrompt(t, 'tests', implSummary), { label: `review:tests:${t.id}`, phase: t.phase, schema: REVIEW_SCHEMA }),
  ])
}

// ---------------------------------------------------------------------------
// Main loop - sequential spine (the tickets are a dependency chain),
// with parallel review at each vertebra.
// ---------------------------------------------------------------------------

const completed = []
const priorSummaries = []
let stoppedAt = null
let stopReason = ''
const openItems = []

for (const t of TICKETS) {
  phase(t.phase)
  log(`Ticket ${t.id} - ${t.title}: implementing`)

  const impl = await agent(implPrompt(t, priorSummaries), {
    label: `impl:${t.id}`,
    phase: t.phase,
    schema: IMPL_SCHEMA,
  })

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
    await agent(repairPrompt(t, attempt, gate, reviews), {
      label: `repair${attempt}:${t.id}`,
      phase: t.phase,
    })
    gate = await runGate(t)
    reviews = gate && gate.green ? await runReviews(t, impl.summary) : []
  }

  let escalation = null
  if (blockedBy(gate, reviews)) {
    log(`Ticket ${t.id}: repairs exhausted, escalating to architectural exploration`)
    escalation = await agent(explorePrompt(t, gate, reviews), {
      label: `explore:${t.id}`,
      phase: t.phase,
      schema: EXPLORE_SCHEMA,
      effort: 'high',
    })
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
at the repo root so the repo owner can pick this up cold in the morning.

Include, in this order:
  1. Exactly where the run stopped and what the last green commit was (check \`git log --oneline\`).
  2. The objective gate state: ${JSON.stringify(gate)}
  3. What was tried across ${attempt} repair pass(es).
  4. ${escalation ? `The architectural analysis: ${JSON.stringify(escalation)}` : 'No escalation analysis was produced.'}
  5. The concrete decision the repo owner now needs to make, stated as a question with options.
  6. The exact state of the working tree (\`git status --short\`) so they know what is uncommitted.

Be honest and specific. Do not soften the failure. Do not run git commit/push/checkout/stash.`,
      { label: `handover:${t.id}`, phase: t.phase }
    )
    break
  }

  // Passed. Commit this ticket on its own.
  const caveats = reviews
    .filter(Boolean)
    .flatMap((r) => (r.findings || []).filter((f) => f.severity === 'should-fix'))
    .map((f) => f.what)

  await agent(
    `Commit the completed work for ticket ${t.id} (${t.title}) in the datasheet_analyzer worktree.

Steps:
  1. Run \`git status --short\` and \`git diff --stat\` to see what changed.
  2. Verify nothing ignored or unwanted is being added: .venv/, .cache/, .env, __pycache__,
     *.pyc must NOT be staged. If any appear, do not stage them.
  3. \`git add -A\` the legitimate source, test, registry, and doc changes.
  4. Commit with this message body (keep the subject line under 72 chars):

p5-${t.id}: ${t.title.toLowerCase()}

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
  `Write the run report for tonight's autonomous Phase 5 implementation, then push.

RESULT:
  - Tickets completed and committed: ${completed.length ? completed.join(', ') : 'none'}
  - Stopped at: ${stoppedAt || 'nothing - the full run completed'}
  ${stoppedAt ? `- Reason: ${stopReason}` : ''}
  - Open items reported by implementers:
${openItems.length ? openItems.map((o) => `      * ${o}`).join('\n') : '      (none)'}

DO THIS:
  1. Run \`git log --oneline origin/worktree-roadmap-phases-5-7..HEAD\` to list this run's commits.
  2. Run \`${PYTEST}\` and \`${RUFF}\` one final time and record the true result.
  3. Write Reports/PHASE_5_RUN_REPORT.md covering: what landed per ticket, the final test
     count vs the ${BASELINE_TESTS} baseline, every open item, every reviewer note carried
     forward, and what the repo owner should look at first. If the run stopped early, say so
     prominently at the top and point at STOPPED.md.
  4. Commit that report (message: "docs: phase 5 autonomous run report").
  5. Push the branch: \`git push -u origin HEAD\`.
     Do NOT open a pull request. Do NOT push to main.

Be accurate and unvarnished. If the final test run is not green, say that at the very top in
bold. The repo owner is reading this cold in the morning and needs the truth, not reassurance.`,
  { label: 'wrap-up', phase: 'Wrap-up' }
)

return {
  completed,
  total: TICKETS.length,
  stoppedAt,
  stopReason,
  openItems,
}
