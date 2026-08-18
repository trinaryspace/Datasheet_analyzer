/**
 * The recent-directories list behind the path input.
 *
 * A browser cannot hand a server a usable directory path, so the path is
 * typed or pasted — which makes "the four directories you actually use"
 * worth remembering. Stored in `localStorage`, newest first, deduplicated,
 * and tolerant of a storage that throws (private mode, disabled storage):
 * losing the list is never worth losing the screen.
 */

export const RECENT_DIRECTORIES_KEY = 'dsa.analyze.recent-directories';
export const RECENT_DIRECTORIES_LIMIT = 8;

function storage(): Storage | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

/** Newest first. Returns `[]` for missing, unparsable or non-array data. */
export function readRecentDirectories(): string[] {
  try {
    const raw = storage()?.getItem(RECENT_DIRECTORIES_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((entry): entry is string => typeof entry === 'string' && entry !== '');
  } catch {
    return [];
  }
}

/** Push a directory to the front and return the new list. */
export function rememberDirectory(directory: string): string[] {
  const trimmed = directory.trim();
  if (!trimmed) return readRecentDirectories();
  const next = [trimmed, ...readRecentDirectories().filter((entry) => entry !== trimmed)].slice(
    0,
    RECENT_DIRECTORIES_LIMIT,
  );
  try {
    storage()?.setItem(RECENT_DIRECTORIES_KEY, JSON.stringify(next));
  } catch {
    // A full or unavailable storage costs the list, not the scan.
  }
  return next;
}
