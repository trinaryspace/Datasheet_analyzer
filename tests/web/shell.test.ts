/**
 * Ticket 16 — the app shell, the theme, the split pane and the shared
 * primitives.
 *
 * Written without JSX on purpose: the ticket's `Owns:` list names
 * `tests/web/shell.test.ts`, and a `.ts` file may not contain JSX, so every
 * element is built with `createElement`. `h` reads closely enough.
 *
 * Hermetic throughout — no network, no `EventSource`, no browser. `useSSE`
 * takes an injected opener, and the two stylesheets are read off disk so the
 * theme assertions test the shipped file rather than a copy of it.
 */
// Every import is relative: `web/node_modules` is not reachable from
// `tests/web/`, so `web/src/shell/testing.ts` re-exports React, the router and
// Testing Library from where resolution works. Vitest's own globals
// (`describe`, `it`, `expect`, `vi`) come from `globals: true`.
import {
  createElement as h,
  MemoryRouter,
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
} from '../../web/src/shell/testing';
import type { ComponentType, ReactNode } from '../../web/src/shell/testing';

import { Shell, RIGHT_PANE_ROUTE_ID } from '../../web/src/shell/Shell';
import {
  SplitPane,
  SPLIT_MAX,
  SPLIT_MIN,
  SPLIT_STORAGE_KEY,
  clampSplit,
  readStoredSplit,
} from '../../web/src/shell/SplitPane';
import { ThemeToggle } from '../../web/src/shell/ThemeToggle';
import { THEME_STORAGE_KEY, applyTheme, readStoredTheme } from '../../web/src/shell/theme';
import { STACK_BREAKPOINT_PX, STACK_QUERY } from '../../web/src/shell/useMediaQuery';
import {
  Button,
  Chip,
  EmptyState,
  ErrorState,
  Panel,
  Spinner,
} from '../../web/src/shell/primitives';
import { ConfidenceBadge, normalizeConfidence } from '../../web/src/shell/ConfidenceBadge';
import {
  ApplicabilityControl,
  APPLICABILITY_USER_EVIDENCE,
  parsePartsList,
  validateApplicability,
} from '../../web/src/shell/ApplicabilityControl';
import { useSSE } from '../../web/src/shell/useSSE';
import type { SSEOpener } from '../../web/src/shell/useSSE';
import * as shellBarrel from '../../web/src/shell';
import type { RouteDescriptor } from '../../web/src/App';
import type { Applicability } from '../../web/src/api/types';
import type { SSEHandlers } from '../../web/src/api/client';

// --- helpers ------------------------------------------------------------------

function renderRouted(node: ReactNode, entry = '/') {
  return render(h(MemoryRouter, { initialEntries: [entry] }, node));
}

function route(id: string, label: string, text: string): RouteDescriptor {
  const Component: ComponentType = () => h('p', null, text);
  return { id, path: `/${id}`, label, order: 100, Component };
}

function stubRect(element: HTMLElement, width: number, left = 0): void {
  element.getBoundingClientRect = () =>
    ({
      x: left,
      y: 0,
      left,
      top: 0,
      right: left + width,
      bottom: 600,
      width,
      height: 600,
      toJSON: () => ({}),
    }) as DOMRect;
}

afterEach(() => {
  cleanup();
  localStorage.clear();
  document.documentElement.removeAttribute('data-theme');
  vi.useRealTimers();
});

// --- design tokens --------------------------------------------------------------

/**
 * The stylesheets are read from disk rather than imported.
 *
 * `vite.config.ts` sets `test.css: false`, which makes *every* `.css` import
 * — `?raw` included — resolve to an empty module, so the only way to assert
 * against the shipped stylesheet is to read the file. The specifiers are held
 * in variables so TypeScript does not try to resolve `node:fs` (this repo
 * installs no `@types/node` for the frontend).
 */
