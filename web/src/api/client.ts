/**
 * The typed API client: one function per endpoint, plus the SSE helpers.
 *
 * Every server call in the application goes through this file. A screen that
 * hand-builds a `fetch` has forked the contract, and the two will drift.
 * Written once by ticket 00 and not modified by the frontend tickets.
 *
 * Errors: a non-2xx response raises `ApiError`, whose `detail` is the
 * server's own message (`ErrorOut.detail`). That message is written to be
 * shown — the scope refusal, the directory that does not exist, the recorded
 * path a PDF moved from — so render it rather than replacing it with a
 * generic string.
 *
 * Streaming: both SSE endpoints are one-way server-to-client. The analyze
 * stream is a GET (`openSSE`), and the chat stream is a POST carrying the
 * question (`openSSEPost`, a `fetch` body reader, because `EventSource`
 * cannot POST). Both return a handle whose `close()` aborts the request —
 * call it on unmount, and on "stop generating".
 */
import type {
  ChatEvent,
  JobEvent,
  LibraryDocumentOut,
  LibraryOut,
  LibraryPatchIn,
  LocateOut,
  LocateQuery,
  MessageIn,
  PartsOut,
  ProjectCreateIn,
  ProjectOut,
  ProjectPartsIn,
  ProjectPatchIn,
  ProjectsOut,
  ResolveIn,
  RunSnapshot,
  ScanIn,
  ScanOut,
  ScopeResolution,
  SessionCreateIn,
  SessionExportFormat,
  SessionOut,
  SessionsOut,
  StartIn,
  StartOut,
} from './types';

/** Every route lives under this prefix; the dev server proxies it. */
export const API_PREFIX = '/api';

/** A non-2xx response, carrying the server's own `detail` message. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail || `request failed with status ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    throw new ApiError(response.status, await readDetail(response));
  }
  return (await response.json()) as T;
}

async function readDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body?.detail === 'string') return body.detail;
    return JSON.stringify(body);
  } catch {
    return response.statusText;
  }
}

function jsonBody(payload: unknown): RequestInit {
  return { method: 'POST', body: JSON.stringify(payload) };
}

// --- catalog ------------------------------------------------------------------

/** `GET /api/parts` — built and half-built parts alike. */
export function getParts(): Promise<PartsOut> {
  return request<PartsOut>('/parts');
}

/** `GET /api/projects`. */
export function getProjects(): Promise<ProjectsOut> {
  return request<ProjectsOut>('/projects');
}

/** `POST /api/projects` — a new, empty working set. 409 if the name is taken. */
export function createProject(body: ProjectCreateIn): Promise<ProjectOut> {
  return request<ProjectOut>('/projects', jsonBody(body));
}

/**
 * `PATCH /api/projects/{name}` — the fields a user maintains.
 *
 * Omitting a field leaves it alone, so a screen editing the directory cannot
 * blank the notes by not sending them.
 */
