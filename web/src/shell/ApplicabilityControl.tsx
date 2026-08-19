/**
 * The three-way applicability editor, shared by the review screen (17) and
 * the library screen (20).
 *
 * It lives in the shell rather than in either screen on purpose. Both screens
 * edit applicability, both are written concurrently, and neither may import
 * from the other — so a shared primitive is the only place the *same*
 * validation can exist. Two screens with two rules would let a document be
 * saved with an empty parts list from one page and rejected from the other.
 *
 * The control matches `models.Applicability` exactly: `parts`, `family`, or
 * `all`, with `parts` read only when `kind === 'parts'` and `family` only when
 * `kind === 'family'`. There is no fourth kind, and the two degenerate values
 * the model permits but the product must not send — an empty parts list, a
 * blank family — are blocked here, before they can reach the server.
 */
import { useEffect, useId, useRef, useState } from 'react';

import type { Applicability, ApplicabilityKind } from '../api/types';

/** `Applicability.evidence` written when a human, not inference, decided. */
export const APPLICABILITY_USER_EVIDENCE = 'set by user';

/**
 * Human labels for the four kinds, in the order the control renders them.
 *
 * `family` and `category` sit next to each other and are not the same thing: a
 * family is a pattern over part numbers read off the page (`AFE79xx`), a
 * category is a slot in the user's taxonomy (`amplifiers`). The labels say so,
 * because a control that made them look interchangeable would get them mixed.
 */
export const APPLICABILITY_KIND_LABELS: Record<ApplicabilityKind, string> = {
  parts: 'Specific parts',
  family: 'Family prefix',
  category: 'A whole category',
  all: 'All parts',
};

/**
 * Split a typed part list on commas, semicolons and whitespace.
 *
 * Duplicates are dropped case-insensitively — `AD9081` and `ad9081` are the
 * same part to `Applicability.covers()`, so they must be the same entry here.
 */
export function parsePartsList(text: string): string[] {
  const seen = new Set<string>();
  const parts: string[] = [];
  for (const token of text.split(/[\s,;]+/)) {
    const trimmed = token.trim();
    if (!trimmed) continue;
    const key = trimmed.toUpperCase();
    if (seen.has(key)) continue;
    seen.add(key);
    parts.push(trimmed);
  }
  return parts;
}

/** The message to show, or `null` when the value may be sent. */
export function validateApplicability(value: Applicability): string | null {
  if (value.kind === 'parts') {
    return parsePartsList(value.parts.join(' ')).length === 0
      ? 'Name at least one part number, or choose All parts.'
      : null;
  }
  if (value.kind === 'family') {
    return value.family.trim() === ''
      ? 'Enter a family prefix, such as AFE79xx, or choose All parts.'
      : null;
  }
  if (value.kind === 'category') {
    return value.category.trim() === ''
      ? 'Choose a category, or choose All parts.'
      : null;
  }
  return null;
}

function signature(value: Applicability): string {
  return JSON.stringify([value.kind, value.parts, value.family, value.category]);
}

export interface ApplicabilityControlProps {
  value: Applicability;
  /** Called **only** with a valid value; an invalid draft never escapes. */
  onChange: (next: Applicability) => void;
  /** Told why a draft was withheld, so a screen can disable its Save button. */
  onInvalid?: (message: string) => void;
  legend?: string;
  disabled?: boolean;
  /**
   * The taxonomy, for the `category` kind. Empty hides that option entirely —
   * a shelf with no categories should not offer to file a document into one.
   */
  categories?: readonly { id: string; name: string }[];
}

