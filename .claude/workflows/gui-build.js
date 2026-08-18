export const meta = {
  name: 'gui-build',
  description: 'Build the datasheet workbench: contracts, then 21 parallel tickets, then integration',
  phases: [
    { title: 'Contracts' },
    { title: 'Build' },
    { title: 'Repair' },
    { title: 'Integrate' },
  ],
}

const TICKETS = [
  '01-library-store', '02-applicability-inference', '03-library-backed-acquire',
  '04-publish-shared-docs', '05-scope-seam', '06-app-skeleton',
  '07-analyze-jobs', '08-review-api', '09-library-api', '10-scope-resolver',
  '11-agent-tools', '12-chat-stream', '13-locate', '14-pdf-serve',
  '15-sessions', '16-fe-shell', '17-fe-analyze', '18-fe-chat',
  '19-fe-pdf', '20-fe-library', '21-docs',
]

// Environment mechanics. `python` and `ruff` on PATH are NOT the project's —
// the venv has no pip and is uv-managed. Every agent must use these exact paths.
const ENV = `ENVIRONMENT (exact commands — bare \`python\`/\`ruff\`/\`pytest\` on PATH are the WRONG ones):
- Python:  .venv/Scripts/python.exe
- Pytest:  .venv/Scripts/python.exe -m pytest tests/unit/test_<yours>.py -q
- Ruff:    .venv/Scripts/ruff.exe check <your files> && .venv/Scripts/ruff.exe format <your files>
- Node 24 / npm 11 are on PATH. fastapi, uvicorn, sse-starlette, mcp, anthropic,
  pymupdf (fitz), httpx and pydantic are already installed in the venv.
- Repo root is the working directory. You share this working tree with 20 other
  agents building other tickets concurrently. Their in-flight edits are NOT your
  concern and NOT your failures.`

const REPORT_SCHEMA = {
  type: 'object',
  required: ['ticket', 'testsPassed', 'testCommand', 'testResult', 'filesTouched'],
  properties: {
    ticket: { type: 'string' },
    testsPassed: { type: 'boolean', description: 'true only if your own test file ran green' },
    testCommand: { type: 'string' },
    testResult: { type: 'string', description: 'the pass/fail tail of the run, e.g. "14 passed in 2.1s"' },
    filesTouched: { type: 'array', items: { type: 'string' } },
    ownershipViolations: {
      type: 'array', items: { type: 'string' },
      description: 'files you edited that were NOT in your Owns list — empty if none',
    },
    contractGaps: {
      type: 'array', items: { type: 'string' },
      description: 'interfaces you needed that ticket 00 did not freeze, and what you coded against instead',
    },
    ruffClean: { type: 'boolean' },
    notes: { type: 'string' },
  },
}

const brief = (id) => `Read .scratch/gui/issues/${id}.md and implement it exactly.
Also read .scratch/gui/PLAN.md ("Rules every wave-1 agent follows") and
.scratch/gui/SPEC.md for the decisions behind the ticket. The contracts you code
against are already frozen on disk by ticket 00 — read them, do not invent them:
src/datasheet_analyzer/models.py, config.py, app/contracts.py, and for frontend
tickets web/src/api/types.ts and web/src/api/client.ts.

NON-NEGOTIABLE:
- Touch ONLY the files in the ticket's Owns list. If you believe you need a file
  you do not own, that is a contract gap: record it in contractGaps and code
  against the frozen signature anyway. Do not edit it.
- NEVER edit src/datasheet_analyzer/extract/pdf_layout.py and never bump
  output_version. The extraction cache must stay valid.
- Tests are hermetic: no network, no live model, no subprocess, no browser.
  Build synthetic PDFs in-test with fitz, use a fake LLM client, and set
  Settings(parts_dir=tmp, cache_dir=tmp, ...) with the reset_settings_cache hook.
- Every acceptance checkbox in the ticket must be satisfied by a real test.
- Run ONLY your own test file. Do not run the full suite — that is ticket 22's
  job, and running it now surfaces other agents' in-flight work as false failures.

${ENV}

Finish by reporting via the structured schema. Set testsPassed=true only if your
own test file actually ran green; if it is red, say so honestly with the failure.`

phase('Contracts')
const contracts = await agent(
  `Read .scratch/gui/issues/00-contracts.md and implement it exactly.
This ticket freezes every interface the other 21 tickets code against — a missing
or wrong signature blocks all of them, so be exhaustive and prefer an
over-specified contract to a gap. Every type, setting, endpoint request/response
model, function signature and its TypeScript mirror must exist on disk when you
finish. Stub bodies raise NotImplementedError; their owning ticket fills them in.

Also read .scratch/gui/SPEC.md, docs/adr/0005-documents-apply-to-parts.md and
docs/adr/0006-auto-resolved-scope.md.

THE HARD CONSTRAINT: SourceDocument must not change shape — it is embedded in
RawDocument which is serialized into .cache/extract/<hash>__<backend>.json, and a
new required field breaks validation of every cached extraction. Applicability
and labels live on a new LibraryDocument that wraps it. Never edit
src/datasheet_analyzer/extract/pdf_layout.py and never bump output_version.

Touch ONLY the files in the ticket's Owns list. Satisfy every acceptance
checkbox with a real, hermetic test in tests/unit/test_contracts.py. Run
\`npm install\` inside web/ so the scaffold is installed and \`npm run typecheck\`
passes — the 5 frontend tickets depend on that install being done.

${ENV}

Report every contract you froze: the models, the settings, the endpoint table,
the stubbed signatures, and the TypeScript type names.`,
  { label: 'contracts', phase: 'Contracts', effort: 'xhigh', schema: REPORT_SCHEMA },
)

