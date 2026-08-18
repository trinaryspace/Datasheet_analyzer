/**
 * The backend contract, mirrored by hand.
 *
 * One exported type per model in `src/datasheet_analyzer/app/contracts.py`
 * (plus the four in `models.py` that contracts re-exports), named
 * identically so the two files can be diffed by eye and by test. Written
 * once by ticket 00; a frontend ticket that needs a shape not here has found
 * a contract gap and must report it rather than widen a type locally.
 *
 * Dates cross the wire as ISO-8601 strings (pydantic `mode="json"`), so
 * every `datetime` is `string` here and every `datetime | None` is
 * `string | null`.
 */

// --- scope, citations, applicability (models.py) ------------------------------

/** `Applicability.kind` — the three, and there is no fourth. */
export type ApplicabilityKind = 'parts' | 'family' | 'all';

/**
 * The set of parts a document is about (ADR 0005).
 *
 * `all` is the honest default: a document whose applicability cannot be
 * determined degrades to the previous flat behaviour, never to a wrong
 * owner. `evidence` says how it was decided and is never blank in practice —
 * it is what makes a wrong inference correctable instead of merely visible.
 */
export interface Applicability {
  kind: ApplicabilityKind;
  /** Read when `kind === 'parts'`. */
  parts: string[];
  /** Read when `kind === 'family'`, e.g. `AFE79xx`. */
  family: string;
  evidence: string;
}

/** `ScopeRef.kind` — exactly one Part or one Project; no "everything". */
export type ScopeKind = 'part' | 'project';

/** The scope an answer was drawn from: always shown, always editable (ADR 0006). */
export interface ScopeRef {
  kind: ScopeKind;
  name: string;
}

/**
 * A citation as the retrieval core built it.
 *
 * Render `label` (`§4.5, p.7`). Never assemble `p.N` in the frontend: the
 * citation format is what `dsa verify` measures, and it must not drift
 * between the CLI, the MCP server and this application.
 */
export interface CitationOut {
  doc: string;
  doc_hash: string;
  section: string;
  page_start: number | null;
  page_end: number | null;
  part: string;
  pages: string;
  label: string;
  /**
   * The record's own printed text — a spec row's parameter name, a figure's
   * caption, a section's title. Hand this to `/locate` so the highlight lands
   * on the row the number came from rather than on the section heading. May
   * be empty, in which case the page opens unhighlighted.
   */
  needle: string;
}

/** A `SourceDocument` as it appears inside a `LibraryDocument`. */
export interface SourceDocument {
  content_hash: string;
  path: string;
  part_number: string;
  doc_type: string;
  revision: string;
  page_count: number;
  nda: boolean;
  vendor: string;
  vendor_evidence: string;
  registered_at: string;
}

/** A document in the Library, plus the only two fields a user may change. */
export interface LibraryDocument {
  source: SourceDocument;
  applicability: Applicability;
  /** User text. The machine-derived `PlotRecord.tags` are Tags, not Labels. */
  labels: string[];
  added_at: string;
  schema_version: string;
}

/** Where one analyze job is. The last three are terminal. */
export type JobState =
  | 'queued'
  | 'extracting'
  | 'structuring'
  | 'enriching'
  | 'publishing'
  | 'done'
  | 'failed'
  | 'skipped';

/** The stages a job passes through, in order. */
export const JOB_STAGE_ORDER: JobState[] = [
  'queued',
  'extracting',
  'structuring',
  'enriching',
  'publishing',
];

/** A job emits nothing further once it reaches one of these. */
export const JOB_TERMINAL_STATES: JobState[] = ['done', 'failed', 'skipped'];

/** One PDF being built, carrying the applicability the user confirmed. */
export interface AnalyzeJob {
  id: string;
  pdf_path: string;
  part_number: string;
  applicability: Applicability;
  state: JobState;
  error: string;
  detail: string;
  started_at: string | null;
  finished_at: string | null;
}

/** One turn of a conversation, with the citations that back it. */
export interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
  citations: CitationOut[];
  created_at: string;
}

/** A saved conversation: messages, citations, and the scope they were answered under. */
export interface ChatSession {
  id: string;
  title: string;
  scope: ScopeRef;
  messages: ChatMessage[];
  created_at: string;
  updated_at: string;
}

// --- errors -------------------------------------------------------------------

/** FastAPI's error body. `detail` is always safe to render. */
export interface ErrorOut {
  detail: string;
  kind: string;
}

// --- catalog ------------------------------------------------------------------

/** One part corpus. `built: false` is a real, listable state, not a hidden one. */
export interface PartOut {
  part_number: string;
  built: boolean;
  revision: string;
  vendor: string;
  backends: string[];
  sections: number;
  specs: number;
  plots: number;
  tokens: number;
  searchable: boolean;
  spec_confidence: Record<string, number>;
  plot_confidence: Record<string, number>;
}

