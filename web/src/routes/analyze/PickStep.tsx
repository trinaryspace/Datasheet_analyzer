/**
 * Step one: point at a directory.
 *
 * There is no native directory picker that yields a **server-usable** path —
 * a browser hands out opaque `File` handles, and the analyzer needs a path it
 * can open itself. So the input is typed or pasted, the UI says exactly that
 * instead of showing a file button that cannot work, and the server validates
 * it: an unusable path comes back as a 400 whose message is rendered verbatim.
 */
import { useState } from 'react';
import type { FormEvent } from 'react';

import { ApiError, scanDirectory } from '../../api/client';
import type { ScanOut } from '../../api/types';
import { rememberDirectory, readRecentDirectories } from './recentDirectories';

export interface PickStepProps {
  onScanned: (scan: ScanOut) => void;
  /** Pre-filled when returning from a later step. */
  initialDirectory?: string;
}

function messageFor(error: unknown): string {
  // The server's own `detail` is written to be shown: the path that does not
  // exist, the directory with no PDFs in it. Never replace it.
  if (error instanceof ApiError) return error.detail;
  if (error instanceof Error && error.message) return error.message;
  return 'The scan could not be started.';
}

export default function PickStep({ onScanned, initialDirectory = '' }: PickStepProps) {
  const [directory, setDirectory] = useState(initialDirectory);
  const [recents, setRecents] = useState<string[]>(() => readRecentDirectories());
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState('');

  async function runScan(path: string) {
    const trimmed = path.trim();
    if (!trimmed) {
      setError('Enter the full path of a directory on this machine.');
      return;
    }
    setScanning(true);
    setError('');
    try {
      const scan = await scanDirectory({ directory: trimmed });
      setRecents(rememberDirectory(trimmed));
      onScanned(scan);
    } catch (caught) {
      setError(messageFor(caught));
    } finally {
      setScanning(false);
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void runScan(directory);
  }

  return (
    <section className="analyze-step analyze-pick" aria-labelledby="analyze-pick-heading">
      <h2 id="analyze-pick-heading">Analyze a directory</h2>
      <p className="analyze-hint">
        Type or paste the full path of a directory <strong>on the machine running the
        server</strong>. A browser cannot hand the server a folder, so there is no file
        picker here — the path is checked when you scan.
      </p>

      <form onSubmit={onSubmit} className="analyze-pick-form">
        <label htmlFor="analyze-directory">Directory path</label>
        <input
          id="analyze-directory"
          name="directory"
          type="text"
          autoComplete="off"
          spellCheck={false}
          placeholder="/home/me/datasheets"
          value={directory}
          disabled={scanning}
          onChange={(event) => setDirectory(event.target.value)}
        />
        <button type="submit" disabled={scanning}>
          {scanning ? 'Scanning…' : 'Scan'}
        </button>
      </form>

      {scanning ? (
        <p role="status" className="analyze-loading">
          Scanning {directory.trim()} for PDFs…
        </p>
      ) : null}

      {error ? (
        <p role="alert" className="analyze-error">
          {error}
        </p>
      ) : null}

      <section aria-labelledby="analyze-recent-heading" className="analyze-recents">
        <h3 id="analyze-recent-heading">Recent directories</h3>
        {recents.length === 0 ? (
          <p className="analyze-empty">
            No directories yet. The ones you scan will be listed here.
          </p>
        ) : (
          <ul>
            {recents.map((entry) => (
              <li key={entry}>
                <button
                  type="button"
                  disabled={scanning}
                  onClick={() => {
                    setDirectory(entry);
                    void runScan(entry);
                  }}
                >
                  {entry}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </section>
  );
}