export function ApplicabilityControl({
  value,
  onChange,
  onInvalid,
  categories = [],
  legend = 'Applies to',
  disabled = false,
}: ApplicabilityControlProps) {
  const groupName = useId();
  const [kind, setKind] = useState<ApplicabilityKind>(value.kind);
  const [partsText, setPartsText] = useState(() => value.parts.join(', '));
  const [family, setFamily] = useState(value.family);
  const [category, setCategory] = useState(value.category);
  const [error, setError] = useState<string | null>(null);
  const lastEmitted = useRef(signature(value));

  // Re-sync only on a value that did not come from this control, so typing is
  // never interrupted by the parent echoing our own emission back.
  useEffect(() => {
    const incoming = signature(value);
    if (incoming === lastEmitted.current) return;
    lastEmitted.current = incoming;
    setKind(value.kind);
    setPartsText(value.parts.join(', '));
    setFamily(value.family);
    setCategory(value.category);
    setError(null);
  }, [value]);

  function emit(
    nextKind: ApplicabilityKind,
    nextPartsText: string,
    nextFamily: string,
    nextCategory: string = category,
  ): void {
    const candidate: Applicability = {
      kind: nextKind,
      parts: nextKind === 'parts' ? parsePartsList(nextPartsText) : [],
      family: nextKind === 'family' ? nextFamily.trim() : '',
      category: nextKind === 'category' ? nextCategory.trim() : '',
      evidence: APPLICABILITY_USER_EVIDENCE,
    };
    if (signature(candidate) === signature(value)) {
      candidate.evidence = value.evidence;
    }
    const message = validateApplicability(candidate);
    setError(message);
    if (message !== null) {
      onInvalid?.(message);
      return;
    }
    lastEmitted.current = signature(candidate);
    onChange(candidate);
  }

  const errorId = `${groupName}-error`;

  return (
    <fieldset className="applicability" disabled={disabled} data-testid="applicability">
      <legend className="applicability__legend">{legend}</legend>

      <div className="applicability__kinds">
        {(Object.keys(APPLICABILITY_KIND_LABELS) as ApplicabilityKind[])
          .filter((option) => option !== 'category' || categories.length > 0)
          .map((option) => (
          <label className="applicability__kind" key={option}>
            <input
              type="radio"
              name={groupName}
              value={option}
              checked={kind === option}
              onChange={() => {
                setKind(option);
                emit(option, partsText, family, category);
              }}
            />
            {APPLICABILITY_KIND_LABELS[option]}
          </label>
        ))}
      </div>

      {kind === 'parts' ? (
        <label className="applicability__field">
          Part numbers
          <input
            type="text"
            value={partsText}
            placeholder="AD9081, AD9082"
            aria-invalid={error !== null || undefined}
            aria-describedby={error ? errorId : undefined}
            onChange={(event) => {
              setPartsText(event.target.value);
              emit('parts', event.target.value, family, category);
            }}
          />
        </label>
      ) : null}

      {kind === 'category' ? (
        <label className="applicability__field">
          {/* A supporting document — a layout note that covers every
              amplifier — belongs to a category and to no part at all. */}
          Category
          <select
            value={category}
            aria-invalid={error !== null || undefined}
            aria-describedby={error ? errorId : undefined}
            onChange={(event) => {
              setCategory(event.target.value);
              emit('category', partsText, family, event.target.value);
            }}
          >
            <option value="">choose a category…</option>
            {categories.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      {kind === 'family' ? (
        <label className="applicability__field">
          {/* "Prefix", not "Family prefix": the radio above already carries
              that name, and two controls with one accessible name is a
              screen-reader ambiguity as much as a test-query one. */}
          Prefix
          <input
            type="text"
            value={family}
            placeholder="AFE79xx"
            aria-invalid={error !== null || undefined}
            aria-describedby={error ? errorId : undefined}
            onChange={(event) => {
              setFamily(event.target.value);
              emit('family', partsText, event.target.value, category);
            }}
          />
        </label>
      ) : null}

      {error ? (
        <p className="applicability__error" id={errorId} role="alert">
          {error}
        </p>
      ) : null}

      {value.evidence ? (
        <p className="applicability__evidence">Evidence: {value.evidence}</p>
      ) : null}
    </fieldset>
  );
}

export default ApplicabilityControl;
