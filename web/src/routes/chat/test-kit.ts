/**
 * Test-only re-exports for `tests/web/chat.test.ts`.
 *
 * Contract gap, worked around rather than fixed: `vite.config.ts` includes
 * `../tests/web/**` in the test glob, but the repo's `node_modules` lives
 * under `web/`, so a bare `import '@testing-library/react'` from a file in
 * `tests/web/` resolves against `tests/` and fails — and `@types/node` is not
 * installed, so `node:fs` is not available to that file either. Both are
 * ticket 00's files, so neither is touched here.
 *
 * Everything a test outside the Vite root needs therefore goes through this
 * module, which lives inside the root and resolves normally. It is imported
 * only by tests; no route module imports it, so it never reaches a bundle.
 */
export { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
export { default as userEvent } from '@testing-library/user-event';
export { createElement } from 'react';
export type { ReactNode } from 'react';
export { MemoryRouter, useLocation } from 'react-router-dom';

/**
 * Every source file of the chat pane, as text.
 *
 * The pane must not import the PDF pane — the two stay independently testable
 * only while neither knows the other exists — and that is a property of the
 * source, so a test reads the source. `import.meta.glob` is used rather than
 * `node:fs` because the raw text is resolved by Vite at transform time and
 * needs no Node typings.
 */
export function chatSourceFiles(): Record<string, string> {
  return import.meta.glob<string>('./*.{ts,tsx}', {
    query: '?raw',
    import: 'default',
    eager: true,
  });
}
