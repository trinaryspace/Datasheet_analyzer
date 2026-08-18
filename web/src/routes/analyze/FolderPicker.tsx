/**
 * Choosing a folder, three ways, in order of how pleasant they are.
 *
 * **Browse…** asks the server to open a native folder dialog. That works only
 * because this application is local — the dialog opens on the machine running
 * the server, which is the machine you are sitting at. It is the nicest of the
 * three and the least dependable: it can appear *behind* the browser window,
 * and a headless host has no dialog at all.
 *
 * **The inline browser** is the fallback and the actual contract. The server
 * lists directories, you click down through them. It always works.
 *
 * **Typing the path** remains, because sometimes you already have it on the
 * clipboard and neither of the above is faster.
 */
import { useCallback, useState } from 'react';

import { ApiError, listDirectory, openFolderDialog } from '../../api/client';
import type { BrowseEntry } from '../../api/types';

export interface FolderPickerProps {
  value: string;
  disabled?: boolean;
  onChange: (directory: string) => void;
  /** Fired when a folder is chosen outright (dialog, or "use this folder"). */
  onPick?: (directory: string) => void;
}

export function FolderPicker({ value, disabled = false, onChange, onPick }: FolderPickerProps) {
  const [browsing, setBrowsing] = useState(false);
  const [here, setHere] = useState('');
  const [parent, setParent] = useState('');
  const [entries, setEntries] = useState<BrowseEntry[]>([]);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (path: string) => {
    setBusy(true);
    try {
      const listing = await listDirectory(path);
      setHere(listing.path);
      setParent(listing.parent);
      setEntries(listing.entries);
      if (listing.path) onChange(listing.path);
    } catch (caught) {
      setNote(caught instanceof ApiError ? caught.detail : 'that folder could not be read');
    } finally {
      setBusy(false);
    }
  }, [onChange]);

  async function browse() {
    setNote('');
    setBusy(true);
    try {
      const picked = await openFolderDialog();
      if (!picked.available) {
        // No dialog on this host: fall through to the inline browser rather
        // than leaving the user with a button that does nothing.
        setNote('No folder dialog on this machine — browse below instead.');
        setBrowsing(true);
        await load(value || '');
        return;
      }
      if (!picked.picked) return; // cancelled: an ordinary answer, not an error
      onChange(picked.directory);
      onPick?.(picked.directory);
    } catch (caught) {
      setNote(caught instanceof ApiError ? caught.detail : 'the folder dialog failed');
      setBrowsing(true);
      await load(value || '');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="folder-picker">
      <div className="folder-picker-row">
        <label htmlFor="analyze-directory">Project folder</label>
        <input
          id="analyze-directory"
          type="text"
          value={value}
          disabled={disabled}
          placeholder="C:\work\radar-frontend"
          onChange={(event) => onChange(event.target.value)}
        />
        <button type="button" onClick={() => void browse()} disabled={disabled || busy}>
          Browse…
        </button>
        <button
          type="button"
          onClick={() => {
            setBrowsing((open) => !open);
            if (!browsing) void load(value || '');
          }}
          disabled={disabled || busy}
          aria-expanded={browsing}
        >
          {browsing ? 'Hide list' : 'Or pick from a list'}
        </button>
      </div>

      {note ? (
        <p className="folder-picker-note" role="status">
          {note}
        </p>
      ) : null}

      {browsing ? (
        <div className="folder-picker-browser" aria-label="Folder browser">
          <p className="folder-picker-here">{here || 'Pick a drive to start'}</p>
          <ul>
            {parent ? (
              <li>
                <button type="button" onClick={() => void load(parent)} disabled={busy}>
                  ↑ up
                </button>
              </li>
            ) : null}
            {entries.map((entry) => (
              <li key={entry.path}>
                <button type="button" onClick={() => void load(entry.path)} disabled={busy}>
                  {entry.name}
                </button>
              </li>
            ))}
          </ul>
          {here ? (
            <button
              type="button"
              className="folder-picker-use"
              onClick={() => {
                onChange(here);
                onPick?.(here);
                setBrowsing(false);
              }}
              disabled={busy}
            >
              Use this folder
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export default FolderPicker;