const FS_MODULE = 'node:fs';
const URL_MODULE = 'node:url';
const fs = (await import(/* @vite-ignore */ FS_MODULE)) as {
  readFileSync: (path: string, encoding: string) => string;
};
const nodeUrl = (await import(/* @vite-ignore */ URL_MODULE)) as {
  fileURLToPath: (url: string) => string;
};

// `new URL(…, import.meta.url)` is rewritten by Vite's asset plugin into a
// served asset URL, so the repo root is derived from the module URL by hand.
const REPO_ROOT_URL = import.meta.url.replace(/\/tests\/web\/[^/]*$/, '');

function readStylesheet(name: string): string {
  return fs.readFileSync(
    nodeUrl.fileURLToPath(`${REPO_ROOT_URL}/web/src/styles/${name}`),
    'utf8',
  );
}

const tokensCss = readStylesheet('tokens.css');
const shellCss = readStylesheet('shell.css');

const strip = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, '');

function blockAt(css: string, selector: string): string {
  const start = css.indexOf(selector);
  if (start === -1) throw new Error(`selector not found: ${selector}`);
  const open = css.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < css.length; i += 1) {
    if (css[i] === '{') depth += 1;
    else if (css[i] === '}') {
      depth -= 1;
      if (depth === 0) return css.slice(open + 1, i);
    }
  }
  throw new Error(`unbalanced braces after ${selector}`);
}

function declarations(block: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const chunk of block.split(';')) {
    const match = /(--[\w-]+)\s*:\s*(.+)/s.exec(chunk);
    if (match) out[match[1] as string] = (match[2] as string).trim();
  }
  return out;
}

const tokens = strip(tokensCss);
const shellStyles = strip(shellCss);
const rootTokens = declarations(blockAt(tokens, ':root {'));
const mediaDark = declarations(blockAt(tokens, ':root:not([data-theme="light"])'));
const attrDark = declarations(blockAt(tokens, ':root[data-theme="dark"]'));

