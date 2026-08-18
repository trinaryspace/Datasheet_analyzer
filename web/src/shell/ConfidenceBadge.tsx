/**
 * The confidence grade a retrieval record carries, rendered.
 *
 * The four values are exactly what `retrieve/results.py` computes —
 * `high | medium | low | unknown`, with `CONFIDENCE_UNKNOWN = "unknown"` as
 * the honest fallback — and anything else normalizes to `unknown` rather than
 * inventing a fifth state.
 *
 * `low` is deliberately the loudest badge on the screen. A low-confidence
 * spec is the exact case where the user should stop reading the answer and
 * open the page, so it gets a solid fill, a border, a marker glyph and a
 * spoken hint, not a quieter pastel than `medium`.
 */

/** The grades `retrieve/` produces. */
export type Confidence = 'high' | 'medium' | 'low' | 'unknown';

/** Every grade, in descending order of trust. */
export const CONFIDENCE_VALUES: Confidence[] = ['high', 'medium', 'low', 'unknown'];

/** Anything unrecognised — blank, `null`, a typo — is `unknown`, never guessed. */
export function normalizeConfidence(value: string | null | undefined): Confidence {
  const text = (value ?? '').trim().toLowerCase();
  return (CONFIDENCE_VALUES as string[]).includes(text) ? (text as Confidence) : 'unknown';
}

const HINTS: Record<Confidence, string> = {
  high: 'High confidence',
  medium: 'Medium confidence',
  low: 'Low confidence — open the page and read the row',
  unknown: 'Confidence not recorded',
};

export interface ConfidenceBadgeProps {
  confidence: string | null | undefined;
  className?: string;
}

/** A badge naming the grade, loud when the grade is `low`. */
export function ConfidenceBadge({ confidence, className }: ConfidenceBadgeProps) {
  const grade = normalizeConfidence(confidence);
  const loud = grade === 'low';
  const classes = ['confidence-badge', `confidence-badge--${grade}`, className]
    .filter(Boolean)
    .join(' ');
  return (
    <span
      className={classes}
      data-confidence={grade}
      data-loud={loud ? 'true' : 'false'}
      title={HINTS[grade]}
      aria-label={HINTS[grade]}
      data-testid="confidence-badge"
    >
      {loud ? (
        <span className="confidence-badge__mark" aria-hidden="true">
          !
        </span>
      ) : null}
      <span className="confidence-badge__text">{grade}</span>
    </span>
  );
}

export default ConfidenceBadge;