/** `GET /api/parts`. */
export interface PartsOut {
  parts: PartOut[];
  count: number;
}

/** One member of a project, with the role its designer gave it. */
export interface ProjectPartOut {
  part_number: string;
  role: string;
  built: boolean;
}

/** One project and its explicit part list. */
export interface ProjectOut {
  name: string;
  parts: ProjectPartOut[];
  interfaces: string;
  notes: string;
  /** The directory this project was scanned from; `''` when not recorded. */
  directory: string;
  /** Content hashes this project will never build. Excluding is not deleting. */
  excluded: string[];
  built: boolean;
  error: string;
}

/** `PATCH /api/projects/{name}` — omitting a field leaves it alone. */
export interface ProjectPatchIn {
  directory?: string;
  interfaces?: string;
  notes?: string;
}

/** `POST /api/projects` — a new, empty working set. */
export interface ProjectCreateIn {
  name: string;
  interfaces?: string;
  notes?: string;
}

/** `POST /api/projects/open` — adopt a directory as a working set. */
export interface ProjectOpenIn {
  directory: string;
}

/** `PUT /api/projects/{name}/exclusions` — the full set, not a delta. */
export interface ProjectExcludeIn {
  excluded: string[];
}

/** `POST /api/projects/{name}/parts` — parts to bring into the project. */
export interface ProjectPartsIn {
  parts: string[];
  role?: string;
}

/** `GET /api/projects`. */
export interface ProjectsOut {
  projects: ProjectOut[];
  count: number;
}

// --- browsing for a folder ------------------------------------------------------

/**
 * `POST /api/browse/dialog` — a native folder picker on the server's machine.
 *
 * Three distinct outcomes: a folder was chosen, the user cancelled, or no
 * dialog could open. Only `available: false` is a reason to fall back to the
 * in-app listing — cancelling means they changed their mind.
 */
export interface BrowsePickOut {
  available: boolean;
  picked: boolean;
  directory: string;
  reason: string;
}

/** One selectable directory in the in-app browser. */
export interface BrowseEntry {
  name: string;
  path: string;
}

/** `GET /api/browse/list`. `parent` is `''` at a filesystem root. */
export interface BrowseListOut {
  path: string;
  parent: string;
  entries: BrowseEntry[];
}

// --- scan and review ----------------------------------------------------------

/**
 * Whether analyzing this PDF will actually do any work.
 *
 * `current` is the only one that costs nothing. The other three all end in a
 * build, and `build_reason` says which of them and why.
 */
export type BuildState = 'new' | 'current' | 'stale' | 'changed';

/**
 * What inference proposes for one PDF — a proposal, never a decision.
 *
 * `evidence` is the part-number evidence; `applicability.evidence` is the
 * separate record for the applicability. Both are rendered: a user cannot
 * judge `AFE79xx` without seeing the line it came from.
 */
export interface DocProposal {
  pdf_path: string;
  filename: string;
  part_number: string;
  applicability: Applicability;
  evidence: string;
  page_count: number;
  doc_type: string;
  content_hash: string;
  build_state: BuildState;
  build_reason: string;
  /** Where it sits under the scanned folder; `''` at the top level. */
  relative_dir: string;
  /** False when this does not read like a source document at all. */
  is_datasheet: boolean;
}

/** `POST /api/analyze/scan` — a server-side directory path. */
export interface ScanIn {
  directory: string;
}

/** One proposal per direct-child PDF, sorted by filename. */
export interface ScanOut {
  directory: string;
  proposals: DocProposal[];
  count: number;
  /** Tally of `DocProposal.build_state`, so a caller need not walk the rows. */
  states: Partial<Record<BuildState, number>>;
  /**
   * Directories the walk deliberately did not descend into, with reasons.
   * Reported rather than swallowed: a scan that silently ignored half a shelf
   * looks exactly like one that found everything.
   */
  skipped: string[];
}

/** `POST /api/analyze/start` — the confirmed proposals, used verbatim. */
export interface StartIn {
  directory: string;
  proposals: DocProposal[];
}

/** Returned immediately; the build runs in the background. */
export interface StartOut {
  run_id: string;
  n_jobs: number;
}

/** One job transition on the analyze stream (`event: job`). */
export interface JobEvent {
  run_id: string;
  job_id: string;
  part_number: string;
  pdf_path: string;
  state: JobState;
  detail: string;
  at: string;
}

/** The whole run's current state (`event: snapshot`, sent on every connect). */
export interface RunSnapshot {
  run_id: string;
  directory: string;
  jobs: AnalyzeJob[];
  done: boolean;
}

// --- library ------------------------------------------------------------------

/**
 * One library document plus the parts it currently reaches.
 *
 * Reach is derived from applicability, so widening it can name a part that
 * does not exist yet — legal and intended (ADR 0005). Such parts come back
 * in `unbuilt_parts`, and `rebuild_needed` is the offer to materialize them.
 */
