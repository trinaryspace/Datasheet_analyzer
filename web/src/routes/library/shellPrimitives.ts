/**
 * The shell primitive this screen borrows, resolved without a static import.
 *
 * `ApplicabilityControl` belongs to ticket 16 (`web/src/shell/**`). Nothing in
 * this directory implements one: the review screen (ticket 17) and this screen
 * both edit applicability, and a second copy would mean two validation rules
 * for one model within a month. What lives here is only the *lookup* — the
 * same `import.meta.glob` seam `App.tsx` uses to discover `shell/Shell.tsx`,
 * which resolves at build time and yields an empty record when the shell is
 * not built yet, where a static `import` would be a hard resolution error.
 *
 * When the control is absent the screen renders applicability read-only and
 * says why. An editor that validated differently from the shell's would be
 * worse than no editor.
 */
import type { ComponentType } from 'react';

import type { Applicability } from '../../api/types';

/**
 * The props the shell's `ApplicabilityControl` is called with.
 *
 * Ticket 00 froze the `Applicability` model but not this component's
 * signature, so this is the contract the library screen codes against — a
 * controlled value plus a change handler, mirroring the model exactly. It is
 * character-for-character the contract `routes/analyze/shellPrimitives.ts`
 * declares, so the two screens ask the shell for the same thing.
 */
export interface ApplicabilityControlProps {
  value: Applicability;
  onChange: (next: Applicability) => void;
  /** Stable DOM id, so a row's control can be labelled and found. */
  id?: string;
  /** Accessible name for the control as a whole. */
  label?: string;
  disabled?: boolean;
  /**
   * The taxonomy, for the `category` kind — a supporting document applies to
   * a whole category and to no part. Empty hides that option: a shelf with no
   * categories should not offer to file a document into one.
   */
  categories?: readonly { id: string; name: string }[];
}

type ShellModule = Record<string, unknown>;

const shellModules = import.meta.glob<ShellModule>('../../shell/**/*.{ts,tsx}', {
  eager: true,
});

/**
 * The shell's `ApplicabilityControl`, or `null` when the shell is not built.
 *
 * Every module under `web/src/shell/` is scanned for the export by name, so
 * ticket 16 may place it in an index, a barrel, or its own file without this
 * screen caring which.
 */
export function getApplicabilityControl(): ComponentType<ApplicabilityControlProps> | null {
  for (const module of Object.values(shellModules)) {
    const candidate = (module as ShellModule | undefined)?.ApplicabilityControl;
    if (typeof candidate === 'function') {
      return candidate as ComponentType<ApplicabilityControlProps>;
    }
  }
  return null;
}
