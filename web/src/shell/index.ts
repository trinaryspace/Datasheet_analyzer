/**
 * Everything the other frontend tickets import from the shell.
 *
 * One barrel, so a screen writes `import { Button, ConfidenceBadge } from
 * '../../shell'` and never reaches into a file path that could be
 * reorganised. Deep imports (`'../../shell/primitives'`) also work and are
 * equally supported — the module layout is part of the contract too.
 */
export { Shell, RIGHT_PANE_ROUTE_ID, PdfPaneEmptyState } from './Shell';
export { default as ShellDefault } from './Shell';

export { SplitPane, SPLIT_STORAGE_KEY, SPLIT_MIN, SPLIT_MAX, SPLIT_STEP, clampSplit, readStoredSplit } from './SplitPane';
export type { SplitPaneProps } from './SplitPane';

export { ThemeToggle } from './ThemeToggle';
export type { ThemeToggleProps } from './ThemeToggle';
export { THEMES, THEME_STORAGE_KEY, applyTheme, nextTheme, readStoredTheme, useTheme } from './theme';
export type { Theme } from './theme';

export { STACK_BREAKPOINT_PX, STACK_QUERY, useMediaQuery, useStacked } from './useMediaQuery';

export { Button, Chip, Panel, Spinner, EmptyState, ErrorState } from './primitives';
export type {
  ButtonProps,
  ButtonVariant,
  ChipProps,
  PanelProps,
  SpinnerProps,
  EmptyStateProps,
  ErrorStateProps,
} from './primitives';

export { ConfidenceBadge, CONFIDENCE_VALUES, normalizeConfidence } from './ConfidenceBadge';
export type { Confidence, ConfidenceBadgeProps } from './ConfidenceBadge';

export {
  ApplicabilityControl,
  APPLICABILITY_KIND_LABELS,
  APPLICABILITY_USER_EVIDENCE,
  parsePartsList,
  validateApplicability,
} from './ApplicabilityControl';
export type { ApplicabilityControlProps } from './ApplicabilityControl';

export { useSSE } from './useSSE';
export type { SSEOpener, SSEStatus, UseSSEOptions, UseSSEResult } from './useSSE';
