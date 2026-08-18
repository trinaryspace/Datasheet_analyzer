/**
 * Where you land with no project open: recent folders, and a way to open one.
 *
 * Deliberately *not* a modal that gates the application. A dialog you must
 * dismiss before anything works is the right shape exactly once — the first
 * time — and wrong every time after, when what you want is the folder you had
 * open yesterday. VS Code shows a welcome screen for the same reason.
 *
 * Recents come from the server, not from browser storage: a project records
 * the directory it was opened from, so the list survives a cleared cache and
 * a different browser. That is the whole point of having moved it server-side.
 */
import { useEffect, useState } from 'react';

import { ApiError, getProjects, openProject } from '../../api/client';
import type { ProjectOut } from '../../api/types';
import FolderPicker from './FolderPicker';

export interface WelcomeStepProps {
  /** Called with the project that was opened, once one is. */
  onOpened: (project: ProjectOut) => void;
}

export default function WelcomeStep({ onOpened }: WelcomeStepProps) {
  const [recents, setRecents] = useState<ProjectOut[]>([]);
  const [directory, setDirectory] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const { projects } = await getProjects();
        // Only projects that came from a folder can be reopened as one.
        if (live) setRecents(projects.filter((p) => p.directory));
      } catch {
        // An empty recents list is a fine first-run state; the picker below
        // works regardless, so this never becomes an error screen.
        if (live) setRecents([]);
      }
    })();
    return () => {
      live = false;
    };
  }, []);

  async function open(path: string) {
    const target = path.trim();
    if (!target) return;
    setBusy(true);
    setError('');
    try {
      onOpened(await openProject({ directory: target }));
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.detail : 'that folder could not be opened',
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="analyze-welcome" aria-labelledby="analyze-welcome-heading">
      <h2 id="analyze-welcome-heading">Open a project folder</h2>
      <p className="analyze-hint">
        Point at the folder your design lives in. Every PDF inside it — including
        subfolders — is offered for analysis, and you choose which ones to build.
      </p>

      <FolderPicker
        value={directory}
        disabled={busy}
        onChange={setDirectory}
        onPick={(picked) => void open(picked)}
      />

      <div className="analyze-actions">
        <button type="button" onClick={() => void open(directory)} disabled={busy || !directory.trim()}>
          {busy ? 'Opening…' : 'Open'}
        </button>
      </div>

      {error ? (
        <p role="alert" className="analyze-error">
          {error}
        </p>
      ) : null}

      {recents.length > 0 ? (
        <div className="analyze-recents">
          <h3>Recent projects</h3>
          <ul>
            {recents.map((project) => (
              <li key={project.name}>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void open(project.directory)}
                >
                  <span className="analyze-recent-name">{project.name}</span>
                  <span className="analyze-recent-path">{project.directory}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
