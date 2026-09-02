/**
 * A document's upstream freshness, rendered.
 *
 * The reading itself is `describeRevision` in `state.ts`, mirrored by hand
 * from `staleness.banner_text`; this file only draws it. The drawing carries
 * one rule of its own, and it is the whole reason the component exists:
 *
 * **`unknown` must not be a quiet tick.** Every corpus in this repo currently
 * reads `unknown`, because nothing has ever been checked against real upstream
 * bytes, and a badge that rendered that as a neutral grey dot beside "current"
 * would let a reader take "nobody looked" for "still good". So `unknown` gets
 * the warning glyph, the warning colours, and the words "not checked" — the
 * same treatment `stale` gets, differing only in what it says. `current` is
 * the *only* state that is drawn as a confirmation, and even then it is a
 * claim with a date attached, printed in the tooltip.
 *
 * Shaped like the shell's `ConfidenceBadge` — data attributes for the state,
 * one title and one accessible name carrying the whole sentence, a marker
 * glyph for the loud case — so the two badges read as the same kind of object
 * on a screen that shows both.
 */
import type { LibraryDocumentOut, RevisionState } from '../../api/types';
import { describeRevision, worstRevision } from './state';

export interface RevisionBadgeProps {
  /** One document's reading. Pass this or `documents`, not both. */
  state?: RevisionState | null;
  /** A part's documents: the badge shows the least fresh of them. */
  documents?: LibraryDocumentOut[];
  /** Named in the accessible label, so a row of badges is distinguishable. */
  subject?: string;
  className?: string;
}

/** `⚠` when the reading is something to act on, `✓` when it is a confirmation. */
export function revisionMarker(warns: boolean): string {
  return warns ? '⚠' : '✓';
}

export function RevisionBadge({ state, documents, subject, className }: RevisionBadgeProps) {
  const reading = documents ? worstRevision(documents) : describeRevision(state);
  const classes = [
    'revision-badge',
    `revision-badge--${reading.staleness}`,
    reading.warns ? 'revision-badge--warns' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');
  const spoken = subject ? `${subject}: ${reading.detail}` : reading.detail;

  return (
    <span
      className={classes}
      data-testid="revision-badge"
      data-staleness={reading.staleness}
      data-warns={reading.warns ? 'true' : 'false'}
      title={spoken}
      aria-label={spoken}
    >
      <span className="revision-badge__mark" aria-hidden="true">
        {revisionMarker(reading.warns)}
      </span>
      <span className="revision-badge__text">{reading.label}</span>
    </span>
  );
}

export default RevisionBadge;
