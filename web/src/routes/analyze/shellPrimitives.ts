/**
 * The shell primitives this screen borrows, resolved without a static import.
 *
 * `ApplicabilityControl` belongs to ticket 16 (`web/src/shell/**`) and is
 * deliberately **not** reimplemented here: tickets 17 and 20 both edit
 * applicability, so a second copy would mean two validation rules for one
 * model. This module is the seam that lets the analyze screen use the shell's
 * control while remaining independently buildable and testable — exactly the
 * pattern `App.tsx` already uses to discover `shell/Shell.tsx`:
 * `import.meta.glob` resolves at build time and yields an empty record when
 * the directory does not exist yet, where a static `import` would be a hard
 * resolution error.
 *
 * Nothing here implements the control. When the shell is absent the screen
 * renders the applicability read-only and says why, because an editor that
 * validates differently from the shell's would be worse than no editor.
 */
import type { ComponentType } from 'react';

import type { Applicability } from '../../api/types';

/**
 * The props the shell's `ApplicabilityControl` is called with.
 *
 * Ticket 00 froze the `Applicability` model but not this component's
 * signature, so this is the contract the analyze screen codes against: a
 * controlled value plus a change handler, mirroring the model exactly. The
 * control owns its own validation (an empty parts list, a blank family).
 */
export interface ApplicabilityControlProps {
  value: Applicability;
  onChange: (next: Applicability) => void;
  /** Stable DOM id, so a row's control can be labelled and found. */
  id?: string;
  /** Accessible name for the control as a whole. */
  label?: string;
  disabled?: boolean;
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
