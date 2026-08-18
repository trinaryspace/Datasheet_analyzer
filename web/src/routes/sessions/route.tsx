/**
 * The Sessions screen: saved conversations, newest first.
 *
 * Opening one loads its full transcript and hands it to the chat pane through
 * the URL (`/chat?session=<id>`) — the cross-pane rule from `App.tsx`, so this
 * screen never imports the chat pane. The load happens here, before the
 * navigation, so a session that cannot be read reports its error where the
 * user clicked rather than on a screen they have just been sent to.
 *
 * Export offers both formats the server emits, and says what each is for. The
 * golden one is the one that needs saying: an engineer who has just verified
 * an answer is one click from a regression test, and will not discover that
 * unless the UI tells them.
 */
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { exportSession, getSession, listSessions } from '../../api/client';
import type { SessionExportFormat, SessionSummary } from '../../api/types';
import { downloadText } from './download';
import type { DownloadText } from './download';
import {
  chatRestoreUrl,
  describeMessageCount,
  describeScope,
  errorMessage,
  exportButtonLabel,
  exportDescription,
  exportFilename,
  exportMimeType,
  formatTimestamp,
  sortSessions,
} from './state';

/** Route metadata read by `App.tsx`'s filesystem route discovery. */
export const path = '/sessions';
export const label = 'Sessions';
export const order = 40;

const FORMATS: SessionExportFormat[] = ['markdown', 'golden'];

type LoadState = 'loading' | 'ready' | 'error';

export interface SessionsScreenProps {
  /** The download seam; defaults to a real object-URL download. */
  download?: DownloadText;
}

export function SessionsScreen({ download = downloadText }: SessionsScreenProps) {
  const navigate = useNavigate();
  const [status, setStatus] = useState<LoadState>('loading');
  const [error, setError] = useState('');
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [busy, setBusy] = useState('');
  const [note, setNote] = useState('');
  const [rowError, setRowError] = useState('');

  const load = useCallback(async () => {
    setStatus('loading');
    setError('');
    try {
      const listed = await listSessions();
      setSessions(sortSessions(listed.sessions));
      setStatus('ready');
    } catch (caught) {
      setError(errorMessage(caught, 'the saved conversations could not be read'));
      setStatus('error');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function open(session: SessionSummary): Promise<void> {
    setRowError('');
    setNote('');
    setBusy(`open:${session.id}`);
    try {
      const restored = await getSession(session.id);
      setNote(
        `Restoring ${describeMessageCount(restored.messages.length)} from “${restored.title}” into the chat pane.`,
      );
      navigate(chatRestoreUrl(restored.id));
    } catch (caught) {
      setRowError(errorMessage(caught, 'that conversation could not be opened'));
    } finally {
      setBusy('');
    }
  }

  async function save(session: SessionSummary, format: SessionExportFormat): Promise<void> {
    setRowError('');
    setNote('');
    setBusy(`${format}:${session.id}`);
    try {
      const text = await exportSession(session.id, format);
      download(exportFilename(session, format), text, exportMimeType(format));
      setNote(`Downloaded ${exportFilename(session, format)}.`);
    } catch (caught) {
      setRowError(errorMessage(caught, 'the export failed'));
    } finally {
      setBusy('');
    }
  }

  if (status === 'loading') {
    return (
      <main aria-labelledby="sessions-heading">
        <h2 id="sessions-heading">Sessions</h2>
        <p role="status">Loading saved conversations…</p>
      </main>
    );
  }

  if (status === 'error') {
    return (
      <main aria-labelledby="sessions-heading">
        <h2 id="sessions-heading">Sessions</h2>
        <p role="alert">{error}</p>
        <button type="button" onClick={() => void load()}>
          Retry
        </button>
      </main>
    );
  }

  return (
    <main aria-labelledby="sessions-heading">
      <h2 id="sessions-heading">Sessions</h2>

      {note ? <p role="status">{note}</p> : null}
      {rowError ? <p role="alert">{rowError}</p> : null}

      {sessions.length === 0 ? (
        <p className="sessions-empty">
          No saved conversations yet. Ask a question in the chat pane and it is kept here.
        </p>
      ) : (
        <ol className="sessions-list">
          {sessions.map((session) => (
            <li key={session.id}>
              <article aria-label={`Session ${session.title}`}>
                <h3>{session.title}</h3>
                <p className="sessions-meta">
                  <span className="sessions-scope">{describeScope(session)}</span>
                  <span className="sessions-count">
                    {describeMessageCount(session.n_messages)}
                  </span>
                  {formatTimestamp(session.updated_at ?? session.created_at) ? (
                    <time dateTime={session.updated_at ?? session.created_at ?? undefined}>
                      {formatTimestamp(session.updated_at ?? session.created_at)}
                    </time>
                  ) : null}
                </p>
                <div className="sessions-actions">
                  <button
                    type="button"
                    disabled={busy !== ''}
                    onClick={() => void open(session)}
                  >
                    {busy === `open:${session.id}`
                      ? 'Opening…'
                      : `Open ${session.title} in the chat pane`}
                  </button>
                  {FORMATS.map((format) => (
                    <span key={format} className="sessions-export">
                      <button
                        type="button"
                        disabled={busy !== ''}
                        onClick={() => void save(session, format)}
                      >
                        {`${exportButtonLabel(format)} for ${session.title}`}
                      </button>
                      <span className="sessions-export-note">{exportDescription(format)}</span>
                    </span>
                  ))}
                </div>
              </article>
            </li>
          ))}
        </ol>
      )}
    </main>
  );
}

export default function SessionsRoute() {
  return <SessionsScreen />;
}