log(`contracts: testsPassed=${contracts?.testsPassed} — ${contracts?.testResult ?? 'no result'}`)

phase('Build')
const built = await parallel(TICKETS.map((id) => () =>
  agent(brief(id), { label: id, phase: 'Build', schema: REPORT_SCHEMA })))

const results = TICKETS.map((id, i) => ({ id, r: built[i] }))
const red = results.filter(({ r }) => !r || r.testsPassed !== true)
log(`wave 1: ${results.length - red.length}/${TICKETS.length} green; repairing ${red.length}`)

// One repair pass per red ticket — same ownership rules, no widening of scope.
phase('Repair')
const repaired = red.length === 0 ? [] : await parallel(red.map(({ id, r }) => () =>
  agent(`Ticket ${id} was implemented but its own test file is not green.
Reported result: ${r ? JSON.stringify(r.testResult) : 'the agent died before reporting'}
Reported notes: ${r ? JSON.stringify(r.notes ?? '') : 'none'}

Read .scratch/gui/issues/${id}.md, read what is already on disk for it, and fix it
until \`.venv/Scripts/python.exe -m pytest <your test file> -q\` is green. Same
ownership rules: touch ONLY the files in that ticket's Owns list, never
src/datasheet_analyzer/extract/pdf_layout.py, never bump output_version, tests
stay hermetic. Do not delete or weaken a test to make it pass — if an acceptance
checkbox genuinely cannot be met, leave the test failing and say why in notes.

${ENV}`,
    { label: `repair:${id}`, phase: 'Repair', schema: REPORT_SCHEMA })
      .then((rr) => ({ id, rr }))))

const finalById = new Map(results.map(({ id, r }) => [id, r]))
for (const x of repaired) if (x?.rr) finalById.set(x.id, x.rr)

const green = TICKETS.filter((id) => finalById.get(id)?.testsPassed === true)
const stillRed = TICKETS.filter((id) => finalById.get(id)?.testsPassed !== true)

phase('Integrate')
const integration = await agent(
  `Read .scratch/gui/issues/22-integration.md and implement it.

Wave 1 status after one repair pass — ${green.length}/${TICKETS.length} green.
Green: ${green.join(', ') || 'none'}
Still red: ${stillRed.join(', ') || 'none'}
Reported contract gaps across all tickets:
${TICKETS.map((id) => {
    const g = finalById.get(id)?.contractGaps ?? []
    return g.length ? `- ${id}: ${g.join('; ')}` : null
  }).filter(Boolean).join('\n') || '- none reported'}

Run the FULL suite (\`.venv/Scripts/python.exe -m pytest -q\`) and
\`.venv/Scripts/ruff.exe check .\` over the whole repo. Fix integration-level
breakage only — wiring, imports, fixtures, drift between two tickets' assumptions.
Do NOT rewrite a ticket's feature work, and do not delete or weaken a test to make
the suite green. You are the only agent that may touch files outside a single
ticket's ownership; every such file must be listed in ownershipViolations with the
reason.

Baseline for comparison: before this build the suite was collected clean on the
merged feat/phase5-retrieval + GUI-docs tree.

${ENV}

Report: which tickets are green, which are red and why, what you had to touch
outside your ownership, and the final full-suite and ruff results verbatim.`,
  { label: 'integrate', phase: 'Integrate', effort: 'xhigh', schema: {
    type: 'object',
    required: ['fullSuiteResult', 'ruffResult', 'greenTickets', 'redTickets', 'ownershipViolations'],
    properties: {
      fullSuiteResult: { type: 'string' },
      ruffResult: { type: 'string' },
      greenTickets: { type: 'array', items: { type: 'string' } },
      redTickets: {
        type: 'array',
        items: {
          type: 'object',
          required: ['ticket', 'why'],
          properties: { ticket: { type: 'string' }, why: { type: 'string' } },
        },
      },
      ownershipViolations: {
        type: 'array',
        items: {
          type: 'object',
          required: ['file', 'reason'],
          properties: { file: { type: 'string' }, reason: { type: 'string' } },
        },
      },
      contractGapsConfirmed: { type: 'array', items: { type: 'string' } },
      notes: { type: 'string' },
    },
  } },
)

return {
  contracts,
  waveOne: TICKETS.map((id) => ({ ticket: id, ...(finalById.get(id) ?? { testsPassed: false, notes: 'agent died' }) })),
  green,
  stillRed,
  integration,
}
