/**
 * The working set: which project every screen is being read through.
 *
 * It lived inside the Library, which made the project the *last* thing a user
 * chose when it is the first thing they decide. Hoisting it into the shell
 * makes it context the whole application inherits — Library narrows to it,
 * Analyze prefills its directory from it, Chat falls back to it.
 *
 * Two places hold the value and they are deliberately not the same:
 *
 * - `localStorage` so the choice survives a reload, because a working set the
 *   user re-picks every morning is not a working set.
 * - the `?project=` search param so a link carries it, because "look at this
 *   under the LNA project" should be one paste.
 *
 * The URL wins on first load: a pasted link must show what the sender saw,
 * not what the recipient last had open.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';

/** The sentinel for "no working set": the whole library, unnarrowed. */
export const NO_PROJECT = '';

/** Search param and storage key, exported so tests need not retype them. */
export const PROJECT_PARAM = 'project';
const STORAGE_KEY = 'dsa.workingSet';

export interface WorkingSet {
  /** The selected project's name, or `NO_PROJECT`. */
  project: string;
  setProject: (name: string) => void;
}

const WorkingSetContext = createContext<WorkingSet | null>(null);

function readStored(): string {
  try {
    return globalThis.localStorage?.getItem(STORAGE_KEY) ?? NO_PROJECT;
  } catch {
    // Private browsing and disabled storage both throw. A working set that
    // does not persist is a lesser failure than a screen that will not render.
    return NO_PROJECT;
  }
}

function writeStored(name: string): void {
  try {
    if (name) globalThis.localStorage?.setItem(STORAGE_KEY, name);
    else globalThis.localStorage?.removeItem(STORAGE_KEY);
  } catch {
    /* see readStored */
  }
}

export function WorkingSetProvider({ children }: { children: ReactNode }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const fromUrl = searchParams.get(PROJECT_PARAM);

  // The URL wins on first load; storage is the fallback.
  const [project, setProjectState] = useState<string>(() => fromUrl ?? readStored());

  // A later URL change (back button, a second pasted link) is authoritative too.
  useEffect(() => {
    if (fromUrl !== null && fromUrl !== project) setProjectState(fromUrl);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fromUrl]);

  const setProject = useCallback(
    (name: string) => {
      setProjectState(name);
      writeStored(name);
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current);
          if (name) next.set(PROJECT_PARAM, name);
          else next.delete(PROJECT_PARAM);
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const value = useMemo(() => ({ project, setProject }), [project, setProject]);
  return <WorkingSetContext.Provider value={value}>{children}</WorkingSetContext.Provider>;
}

/**
 * The working set, or an inert one outside a provider.
 *
 * Falling back rather than throwing keeps a screen renderable in isolation —
 * which is how several of them are tested — and "no working set" is a real
 * state the application already handles everywhere.
 */
export function useWorkingSet(): WorkingSet {
  const found = useContext(WorkingSetContext);
  const [orphan, setOrphan] = useState<string>(NO_PROJECT);
  const inert = useMemo(
    () => ({ project: orphan, setProject: setOrphan }),
    [orphan],
  );
  return found ?? inert;
}

export default WorkingSetProvider;
