/**
 * `matchMedia` as a hook, defensively.
 *
 * jsdom and older browsers expose `matchMedia` inconsistently (sometimes
 * absent, sometimes with only the deprecated `addListener`), so every access
 * is guarded. A missing `matchMedia` reports `false`, which for the stacking
 * query means "wide" — the two-pane layout, the correct default.
 */
import { useEffect, useState } from 'react';

/**
 * The width at or below which the panes stack.
 *
 * Mirrors `--breakpoint-stack` in `tokens.css`; `shell.test.ts` asserts the
 * two agree, because a JS/CSS breakpoint that drifts produces a layout with a
 * hidden divider and an un-resizable pane.
 */
export const STACK_BREAKPOINT_PX = 720;

/** The media query the shell stacks on. */
export const STACK_QUERY = `(max-width: ${STACK_BREAKPOINT_PX}px)`;

function matches(query: string): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
  try {
    return window.matchMedia(query).matches;
  } catch {
    return false;
  }
}

/** True while `query` matches; re-renders when it changes. */
export function useMediaQuery(query: string): boolean {
  const [active, setActive] = useState(() => matches(query));

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    let list: MediaQueryList;
    try {
      list = window.matchMedia(query);
    } catch {
      return;
    }
    const onChange = () => setActive(list.matches);
    onChange();
    if (typeof list.addEventListener === 'function') {
      list.addEventListener('change', onChange);
      return () => list.removeEventListener('change', onChange);
    }
    if (typeof list.addListener === 'function') {
      list.addListener(onChange);
      return () => list.removeListener?.(onChange);
    }
    return;
  }, [query]);

  return active;
}

/** True when the window is narrow enough that the panes must stack. */
export function useStacked(): boolean {
  return useMediaQuery(STACK_QUERY);
}
