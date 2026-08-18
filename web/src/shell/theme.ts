/**
 * Theme state: three values, one stamp, one storage key.
 *
 * `system` means *no* `data-theme` attribute, so `prefers-color-scheme` in
 * `tokens.css` decides. `light` and `dark` stamp the attribute, and because
 * the dark media block is guarded with `:root:not([data-theme='light'])` the
 * stamp wins in **both** directions — a user on a dark OS can force light,
 * and a user on a light OS can force dark.
 */
import { useCallback, useEffect, useState } from 'react';

/** The three states of the toggle. `system` is the default. */
export type Theme = 'light' | 'dark' | 'system';

/** Every legal value, in toggle order. */
export const THEMES: Theme[] = ['light', 'dark', 'system'];

/** `localStorage` key. Namespaced so the app never collides with a host page. */
export const THEME_STORAGE_KEY = 'dsa.theme';

function isTheme(value: unknown): value is Theme {
  return value === 'light' || value === 'dark' || value === 'system';
}

/** The stored choice, or `system` when nothing legible is stored. */
export function readStoredTheme(storage: Storage | undefined = safeStorage()): Theme {
  try {
    const raw = storage?.getItem(THEME_STORAGE_KEY);
    return isTheme(raw) ? raw : 'system';
  } catch {
    return 'system';
  }
}

/** Stamp (or clear) `data-theme` on the document element. */
export function applyTheme(theme: Theme, root: HTMLElement | null = documentRoot()): void {
  if (!root) return;
  if (theme === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', theme);
}

function documentRoot(): HTMLElement | null {
  return typeof document === 'undefined' ? null : document.documentElement;
}

function safeStorage(): Storage | undefined {
  try {
    return typeof localStorage === 'undefined' ? undefined : localStorage;
  } catch {
    return undefined;
  }
}

/** The next theme in the cycle: light → dark → system → light. */
export function nextTheme(theme: Theme): Theme {
  const index = THEMES.indexOf(theme);
  return THEMES[(index + 1) % THEMES.length] as Theme;
}

/** Read/write the theme, stamping the document and persisting the choice. */
export function useTheme(): { theme: Theme; setTheme: (theme: Theme) => void } {
  const [theme, setThemeState] = useState<Theme>(() => readStoredTheme());

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    applyTheme(next);
    try {
      safeStorage()?.setItem(THEME_STORAGE_KEY, next);
    } catch {
      /* a browser with storage disabled still gets a working toggle */
    }
  }, []);

  return { theme, setTheme };
}