function channel(value: number): number {
  const c = value / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const clean = hex.trim().replace('#', '');
  const full =
    clean.length === 3
      ? clean
          .split('')
          .map((d) => d + d)
          .join('')
      : clean;
  const r = channel(Number.parseInt(full.slice(0, 2), 16));
  const g = channel(Number.parseInt(full.slice(2, 4), 16));
  const b = channel(Number.parseInt(full.slice(4, 6), 16));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(fg: string, bg: string): number {
  const a = luminance(fg);
  const b = luminance(bg);
  const [hi, lo] = a > b ? [a, b] : [b, a];
  return ((hi as number) + 0.05) / ((lo as number) + 0.05);
}

const CONTRAST_PAIRS: [string, string][] = [
  ['--color-fg', '--color-bg'],
  ['--color-fg', '--color-bg-raised'],
  ['--color-fg', '--color-bg-sunken'],
  ['--color-fg-muted', '--color-bg'],
  ['--color-fg-subtle', '--color-bg'],
  ['--color-accent-fg', '--color-accent'],
  ['--color-accent-soft-fg', '--color-accent-soft'],
  ['--color-danger-fg', '--color-danger'],
  ['--color-danger-soft-fg', '--color-danger-soft'],
  ['--color-warn-fg', '--color-warn'],
  ['--color-warn-soft-fg', '--color-warn-soft'],
  ['--color-ok-fg', '--color-ok'],
  ['--color-ok-soft-fg', '--color-ok-soft'],
  ['--color-confidence-high-fg', '--color-confidence-high-bg'],
  ['--color-confidence-medium-fg', '--color-confidence-medium-bg'],
  ['--color-confidence-low-fg', '--color-confidence-low-bg'],
  ['--color-confidence-unknown-fg', '--color-confidence-unknown-bg'],
];

describe('design tokens', () => {
  it('defines every colour token on bare :root', () => {
    const colours = Object.keys(rootTokens).filter((name) => name.startsWith('--color-'));
    expect(colours.length).toBeGreaterThan(20);
    expect(rootTokens['--color-bg']).toBeTruthy();
    expect(rootTokens['--color-fg']).toBeTruthy();
  });

  it('never defines a colour only inside a media query or [data-theme] block', () => {
    for (const name of [...Object.keys(mediaDark), ...Object.keys(attrDark)]) {
      expect(rootTokens, `${name} has no bare :root definition`).toHaveProperty(name);
    }
  });

  it('keeps the two dark palettes identical, so the toggle matches the OS', () => {
    expect(Object.keys(attrDark).sort()).toEqual(Object.keys(mediaDark).sort());
    for (const [name, value] of Object.entries(mediaDark)) {
      expect(attrDark[name], name).toBe(value);
    }
  });

  it('guards the dark media query so an explicit light choice wins', () => {
    expect(tokens).toContain('@media (prefers-color-scheme: dark)');
    expect(tokens).toContain(':root:not([data-theme="light"])');
    expect(tokens).toContain(':root[data-theme="dark"]');
    expect(tokens).toContain(':root[data-theme="light"]');
  });

  it.each(['light', 'dark-from-os', 'dark-from-toggle'])(
    'renders legible text in the %s palette',
    (palette) => {
      const overrides =
        palette === 'light' ? {} : palette === 'dark-from-os' ? mediaDark : attrDark;
      const resolved = { ...rootTokens, ...overrides };
      for (const [fg, bg] of CONTRAST_PAIRS) {
        const ratio = contrast(resolved[fg] as string, resolved[bg] as string);
        expect(ratio, `${fg} on ${bg} in ${palette}`).toBeGreaterThanOrEqual(4.5);
      }
    },
  );

  it('suppresses motion when the user asks for less of it', () => {
    expect(tokens).toContain('@media (prefers-reduced-motion: reduce)');
    const reduced = blockAt(tokens, '@media (prefers-reduced-motion: reduce)');
    expect(declarations(reduced)['--motion-base']).toBe('0ms');
    const shellReduced = blockAt(shellStyles, '@media (prefers-reduced-motion: reduce)');
    expect(shellReduced).toContain('transition-duration: 0.01ms !important');
    expect(shellReduced).toContain('animation-duration: 0.01ms !important');
  });

  it('keeps the CSS and JS stacking breakpoints in agreement', () => {
    expect(rootTokens['--breakpoint-stack']).toBe(`${STACK_BREAKPOINT_PX}px`);
    expect(STACK_QUERY).toBe(`(max-width: ${STACK_BREAKPOINT_PX}px)`);
  });
});

describe('component stylesheet', () => {
  it('uses no colour literal — every colour comes from a token', () => {
    const literals = shellStyles.match(/#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|oklch|lab)\(/g);
    expect(literals ?? []).toEqual([]);
    expect(shellStyles).not.toMatch(/:\s*(?:white|black|red|green|blue|grey|gray)\b/);
  });

  it('references only tokens that exist', () => {
    const allowed = new Set(['--split-left']);
    const referenced = shellStyles.match(/var\((--[\w-]+)/g) ?? [];
    for (const raw of referenced) {
      const name = raw.slice(4);
      if (allowed.has(name)) continue;
      expect(rootTokens, `${name} is used but never defined`).toHaveProperty(name);
    }
  });

  it('makes keyboard focus visible from one rule', () => {
    const focus = blockAt(shellStyles, ':focus-visible {');
    expect(focus).toContain('outline');
    expect(focus).toContain('var(--color-focus)');
  });
});

// --- split pane ------------------------------------------------------------------

describe('SplitPane', () => {
  it('renders both panes and a keyboard-operable divider', () => {
    renderRouted(h(SplitPane, { left: h('p', null, 'left side'), right: h('p', null, 'right side') }));
    expect(screen.getByText('left side')).toBeInTheDocument();
    expect(screen.getByText('right side')).toBeInTheDocument();
    const divider = screen.getByRole('separator', { name: 'Resize panes' });
    expect(divider).toHaveAttribute('aria-orientation', 'vertical');
    expect(divider).toHaveAttribute('tabindex', '0');
    divider.focus();
    expect(document.activeElement).toBe(divider);
  });

  it('drags to a new width and restores it after a reload', () => {
    const view = renderRouted(
      h(SplitPane, { left: h('p', null, 'left side'), right: h('p', null, 'right side') }),
    );
    stubRect(screen.getByTestId('split'), 1000);
    const divider = screen.getByTestId('split-divider');

    fireEvent.mouseDown(divider);
    fireEvent.mouseMove(window, { clientX: 300 });
    fireEvent.mouseUp(window);

    expect(divider).toHaveAttribute('aria-valuenow', '30');
    expect(screen.getByTestId('split').style.getPropertyValue('--split-left')).toBe('30%');
    expect(localStorage.getItem(SPLIT_STORAGE_KEY)).toBe('0.3');

    // "Reload": tear the tree down and mount a fresh one against the same storage.
    view.unmount();
    renderRouted(h(SplitPane, { left: h('p', null, 'left side'), right: h('p', null, 'right side') }));
    expect(screen.getByTestId('split-divider')).toHaveAttribute('aria-valuenow', '30');
    expect(readStoredSplit()).toBeCloseTo(0.3, 5);
  });

  it('moves with the arrow keys and clamps at both ends', () => {
    renderRouted(h(SplitPane, { left: h('p', null, 'L'), right: h('p', null, 'R') }));
    const divider = screen.getByTestId('split-divider');
    expect(divider).toHaveAttribute('aria-valuenow', '50');

    fireEvent.keyDown(divider, { key: 'ArrowLeft' });
    expect(divider).toHaveAttribute('aria-valuenow', '48');
    fireEvent.keyDown(divider, { key: 'ArrowRight' });
    fireEvent.keyDown(divider, { key: 'ArrowRight' });
    expect(divider).toHaveAttribute('aria-valuenow', '52');

    fireEvent.keyDown(divider, { key: 'Home' });
    expect(divider).toHaveAttribute('aria-valuenow', String(Math.round(SPLIT_MIN * 100)));
    fireEvent.keyDown(divider, { key: 'End' });
    expect(divider).toHaveAttribute('aria-valuenow', String(Math.round(SPLIT_MAX * 100)));

    expect(clampSplit(-3)).toBe(SPLIT_MIN);
    expect(clampSplit(9)).toBe(SPLIT_MAX);
    expect(clampSplit(Number.NaN)).toBe(0.5);
  });

  it('stacks below the breakpoint and keeps both panes usable', () => {
    const original = window.matchMedia;
    window.matchMedia = ((query: string) => ({
      matches: query === STACK_QUERY,
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
    try {
      renderRouted(
        h(SplitPane, { left: h('p', null, 'left side'), right: h('p', null, 'right side') }),
      );
      expect(screen.getByTestId('split')).toHaveAttribute('data-stacked', 'true');
      expect(screen.getByText('left side')).toBeInTheDocument();
      expect(screen.getByText('right side')).toBeInTheDocument();
      const divider = screen.getByTestId('split-divider');
      expect(divider).toHaveAttribute('aria-disabled', 'true');
      expect(divider).toHaveAttribute('tabindex', '-1');
      // A drag attempt in the stacked layout must not move anything.
      stubRect(screen.getByTestId('split'), 1000);
      fireEvent.mouseDown(divider);
      fireEvent.mouseMove(window, { clientX: 200 });
      expect(divider).toHaveAttribute('aria-valuenow', '50');
    } finally {
      window.matchMedia = original;
    }
  });
});

// --- theme -----------------------------------------------------------------------

describe('theme', () => {
  it('overrides the OS preference in both directions and back to system', () => {
    renderRouted(h(ThemeToggle));
    const dark = screen.getByRole('button', { name: 'Dark' });
    const light = screen.getByRole('button', { name: 'Light' });
    const system = screen.getByRole('button', { name: 'System' });

    fireEvent.click(dark);
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
    expect(dark).toHaveAttribute('aria-pressed', 'true');
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');

    fireEvent.click(light);
    expect(document.documentElement).toHaveAttribute('data-theme', 'light');
    expect(light).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(system);
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
    expect(readStoredTheme()).toBe('system');
  });

  it('restores the stored choice on the next load', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'dark');
    renderRouted(h(ThemeToggle));
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
    expect(screen.getByRole('button', { name: 'Dark' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('treats an unreadable stored value as system', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'chartreuse');
    expect(readStoredTheme()).toBe('system');
    applyTheme('system');
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });
});

// --- shell -----------------------------------------------------------------------

describe('Shell', () => {
  const routes = [
    route('analyze', 'Analyze', 'analyze screen'),
    route('library', 'Library', 'library screen'),
    route(RIGHT_PANE_ROUTE_ID, 'PDF', 'pdf pane'),
  ];

  it('navigates the discovered screens and keeps the PDF pane out of the nav', () => {
    renderRouted(h(Shell, { routes, children: h('p', null, 'route content') }), '/analyze');
    const nav = screen.getByRole('navigation', { name: 'Screens' });
    expect(nav).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Analyze' })).toHaveAttribute('href', '/analyze');
    expect(screen.getByRole('link', { name: 'Library' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'PDF' })).toBeNull();
    expect(screen.getByText('route content')).toBeInTheDocument();
  });

  it('shows an informative empty state in the right pane before a citation is clicked', () => {
    renderRouted(h(Shell, { routes, children: h('p', null, 'route content') }), '/analyze');
    const pane = screen.getByRole('region', { name: 'Source page' });
    expect(pane).toHaveTextContent('No page open yet');
    expect(pane).toHaveTextContent(/click a citation/i);
    expect(screen.queryByText('pdf pane')).toBeNull();
  });

  it('fills the right pane from the URL once a citation is clicked', () => {
    renderRouted(
      h(Shell, { routes, children: h('p', null, 'route content') }),
      '/analyze?doc=abc123&page=7&needle=VDD',
    );
    const pane = screen.getByRole('region', { name: 'Source page' });
    expect(pane).toHaveTextContent('pdf pane');
    expect(pane).not.toHaveTextContent('No page open yet');
  });

  it('says so honestly when no PDF screen is installed', () => {
    renderRouted(
      h(Shell, { routes: [route('chat', 'Chat', 'chat screen')], children: null }),
      '/chat?doc=abc123',
    );
    expect(screen.getByRole('region', { name: 'Source page' })).toHaveTextContent(
      /PDF pane is not installed/i,
    );
  });
});

// --- shared primitives -------------------------------------------------------------

describe('shared primitives', () => {
  it('exports every primitive the other frontend tickets import', () => {
    for (const name of [
      'Button',
      'Chip',
      'Panel',
      'Spinner',
      'EmptyState',
      'ErrorState',
      'ConfidenceBadge',
      'ApplicabilityControl',
      'useSSE',
      'SplitPane',
      'Shell',
      'ThemeToggle',
    ]) {
      expect(shellBarrel, name).toHaveProperty(name);
      expect(typeof (shellBarrel as Record<string, unknown>)[name]).toBe('function');
    }
  });

  it('renders a Button that is focusable, typed button, and busy while loading', () => {
    const onClick = vi.fn();
    const view = render(h(Button, { variant: 'primary', onClick }, 'Analyze'));
    const button = screen.getByRole('button', { name: 'Analyze' });
    expect(button).toHaveAttribute('type', 'button');
    button.focus();
    expect(document.activeElement).toBe(button);
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);

    view.rerender(h(Button, { variant: 'primary', onClick, loading: true }, 'Analyze'));
    const busy = screen.getByRole('button', { name: /Analyze/ });
    expect(busy).toBeDisabled();
    expect(busy).toHaveAttribute('aria-busy', 'true');
    fireEvent.click(busy);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('renders a Chip whose remove control names what it removes', () => {
    const onRemove = vi.fn();
    render(h(Chip, { label: 'jesd204', onRemove, selected: true }));
    expect(screen.getByText('jesd204')).toBeInTheDocument();
    const remove = screen.getByRole('button', { name: 'Remove jesd204' });
    remove.focus();
    expect(document.activeElement).toBe(remove);
    fireEvent.click(remove);
    expect(onRemove).toHaveBeenCalledTimes(1);
  });

  it('renders a Panel as a titled region', () => {
    render(h(Panel, { title: 'Review', actions: h(Button, null, 'Build') }, h('p', null, 'body')));
    expect(screen.getByRole('heading', { name: 'Review' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Build' })).toBeInTheDocument();
    expect(screen.getByText('body')).toBeInTheDocument();
  });

  it('renders a Spinner that announces itself', () => {
    render(h(Spinner, { label: 'Extracting' }));
    expect(screen.getByRole('status', { name: 'Extracting' })).toBeInTheDocument();
  });

  it('renders an EmptyState that says what will appear', () => {
    render(h(EmptyState, { title: 'No documents', description: 'Scan a directory to begin.' }));
    expect(screen.getByText('No documents')).toBeInTheDocument();
    expect(screen.getByText('Scan a directory to begin.')).toBeInTheDocument();
  });

  it("renders an ErrorState carrying the server's own detail", () => {
    const onRetry = vi.fn();
    render(h(ErrorState, { detail: 'directory does not exist: /nope', onRetry }));
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('directory does not exist: /nope');
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

// --- confidence -------------------------------------------------------------------

describe('ConfidenceBadge', () => {
  it.each(['high', 'medium', 'low', 'unknown'])('renders %s', (value) => {
    render(h(ConfidenceBadge, { confidence: value }));
    const badge = screen.getByTestId('confidence-badge');
    expect(badge).toHaveAttribute('data-confidence', value);
    expect(badge).toHaveTextContent(value);
    expect(badge.className).toContain(`confidence-badge--${value}`);
  });

  it('marks low distinctly and loudly', () => {
    render(h(ConfidenceBadge, { confidence: 'low' }));
    const low = screen.getByTestId('confidence-badge');
    expect(low).toHaveAttribute('data-loud', 'true');
    expect(low).toHaveAttribute('aria-label', expect.stringMatching(/open the page/i));
    expect(low.querySelector('.confidence-badge__mark')).not.toBeNull();

    cleanup();
    for (const quiet of ['high', 'medium', 'unknown']) {
      render(h(ConfidenceBadge, { confidence: quiet }));
      const badge = screen.getByTestId('confidence-badge');
      expect(badge, quiet).toHaveAttribute('data-loud', 'false');
      expect(badge.querySelector('.confidence-badge__mark')).toBeNull();
      cleanup();
    }
  });

  it('gives low a fill of its own, not a quieter pastel', () => {
    const low = rootTokens['--color-confidence-low-bg'] as string;
    for (const other of ['high', 'medium', 'unknown']) {
      expect(low).not.toBe(rootTokens[`--color-confidence-${other}-bg`]);
      expect(mediaDark['--color-confidence-low-bg']).not.toBe(
        mediaDark[`--color-confidence-${other}-bg`],
      );
    }
    expect(shellStyles).toContain('.confidence-badge--low');
  });

  it('normalizes anything unrecognised to unknown rather than guessing', () => {
    expect(normalizeConfidence('HIGH')).toBe('high');
    expect(normalizeConfidence('')).toBe('unknown');
    expect(normalizeConfidence(null)).toBe('unknown');
    expect(normalizeConfidence('probably')).toBe('unknown');
  });
});

// --- applicability -----------------------------------------------------------------

function applicability(patch: Partial<Applicability> = {}): Applicability {
  return { kind: 'all', parts: [], family: '', evidence: 'inferred', ...patch };
}

describe('ApplicabilityControl', () => {
  it('round-trips the parts kind', () => {
    const onChange = vi.fn();
    render(
      h(ApplicabilityControl, {
        value: applicability({ kind: 'parts', parts: ['AD9081', 'AD9082'] }),
        onChange,
      }),
    );
    expect(screen.getByRole('radio', { name: 'Specific parts' })).toBeChecked();
    const input = screen.getByLabelText('Part numbers') as HTMLInputElement;
    expect(input.value).toBe('AD9081, AD9082');

    fireEvent.change(input, { target: { value: 'AD9081, AD9082, AD9986' } });
    expect(onChange).toHaveBeenCalledWith({
      kind: 'parts',
      parts: ['AD9081', 'AD9082', 'AD9986'],
      family: '',
      evidence: APPLICABILITY_USER_EVIDENCE,
    });
  });

  it('round-trips the family kind', () => {
    const onChange = vi.fn();
    render(h(ApplicabilityControl, { value: applicability({ kind: 'family', family: 'AFE79xx' }), onChange }));
    const input = screen.getByLabelText('Prefix') as HTMLInputElement;
    expect(input.value).toBe('AFE79xx');

    fireEvent.change(input, { target: { value: 'AFE80xx' } });
    expect(onChange).toHaveBeenCalledWith({
      kind: 'family',
      parts: [],
      family: 'AFE80xx',
      evidence: APPLICABILITY_USER_EVIDENCE,
    });
  });

  it('round-trips the all kind', () => {
    const onChange = vi.fn();
    render(h(ApplicabilityControl, { value: applicability({ kind: 'family', family: 'AFE79xx' }), onChange }));
    fireEvent.click(screen.getByRole('radio', { name: 'All parts' }));
    expect(onChange).toHaveBeenCalledWith({
      kind: 'all',
      parts: [],
      family: '',
      evidence: APPLICABILITY_USER_EVIDENCE,
    });
    expect(screen.queryByLabelText('Prefix')).toBeNull();
  });

  it('blocks an empty parts list before it can reach the server', () => {
    const onChange = vi.fn();
    const onInvalid = vi.fn();
    render(
      h(ApplicabilityControl, {
        value: applicability({ kind: 'parts', parts: ['AD9081'] }),
        onChange,
        onInvalid,
      }),
    );
    fireEvent.change(screen.getByLabelText('Part numbers'), { target: { value: '   ' } });
    expect(onChange).not.toHaveBeenCalled();
    expect(onInvalid).toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(/at least one part number/i);
  });

  it('blocks a blank family before it can reach the server', () => {
    const onChange = vi.fn();
    render(
      h(ApplicabilityControl, {
        value: applicability({ kind: 'family', family: 'AFE79xx' }),
        onChange,
      }),
    );
    fireEvent.change(screen.getByLabelText('Prefix'), { target: { value: '  ' } });
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(/family prefix/i);
  });

  it('blocks switching to a kind whose value is not yet filled in', () => {
    const onChange = vi.fn();
    render(h(ApplicabilityControl, { value: applicability(), onChange }));
    fireEvent.click(screen.getByRole('radio', { name: 'Family prefix' }));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Prefix'), { target: { value: 'AFE79xx' } });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'family', family: 'AFE79xx' }),
    );
  });

  it('shows the evidence behind the current value', () => {
    render(
      h(ApplicabilityControl, {
        value: applicability({ evidence: 'fallback: no part token found' }),
        onChange: vi.fn(),
      }),
    );
    expect(screen.getByText(/fallback: no part token found/)).toBeInTheDocument();
  });

  it('validates and parses the same way for a caller that does it directly', () => {
    expect(parsePartsList(' AD9081 , ad9081;AD9082 ')).toEqual(['AD9081', 'AD9082']);
    expect(parsePartsList('   ')).toEqual([]);
    expect(validateApplicability(applicability())).toBeNull();
    expect(validateApplicability(applicability({ kind: 'parts' }))).toMatch(/at least one/i);
    expect(validateApplicability(applicability({ kind: 'family', family: ' ' }))).toMatch(
      /family prefix/i,
    );
    expect(
      validateApplicability(applicability({ kind: 'family', family: 'AFE79xx' })),
    ).toBeNull();
  });
});

// --- useSSE ---------------------------------------------------------------------------

interface FakeConnection {
  path: string;
  handlers: SSEHandlers;
  closed: boolean;
}

function fakeOpener(): { opener: SSEOpener; connections: FakeConnection[] } {
  const connections: FakeConnection[] = [];
  const opener: SSEOpener = (path, handlers) => {
    const connection: FakeConnection = { path, handlers, closed: false };
    connections.push(connection);
    return {
      close: () => {
        connection.closed = true;
      },
    };
  };
  return { opener, connections };
}

describe('useSSE', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it('opens once, forwards frames, and closes its connection on unmount', () => {
    const { opener, connections } = fakeOpener();
    const onEvent = vi.fn();
    const { result, unmount } = renderHook(() =>
      useSSE({ path: '/analyze/run-1/events', onEvent, open: opener }),
    );

    expect(connections).toHaveLength(1);
    expect(connections[0]?.path).toBe('/analyze/run-1/events');

    act(() => connections[0]?.handlers.onOpen?.());
    expect(result.current.status).toBe('open');

    act(() => connections[0]?.handlers.onEvent('job', '{"state":"done"}'));
    expect(onEvent).toHaveBeenCalledWith('job', '{"state":"done"}');

    unmount();
    expect(connections[0]?.closed).toBe(true);
  });

  it('reconnects after a drop and stops once unmounted', () => {
    const { opener, connections } = fakeOpener();
    const onError = vi.fn();
    const { result, unmount } = renderHook(() =>
      useSSE({
        path: '/analyze/run-1/events',
        onEvent: vi.fn(),
        onError,
        open: opener,
        reconnectDelayMs: 1000,
      }),
    );

    act(() => connections[0]?.handlers.onOpen?.());
    act(() => connections[0]?.handlers.onError?.(new Error('stream dropped')));

    expect(onError).toHaveBeenCalledTimes(1);
    expect(connections[0]?.closed).toBe(true);
    expect(result.current.status).toBe('reconnecting');
    expect(connections).toHaveLength(1);

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(connections).toHaveLength(2);
    expect(connections[1]?.path).toBe('/analyze/run-1/events');

    act(() => connections[1]?.handlers.onOpen?.());
    expect(result.current.status).toBe('open');
    expect(result.current.retries).toBe(0);

    unmount();
    expect(connections[1]?.closed).toBe(true);
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(connections).toHaveLength(2);
  });

  it('gives up after maxRetries instead of hammering a dead endpoint', () => {
    const { opener, connections } = fakeOpener();
    const { result } = renderHook(() =>
      useSSE({
        path: '/chat/s1/stream',
        onEvent: vi.fn(),
        open: opener,
        reconnectDelayMs: 10,
        maxRetries: 2,
      }),
    );

    for (let i = 0; i < 3; i += 1) {
      act(() => connections[connections.length - 1]?.handlers.onError?.(new Error('down')));
      act(() => {
        vi.advanceTimersByTime(1000);
      });
    }
    expect(connections).toHaveLength(3);
    expect(result.current.status).toBe('error');
  });

  it('opens nothing while disabled or without a path', () => {
    const { opener, connections } = fakeOpener();
    const { result, rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) =>
        useSSE({ path: enabled ? '/x' : null, onEvent: vi.fn(), open: opener, enabled }),
      { initialProps: { enabled: false } },
    );
    expect(connections).toHaveLength(0);
    expect(result.current.status).toBe('idle');

    rerender({ enabled: true });
    expect(connections).toHaveLength(1);
  });
});