export interface LibraryDocumentOut {
  content_hash: string;
  path: string;
  filename: string;
  part_number: string;
  doc_type: string;
  vendor: string;
  page_count: number;
  applicability: Applicability;
  labels: string[];
  added_at: string | null;
  parts_reached: string[];
  unbuilt_parts: string[];
  rebuild_needed: string[];
}

/** `GET /api/library`. `labels` is every label in use, for autocomplete. */
export interface LibraryOut {
  documents: LibraryDocumentOut[];
  count: number;
  labels: string[];
}

/**
 * `PATCH /api/library/{content_hash}`.
 *
 * Omit a field to leave it alone; send `labels: []` to clear them. The two
 * are distinguishable on purpose.
 */
export interface LibraryPatchIn {
  applicability?: Applicability;
  labels?: string[];
}

// --- chat ---------------------------------------------------------------------

/** `POST /api/chat/resolve-scope`. */
export interface ResolveIn {
  question: string;
}

/**
 * Which scope a question resolved to — or a question back to the user.
 *
 * `scope === null` with `candidates` means **ask**: render the choices, and
 * issue no model request. There is no widen-to-everything fallback.
 */
export interface ScopeResolution {
  scope: ScopeRef | null;
  confident: boolean;
  candidates: ScopeRef[];
  question: string;
  matched_via: string;
}

/** `POST /api/chat/{session_id}/message`. A present `scope` skips resolution. */
export interface MessageIn {
  question: string;
  scope?: ScopeRef | null;
}

/** `ChatEvent.type` — also the SSE event name of the frame. */
export type ChatEventType = 'token' | 'tool' | 'citation' | 'scope' | 'done' | 'error';

/** One frame of the chat stream. */
export interface ChatEvent {
  type: ChatEventType;
  text: string;
  tool: string;
  summary: string;
  citation: CitationOut | null;
  scope: ScopeRef | null;
  resolution: ScopeResolution | null;
  confidence: string;
  message: string;
  at: string;
}

// --- sessions -----------------------------------------------------------------

/** `POST /api/sessions`. The id is always generated server-side. */
export interface SessionCreateIn {
  title?: string;
  scope?: ScopeRef | null;
}

/** One row of the sessions list. */
export interface SessionSummary {
  id: string;
  title: string;
  scope: ScopeRef;
  n_messages: number;
  created_at: string | null;
  updated_at: string | null;
}

/** `GET /api/sessions` — newest first. */
export interface SessionsOut {
  sessions: SessionSummary[];
  count: number;
}

/** One full transcript, with every citation intact. */
export interface SessionOut {
  id: string;
  title: string;
  scope: ScopeRef;
  messages: ChatMessage[];
  created_at: string | null;
  updated_at: string | null;
  n_messages: number;
}

/**
 * Export formats. `markdown` pastes into a design review; `golden` is a
 * `golden_qa_<PART>.yaml` entry — say so in the UI, because a verified
 * answer is one click from being a regression test.
 */
export type SessionExportFormat = 'markdown' | 'golden';

// --- locate -------------------------------------------------------------------

/** `GET /api/locate` query parameters. */
export interface LocateQuery {
  part: string;
  doc_hash: string;
  page: number;
  needle: string;
}

/**
 * One highlight rectangle in **PDF points**, PyMuPDF's space: origin at the
 * page's top-left, x right, **y down**, unrotated, at zoom 1.0. Convert by
 * applying the current zoom and the page rotation — do not assume the
 * bottom-left origin of raw PDF coordinates; these are already flipped.
 */
export interface RectOut {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

/**
 * Where to draw the highlight — or an honest miss.
 *
 * `found: false` means open the page with **no** highlight and show
 * `reason`. Never approximate: a box around the wrong row turns the
 * verification step into a lie.
 */
export interface LocateOut {
  found: boolean;
  page: number;
  rects: RectOut[];
  reason: string;
  needle: string;
  page_width: number;
  page_height: number;
  rotation: number;
}

// --- streaming and cross-pane state -------------------------------------------

/** SSE event names of the analyze stream. */
export const ANALYZE_EVENT_SNAPSHOT = 'snapshot';
export const ANALYZE_EVENT_JOB = 'job';
export const ANALYZE_EVENT_END = 'end';

/** Server heartbeat period, in seconds; a client may treat 3x this as dead. */
export const SSE_HEARTBEAT_SECONDS = 15;

/**
 * Cross-pane state lives in the URL query, so the chat pane and the PDF pane
 * never import each other. A citation click writes these; the PDF pane reads
 * them.
 */
export const PDF_PARAM_DOC = 'doc';
export const PDF_PARAM_PART = 'part';
export const PDF_PARAM_PAGE = 'page';
export const PDF_PARAM_NEEDLE = 'needle';

/** The decoded form of those parameters. */
export interface PdfTarget {
  doc_hash: string;
  part: string;
  page: number;
  needle: string;
}
