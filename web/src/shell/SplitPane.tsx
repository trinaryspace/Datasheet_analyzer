/**
 * The two-pane split that *is* the product: answer on the left, page on the
 * right, one draggable divider between them.
 *
 * Three behaviours are requirements rather than polish:
 *
 * - **The ratio persists.** An engineer settles on a width once and resents
 *   re-dragging it after every reload, so the fraction is written to
 *   `localStorage` and read back on mount.
 * - **The divider is keyboard-operable.** It is an ARIA window splitter
 *   (`role="separator"`, focusable, arrow keys move it), because a pointer is
 *   not the only way to resize a pane.
 * - **Below the breakpoint the panes stack** and the divider is withdrawn
 *   rather than shrunk to something undraggable.
 */
import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent, ReactNode } from 'react';

import { useStacked } from './useMediaQuery';

/** `localStorage` key holding the left pane's width as a fraction of the whole. */
export const SPLIT_STORAGE_KEY = 'dsa.split.left';

/** Neither pane may be squeezed past this; mirrors `--pane-min` / `--pane-max`. */
export const SPLIT_MIN = 0.18;
export const SPLIT_MAX = 0.82;

/** Arrow-key step, in fraction of the container's width. */
export const SPLIT_STEP = 0.02;

export interface SplitPaneProps {
  left: ReactNode;
  right: ReactNode;
  /** Accessible names for the two regions. */
  leftLabel?: string;
  rightLabel?: string;
  /** Overridable so two split panes can persist independently. */
  storageKey?: string;
  /** Used when nothing is stored. */
  defaultLeft?: number;
  /** Force the stacked layout; defaults to the `--breakpoint-stack` media query. */
  stacked?: boolean;
}

export function clampSplit(value: number): number {
  if (!Number.isFinite(value)) return 0.5;
  return Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, value));
}

function storage(): Storage | undefined {
  try {
    return typeof localStorage === 'undefined' ? undefined : localStorage;
  } catch {
    return undefined;
  }
}

/** The persisted fraction, or `fallback` when nothing legible is stored. */
export function readStoredSplit(key = SPLIT_STORAGE_KEY, fallback = 0.5): number {
  try {
    const raw = storage()?.getItem(key);
    if (raw === null || raw === undefined) return clampSplit(fallback);
    const parsed = Number.parseFloat(raw);
    return Number.isFinite(parsed) ? clampSplit(parsed) : clampSplit(fallback);
  } catch {
    return clampSplit(fallback);
  }
}

function writeStoredSplit(key: string, value: number): void {
  try {
    storage()?.setItem(key, String(value));
  } catch {
    /* storage disabled: the pane still drags, it just forgets */
  }
}

export function SplitPane({
  left,
  right,
  leftLabel = 'Conversation',
  rightLabel = 'Source page',
  storageKey = SPLIT_STORAGE_KEY,
  defaultLeft = 0.5,
  stacked,
}: SplitPaneProps) {
  const autoStacked = useStacked();
  const isStacked = stacked ?? autoStacked;
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [fraction, setFraction] = useState(() => readStoredSplit(storageKey, defaultLeft));
  const [dragging, setDragging] = useState(false);
  const leftId = useId();
  const rightId = useId();

  const commit = useCallback(
    (next: number) => {
      const clamped = clampSplit(next);
      setFraction(clamped);
      writeStoredSplit(storageKey, clamped);
    },
    [storageKey],
  );

  const fractionFromClientX = useCallback((clientX: number): number | null => {
    const box = containerRef.current?.getBoundingClientRect();
    if (!box || box.width <= 0) return null;
    return (clientX - box.left) / box.width;
  }, []);

  useEffect(() => {
    if (!dragging) return;
    const onMove = (event: MouseEvent) => {
      const next = fractionFromClientX(event.clientX);
      if (next !== null) commit(next);
    };
    const onUp = () => setDragging(false);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [dragging, commit, fractionFromClientX]);

  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    let next: number | null = null;
    if (event.key === 'ArrowLeft') next = fraction - SPLIT_STEP;
    else if (event.key === 'ArrowRight') next = fraction + SPLIT_STEP;
    else if (event.key === 'Home') next = SPLIT_MIN;
    else if (event.key === 'End') next = SPLIT_MAX;
    else if (event.key === 'Enter') next = 0.5;
    if (next === null) return;
    event.preventDefault();
    commit(next);
  };

  const percent = Math.round(fraction * 1000) / 10;

  return (
    <div
      className="split"
      ref={containerRef}
      data-testid="split"
      data-stacked={isStacked ? 'true' : 'false'}
      style={{ '--split-left': `${percent}%` } as CSSProperties}
    >
      <div className="split__pane split__pane--left" id={leftId} role="region" aria-label={leftLabel}>
        {left}
      </div>
      <div
        className="split__divider"
        role="separator"
        tabIndex={isStacked ? -1 : 0}
        aria-orientation="vertical"
        aria-label="Resize panes"
        aria-controls={`${leftId} ${rightId}`}
        aria-valuemin={Math.round(SPLIT_MIN * 100)}
        aria-valuemax={Math.round(SPLIT_MAX * 100)}
        aria-valuenow={Math.round(fraction * 100)}
        aria-valuetext={`${Math.round(fraction * 100)}% conversation`}
        aria-disabled={isStacked ? 'true' : undefined}
        data-dragging={dragging ? 'true' : 'false'}
        data-testid="split-divider"
        onMouseDown={(event) => {
          if (isStacked) return;
          event.preventDefault();
          setDragging(true);
        }}
        onKeyDown={isStacked ? undefined : onKeyDown}
        onDoubleClick={() => commit(0.5)}
      />
      <div
        className="split__pane split__pane--right"
        id={rightId}
        role="region"
        aria-label={rightLabel}
      >
        {right}
      </div>
    </div>
  );
}

export default SplitPane;
