/**
 * Test-only re-exports, so a test outside `web/` can reach `web/node_modules`.
 *
 * **This exists to work around a gap in the frozen scaffold**, not by
 * preference. `vite.config.ts` (ticket 00) points Vitest at
 * `../tests/web/**​/*.test.{ts,tsx}`, but npm installs into `web/node_modules`
 * and the repo root has no `node_modules`, so Node resolution walking up from
 * `tests/web/` never finds `react`, `react-router-dom` or
 * `@testing-library/react`. A test file there can only import **relative**
 * paths.
 *
 * Re-exporting them from inside `web/src` — where resolution works — closes
 * the gap without editing a file this ticket does not own. Nothing in the
 * application imports this module, so it never reaches a bundle.
 */
export { createElement, StrictMode } from 'react';
export type { ComponentType, ReactNode } from 'react';

export { MemoryRouter } from 'react-router-dom';

export {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