export function patchProject(name: string, body: ProjectPatchIn): Promise<ProjectOut> {
  return request<ProjectOut>(`/projects/${encodeURIComponent(name)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });
}

/** `POST /api/projects/{name}/parts` — bring parts into the working set. */
export function addProjectParts(name: string, body: ProjectPartsIn): Promise<ProjectOut> {
  return request<ProjectOut>(`/projects/${encodeURIComponent(name)}/parts`, jsonBody(body));
}

/**
 * `DELETE /api/projects/{name}/parts/{part}` — drop a part from the working
 * set. The corpus under `parts/` is untouched; a project is only a view.
 */
export function removeProjectPart(name: string, partNumber: string): Promise<ProjectOut> {
  return request<ProjectOut>(
    `/projects/${encodeURIComponent(name)}/parts/${encodeURIComponent(partNumber)}`,
    { method: 'DELETE' },
  );
}

// --- analyze ------------------------------------------------------------------

/** `POST /api/analyze/scan` — read-only; nothing is built or written. */
export function scanDirectory(body: ScanIn): Promise<ScanOut> {
  return request<ScanOut>('/analyze/scan', jsonBody(body));
}

/** `POST /api/analyze/start` — returns at once; the run continues in the background. */
export function startAnalyze(body: StartIn): Promise<StartOut> {
  return request<StartOut>('/analyze/start', jsonBody(body));
}

/** Handlers for the analyze stream. `snapshot` arrives first on every connect. */
export interface AnalyzeStreamHandlers {
  onSnapshot?: (snapshot: RunSnapshot) => void;
  onJob?: (event: JobEvent) => void;
  onEnd?: () => void;
  onError?: (error: unknown) => void;
  onOpen?: () => void;
}

/** `GET /api/analyze/{run_id}/events` — SSE. Call `close()` on unmount. */
export function openAnalyzeStream(
  runId: string,
  handlers: AnalyzeStreamHandlers,
): SSEConnection {
  return openSSE(`/analyze/${encodeURIComponent(runId)}/events`, {
    onEvent: (event, data) => {
      if (event === 'snapshot') handlers.onSnapshot?.(JSON.parse(data) as RunSnapshot);
      else if (event === 'job') handlers.onJob?.(JSON.parse(data) as JobEvent);
      else if (event === 'end') handlers.onEnd?.();
    },
    onError: handlers.onError,
    onOpen: handlers.onOpen,
  });
}

// --- library ------------------------------------------------------------------

/** `GET /api/library`. */
export function getLibrary(): Promise<LibraryOut> {
  return request<LibraryOut>('/library');
}

/** `PATCH /api/library/{content_hash}` — applicability, labels, or both. */
export function patchLibraryDocument(
  contentHash: string,
  body: LibraryPatchIn,
): Promise<LibraryDocumentOut> {
  return request<LibraryDocumentOut>(`/library/${encodeURIComponent(contentHash)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });
}

// --- chat ---------------------------------------------------------------------

/** `POST /api/chat/resolve-scope` — show the chip before committing to an answer. */
export function resolveScope(body: ResolveIn): Promise<ScopeResolution> {
  return request<ScopeResolution>('/chat/resolve-scope', jsonBody(body));
}

/** `POST /api/chat/{session_id}/message` — SSE of `ChatEvent`, one frame per event. */
export function openChatStream(
  sessionId: string,
  body: MessageIn,
  handlers: {
    onEvent?: (event: ChatEvent) => void;
    onError?: (error: unknown) => void;
    onOpen?: () => void;
    onClose?: () => void;
  },
): SSEConnection {
  return openSSEPost(`/chat/${encodeURIComponent(sessionId)}/message`, body, {
    onEvent: (_name, data) => handlers.onEvent?.(JSON.parse(data) as ChatEvent),
    onError: handlers.onError,
    onOpen: handlers.onOpen,
    onClose: handlers.onClose,
  });
}

// --- sessions -----------------------------------------------------------------

/** `GET /api/sessions` — newest first. */
export function listSessions(): Promise<SessionsOut> {
  return request<SessionsOut>('/sessions');
}

/** `POST /api/sessions`. */
export function createSession(body: SessionCreateIn = {}): Promise<SessionOut> {
  return request<SessionOut>('/sessions', jsonBody(body));
}

/** `GET /api/sessions/{id}` — the full transcript. */
export function getSession(sessionId: string): Promise<SessionOut> {
  return request<SessionOut>(`/sessions/${encodeURIComponent(sessionId)}`);
}

/** `GET /api/sessions/{id}/export` — markdown, or a golden-Q&A fixture entry. */
export async function exportSession(
  sessionId: string,
  format: SessionExportFormat = 'markdown',
): Promise<string> {
  const response = await fetch(
    `${API_PREFIX}/sessions/${encodeURIComponent(sessionId)}/export?format=${format}`,
  );
  if (!response.ok) {
    throw new ApiError(response.status, await readDetail(response));
  }
  return response.text();
}

// --- verify -------------------------------------------------------------------

