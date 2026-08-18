/**
 * The shared primitives every screen imports.
 *
 * They live in the shell rather than in any one screen because tickets 17–20
 * are written concurrently and none of them may import from another. A
 * primitive here is the only place a look — or a validation rule — can be
 * agreed on without coordination.
 *
 * All of them are thin: a class name, an accessible role, and the props the
 * screens actually need. No colour is decided here; `shell.css` maps every
 * class to a token.
 */
import type { ButtonHTMLAttributes, ReactNode } from 'react';

// --- Button -------------------------------------------------------------------

export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  /** Renders a spinner and disables the button; the label stays for context. */
  loading?: boolean;
}

/** A button. `type` defaults to `button` so it never submits a form by accident. */
export function Button({
  variant = 'secondary',
  loading = false,
  disabled,
  className,
  children,
  type = 'button',
  ...rest
}: ButtonProps) {
  const classes = ['button', `button--${variant}`, className].filter(Boolean).join(' ');
  return (
    <button
      {...rest}
      type={type}
      className={classes}
      disabled={disabled || loading}
      data-variant={variant}
      data-loading={loading ? 'true' : undefined}
      aria-busy={loading || undefined}
    >
      {loading ? <Spinner label="Working" /> : null}
      {children}
    </button>
  );
}

// --- Chip ---------------------------------------------------------------------

export interface ChipProps {
  label: string;
  /** Present ⇒ a remove affordance is rendered, named for screen readers. */
  onRemove?: () => void;
  selected?: boolean;
  title?: string;
}

/** A small, removable token — a label, a part number, a resolved scope. */
export function Chip({ label, onRemove, selected = false, title }: ChipProps) {
  return (
    <span className="chip" data-selected={selected ? 'true' : 'false'} title={title}>
      <span className="chip__label">{label}</span>
      {onRemove ? (
        <button
          type="button"
          className="chip__remove"
          aria-label={`Remove ${label}`}
          onClick={onRemove}
        >
          ×
        </button>
      ) : null}
    </span>
  );
}

// --- Panel --------------------------------------------------------------------

export interface PanelProps {
  title?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
}

/** A titled region. `<section>` + a heading, so the page has real landmarks. */
export function Panel({ title, actions, children, className }: PanelProps) {
  const classes = ['panel', className].filter(Boolean).join(' ');
  return (
    <section className={classes}>
      {title || actions ? (
        <header className="panel__head">
          {title ? <h2 className="panel__title">{title}</h2> : null}
          {actions ? <div className="panel__actions">{actions}</div> : null}
        </header>
      ) : null}
      <div className="panel__body">{children}</div>
    </section>
  );
}

// --- Spinner ------------------------------------------------------------------

export interface SpinnerProps {
  label?: string;
}

/** An indeterminate busy indicator. Announced, and stilled by reduced motion. */
export function Spinner({ label = 'Loading' }: SpinnerProps) {
  return <span className="spinner" role="status" aria-label={label} data-testid="spinner" />;
}

// --- EmptyState ---------------------------------------------------------------

export interface EmptyStateProps {
  title: string;
  /** Say what *will* appear here. A blank pane teaches nothing. */
  description?: ReactNode;
  action?: ReactNode;
}

/** The "nothing here yet" state, which always explains what would be here. */
export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="empty-state" data-testid="empty-state">
      <p className="empty-state__title">{title}</p>
      {description ? <p className="empty-state__body">{description}</p> : null}
      {action}
    </div>
  );
}

// --- ErrorState ---------------------------------------------------------------

export interface ErrorStateProps {
  title?: string;
  /** The server's own `ErrorOut.detail`. Render it; never replace it. */
  detail: string;
  onRetry?: () => void;
}

/**
 * A failure, shown with the server's own message.
 *
 * `client.ts` documents that `ApiError.detail` is written to be shown — the
 * scope refusal, the missing directory, the path a PDF moved from — so this
 * component never substitutes a generic string for it.
 */
export function ErrorState({ title = 'Something went wrong', detail, onRetry }: ErrorStateProps) {
  return (
    <div className="error-state" role="alert" data-testid="error-state">
      <p className="error-state__title">{title}</p>
      <p className="error-state__body">{detail}</p>
      {onRetry ? (
        <Button variant="secondary" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}
