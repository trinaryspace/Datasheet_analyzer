/**
 * Typed re-exports for tests that live outside this package.
 *
 * **A scaffold gap, not a preference.** `vite.config.ts` points Vitest at
 * `../tests/web/**​/*.test.{ts,tsx}`, but npm installs into `web/node_modules`
 * and the repo root has no `node_modules`. Node resolution walking up from
 * `tests/web/` therefore never finds `react`, so a test file there can only
 * import **relative** paths — and `../../web/node_modules/react` resolves to
 * `index.js` with no adjacent declarations (React's types live in
 * `@types/react`, which TypeScript only attaches to the *bare* specifier).
 * Every frontend ticket hit this and worked around it separately: one with a
 * local re-export, one with a `@ts-ignore`, one with both.
 *
 * Importing through a module *inside* the package closes the gap for good:
 * here the bare specifier resolves, the types come with it, and the test
 * outside gets a plain relative import. Nothing in the application imports
 * this module, so it never reaches a bundle.
 *
 * `shell/testing.ts` is ticket 16's narrower version of the same idea, kept
 * as-is so its tests do not move; new call sites should use this one.
 */
export { Fragment, StrictMode, createElement, useState } from 'react';
export type {
  ComponentType,
  ReactElement,
  ReactNode,
} from 'react';

export {
  MemoryRouter,
  useLocation,
  useNavigate,
} from 'react-router-dom';

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
