/**
 * Light / Dark / System, as three pressable buttons.
 *
 * A three-state control rather than a two-state switch because "follow the
 * OS" is a real choice and not the absence of one — and because the explicit
 * states must beat the OS in **both** directions, which a boolean cannot say.
 */
import { THEMES, useTheme } from './theme';
import type { Theme } from './theme';

const LABELS: Record<Theme, string> = {
  light: 'Light',
  dark: 'Dark',
  system: 'System',
};

export interface ThemeToggleProps {
  /** Supply to drive the control from outside; otherwise it owns its state. */
  theme?: Theme;
  onChange?: (theme: Theme) => void;
}

export function ThemeToggle({ theme, onChange }: ThemeToggleProps = {}) {
  const own = useTheme();
  const current = theme ?? own.theme;
  const set = onChange ?? own.setTheme;
  return (
    <div className="theme-toggle" role="group" aria-label="Colour theme" data-testid="theme-toggle">
      {THEMES.map((option) => (
        <button
          key={option}
          type="button"
          aria-pressed={current === option}
          onClick={() => set(option)}
        >
          {LABELS[option]}
        </button>
      ))}
    </div>
  );
}

export default ThemeToggle;
