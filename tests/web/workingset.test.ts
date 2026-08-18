/**
 * Ticket 27 — the working set is app-wide, not a Library filter.
 *
 * Hermetic: jsdom, no network, no backend. What is pinned here is the
 * contract every screen depends on — where the value comes from on first
 * load, that it survives a reload, and that a link carries it.
 *
 * No JSX: elements are built with `createElement`, matching the other
 * frontend test files.
 */
import { render, screen, waitFor } from '../../web/node_modules/@testing-library/react';
import userEvent from '../../web/node_modules/@testing-library/user-event';
import { MemoryRouter, useLocation } from '../../web/node_modules/react-router-dom';
import { createElement } from '../../web/src/test-kit';

import {
  NO_PROJECT,
  PROJECT_PARAM,
  WorkingSetProvider,
  useWorkingSet,
} from '../../web/src/shell/workingSet';

const STORAGE_KEY = 'dsa.workingSet';

/** A screen: shows the working set, and can change it. */
function Probe({ label = 'A' }: { label?: string }) {
  const { project, setProject } = useWorkingSet();
  const location = useLocation();
  return createElement(
    'div',
    null,
    createElement('span', { 'data-testid': `project-${label}` }, project || '(none)'),
    createElement('span', { 'data-testid': `search-${label}` }, location.search),
    createElement(
      'button',
      { type: 'button', onClick: () => setProject('rx-chain') },
      `set from ${label}`,
    ),
    createElement(
      'button',
      { type: 'button', onClick: () => setProject(NO_PROJECT) },
      `clear from ${label}`,
    ),
  );
}

function renderApp(initialEntry = '/library') {
  return render(
    createElement(
      MemoryRouter,
      { initialEntries: [initialEntry] },
      createElement(
        WorkingSetProvider,
        null,
        createElement(Probe, { label: 'A' }),
        createElement(Probe, { label: 'B' }),
      ),
    ),
  );
}

beforeEach(() => {
  // Only this module's key: `clear()` would also wipe the theme and split-pane
  // keys other test files rely on, which is a cross-file flake waiting to
  // happen rather than isolation.
  globalThis.localStorage?.removeItem(STORAGE_KEY);
});

it('a project chosen on one screen is visible on the others', async () => {
  const user = userEvent.setup();
  renderApp();
  expect(screen.getByTestId('project-B')).toHaveTextContent('(none)');

  await user.click(screen.getByRole('button', { name: 'set from A' }));

  // Not "the Library knows": every consumer sees it, without a reload.
  expect(screen.getByTestId('project-A')).toHaveTextContent('rx-chain');
  expect(screen.getByTestId('project-B')).toHaveTextContent('rx-chain');
});

it('survives a reload', async () => {
  const user = userEvent.setup();
  const first = renderApp();
  await user.click(screen.getByRole('button', { name: 'set from A' }));
  first.unmount();

  renderApp();
  expect(screen.getByTestId('project-A')).toHaveTextContent('rx-chain');
});

it('a pasted link selects the project, overriding what was last open', () => {
  // The recipient of a link must see what the sender saw.
  globalThis.localStorage?.setItem(STORAGE_KEY, 'something-else');
  renderApp(`/library?${PROJECT_PARAM}=rx-chain`);
  expect(screen.getByTestId('project-A')).toHaveTextContent('rx-chain');
});

it('writes the choice into the URL so the link can be copied', async () => {
  const user = userEvent.setup();
  renderApp();
  await user.click(screen.getByRole('button', { name: 'set from A' }));
  await waitFor(() =>
    expect(screen.getByTestId('search-A').textContent).toContain(`${PROJECT_PARAM}=rx-chain`),
  );
});

it('clearing the working set removes it from the URL and from storage', async () => {
  const user = userEvent.setup();
  renderApp();
  await user.click(screen.getByRole('button', { name: 'set from A' }));
  await user.click(screen.getByRole('button', { name: 'clear from B' }));

  expect(screen.getByTestId('project-A')).toHaveTextContent('(none)');
  await waitFor(() =>
    expect(screen.getByTestId('search-A').textContent).not.toContain(PROJECT_PARAM),
  );
  expect(globalThis.localStorage?.getItem(STORAGE_KEY)).toBeNull();
});

it('a screen rendered outside the provider still works, with no working set', () => {
  // Several screens are tested in isolation; "no working set" is a real state
  // the application handles everywhere, so this falls back rather than throws.
  render(createElement(MemoryRouter, null, createElement(Probe, { label: 'solo' })));
  expect(screen.getByTestId('project-solo')).toHaveTextContent('(none)');
});