/** `GET /api/locate` — rectangles for a citation, or an honest miss. */
export function locate(query: LocateQuery): Promise<LocateOut> {
  const params = new URLSearchParams({
    part: query.part,
    doc_hash: query.doc_hash,
    page: String(query.page),
    needle: query.needle,
  });
  return request<LocateOut>(`/locate?${params.toString()}`);
}

/**
 * `GET /api/pdf/{content_hash}` as a URL, not a fetch: PDF.js must issue its
 * own range requests, so hand it the URL and let it read the bytes it needs.
 */
export function pdfUrl(contentHash: string): string {
  return `${API_PREFIX}/pdf/${encodeURIComponent(contentHash)}`;
}

// --- SSE ----------------------------------------------------------------------

/** A live stream. `close()` is idempotent and safe to call from a cleanup. */
export interface SSEConnection {
  close: () => void;
}

/** Low-level frame handlers: `(eventName, data)` per SSE frame. */
export interface SSEHandlers {
  onEvent: (event: string, data: string) => void;
  onError?: (error: unknown) => void;
  onOpen?: () => void;
  onClose?: () => void;
}

/** GET stream over `EventSource` (the analyze run). */
export function openSSE(path: string, handlers: SSEHandlers): SSEConnection {
  const source = new EventSource(`${API_PREFIX}${path}`);
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    source.close();
    handlers.onClose?.();
  };
  source.onopen = () => handlers.onOpen?.();
  source.onerror = (event) => handlers.onError?.(event);
  // `EventSource` only delivers named events to named listeners, and the
  // default `message` handler never sees them, so both are wired.
  source.onmessage = (event: MessageEvent<string>) => handlers.onEvent('message', event.data);
  for (const name of ['snapshot', 'job', 'end']) {
    source.addEventListener(name, (event) => {
      handlers.onEvent(name, (event as MessageEvent<string>).data);
      if (name === 'end') close();
    });
  }
  return { close };
}

/**
 * POST stream over `fetch` + a body reader (the chat turn).
 *
 * `EventSource` cannot POST, and the question has to travel in a body. The
 * parser is deliberately minimal — `event:` and `data:` lines, frames
 * separated by a blank line, `:` comments (the heartbeat) ignored.
 */
export function openSSEPost(path: string, body: unknown, handlers: SSEHandlers): SSEConnection {
  const controller = new AbortController();
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    controller.abort();
    handlers.onClose?.();
  };

  void (async () => {
    try {
      const response = await fetch(`${API_PREFIX}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new ApiError(response.status, await readDetail(response));
      }
      handlers.onOpen?.();
      const reader = response.body?.getReader();
      if (!reader) throw new Error('this browser cannot read a streaming response');
      const decoder = new TextDecoder();
      let buffer = '';
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // A frame ends at a blank line, and the line terminator may be CRLF,
        // LF or CR — `sse-starlette` sends CRLF, so searching for `\n\n`
        // alone never matches and the whole stream arrives as one frame.
        // Matching on the buffer (rather than normalizing it) keeps a `\r\n`
        // straddling two chunks from being mistaken for a frame boundary.
        for (;;) {
          const boundary = /\r\n\r\n|\n\n|\r\r/.exec(buffer);
          if (!boundary) break;
          dispatchFrame(buffer.slice(0, boundary.index), handlers);
          buffer = buffer.slice(boundary.index + boundary[0].length);
        }
      }
      if (buffer.trim()) dispatchFrame(buffer, handlers);
      close();
    } catch (error) {
      if (closed) return;
      handlers.onError?.(error);
      close();
    }
  })();

  return { close };
}

function dispatchFrame(frame: string, handlers: SSEHandlers): void {
  let event = 'message';
  const data: string[] = [];
  for (const rawLine of frame.split('\n')) {
    const line = rawLine.replace(/\r$/, '');
    if (!line || line.startsWith(':')) continue; // blank or heartbeat comment
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
  }
  if (data.length > 0) handlers.onEvent(event, data.join('\n'));
}
