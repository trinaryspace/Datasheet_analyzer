/**
 * The sessions screen's model: pure functions, no React, no fetch.
 *
 * The two decisions worth stating are here rather than in the component.
 *
 * **Newest first** is enforced client-side even though the server already
 * sorts. The ordering is what makes the list usable, it costs one comparison,
 * and a screen that only looks right because of a server-side detail is a
 * screen that quietly goes wrong when that detail moves.
 *
 * **The chat handoff travels in the URL**, per the cross-pane rule in
 * `App.tsx`: the sessions list never imports the chat pane, it navigates to
 * `/chat?session=<id>` and the chat pane restores the transcript from that id.
 */
import type { SessionExportFormat, SessionSummary } from '../../api/types';

/** The URL query parameter the chat pane restores a saved transcript from. */
export const CHAT_PARAM_SESSION = 'session';

/** The chat route's path, as `App.tsx`'s discovery derives it from the directory. */
export const CHAT_PATH = '/chat';

/** Where "open this session" navigates to: the chat pane, carrying the id. */
export function chatRestoreUrl(sessionId: string): string {
  return `${CHAT_PATH}?${CHAT_PARAM_SESSION}=${encodeURIComponent(sessionId)}`;
}

function sortKey(session: SessionSummary): string {
  return session.updated_at ?? session.created_at ?? '';
}

/**
 * Newest first, by `updated_at` and then `created_at`.
 *
 * Both cross the wire as ISO-8601, which sorts correctly as text. A session
 * with neither timestamp sorts last rather than first, so an incomplete record
 * never claims to be the most recent conversation.
 */
export function sortSessions(sessions: SessionSummary[]): SessionSummary[] {
  return [...sessions].sort((a, b) => {
    const left = sortKey(a);
    const right = sortKey(b);
    if (left === right) return a.title.localeCompare(b.title);
    if (!left) return 1;
    if (!right) return -1;
    return right.localeCompare(left);
  });
}

/** The scope chip's text: `part AFE7950`, `project rf-frontend`, or a dash. */
export function describeScope(session: Pick<SessionSummary, 'scope'>): string {
  const scope = session.scope;
  if (!scope || !scope.name) return 'no scope';
  return `${scope.kind} ${scope.name}`;
}

/** `3 messages`, and `1 message` when there is one. */
export function describeMessageCount(count: number): string {
  return count === 1 ? '1 message' : `${count} messages`;
}

/** ISO-8601 rendered as `2026-08-16 14:02`, or `''` when there is no timestamp. */
export function formatTimestamp(iso: string | null): string {
  if (!iso) return '';
  return iso.slice(0, 16).replace('T', ' ');
}

function slug(text: string): string {
  return text
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

/**
 * What the exported file is called.
 *
 * The golden export is named exactly as the fixture it becomes — an engineer
 * who has just verified an answer should be able to drop the file into
 * `tests/fixtures/` without renaming it (AGENTS.md invariant 5).
 */
export function exportFilename(
  session: Pick<SessionSummary, 'id' | 'title' | 'scope'>,
  format: SessionExportFormat,
): string {
  if (format === 'golden') {
    const part = session.scope?.kind === 'part' ? session.scope.name : '';
    const stem = slug(part || session.scope?.name || session.title || session.id)
      .toUpperCase()
      .replace(/-/g, '_');
    return `golden_qa_${stem || 'SESSION'}.yaml`;
  }
  return `session-${slug(session.title) || slug(session.id) || 'session'}.md`;
}

/** The MIME type each export is offered as. */
export function exportMimeType(format: SessionExportFormat): string {
  return format === 'golden' ? 'application/yaml' : 'text/markdown';
}

/** What the export button says. */
export function exportButtonLabel(format: SessionExportFormat): string {
  return format === 'golden' ? 'Export golden Q&A fixture' : 'Export markdown';
}

/**
 * What the export is *for* — rendered beside the button.
 *
 * The golden option is the one that needs saying: an engineer who has just
 * verified an answer is one click from a regression test, and will not find
 * that unless the UI says so.
 */
export function exportDescription(format: SessionExportFormat): string {
  return format === 'golden'
    ? 'A tests/fixtures/golden_qa_<PART>.yaml entry: turn this verified answer into a regression test.'
    : 'Markdown with citations, for pasting into a design review.';
}

/** The message an unknown thrown value should be rendered as. */
export function errorMessage(error: unknown, fallback = 'the request failed'): string {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === 'string' && error) return error;
  return fallback;
}
