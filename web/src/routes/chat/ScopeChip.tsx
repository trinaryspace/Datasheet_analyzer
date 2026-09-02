/**
 * The scope chip: the visible, editable half of ADR 0006.
 *
 * Auto-resolution is only defensible because the resolved scope is shown on
 * the answer and can be changed there. So this is a control, not a caption:
 * it renders the Part, Project or Family the answer came from and opens a
 * picker on click. Choosing a different scope re-asks the same question — the
 * caller does that; this component only reports the choice.
 *
 * **The picker is the only place a family scope can be chosen, and it may
 * offer nothing but what `GET /api/families` returns.** A family index tells a
 * designer "this section is identical in every member, so read it once"; a
 * wrong member makes that sentence a lie they cannot see. Membership is
 * therefore declared by a human in `registry/families.yaml`, and this
 * component never derives, completes or guesses a family name: the filter
 * narrows the declared list and can never add to it. When nothing is declared
 * the picker says so and names the command that declares one, rather than
 * leaving a silence a user could read as "families do not work here".
 */
import { useEffect, useMemo, useRef, useState } from 'react';

import { getFamilies, getParts, getProjects } from '../../api/client';
import type { ScopeRef } from '../../api/types';

export interface ScopeChipProps {
  scope: ScopeRef;
  /** How resolution decided; shown as the chip's tooltip. */
  matchedVia?: string;
  disabled?: boolean;
  onChange: (scope: ScopeRef) => void;
}

/** `part:AFE7950` — stable identity for a scope across the three lists. */
export function scopeKey(scope: ScopeRef): string {
  return `${scope.kind}:${scope.name}`;
}

/**
 * A scope as a person reads it — the mirror of `ScopeRef.label` in `models.py`.
 *
 * A part is its own name; anything else carries its kind, because `AFE795x`
 * beside `AFE7950` is otherwise indistinguishable from another part number,
 * and a family is a claim about several devices at once. Mirrored by hand from
 * the Python property so the CLI and this pane name a scope the same way.
 */
export function scopeLabel(scope: ScopeRef): string {
  return scope.kind === 'part' ? scope.name : `${scope.kind}: ${scope.name}`;
}

/** What the picker says about families, in both of its two states. */
export const FAMILIES_DECLARED_NOTE =
  'Families are declared by hand in registry/families.yaml; only confirmed ones are offered here.';
export const NO_FAMILIES_NOTE =
  'No families are declared. A family is never inferred — `dsa family suggest` proposes ' +
  'groupings, `dsa family confirm <NAME>` declares one.';

export function ScopeChip({ scope, matchedVia = '', disabled = false, onChange }: ScopeChipProps) {
  const [open, setOpen] = useState(false);
  const [choices, setChoices] = useState<ScopeRef[] | null>(null);
  const [loadError, setLoadError] = useState('');
  const [filter, setFilter] = useState('');
  const filterRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open || choices !== null) return;
    let live = true;
    void (async () => {
      try {
        // Families come from the server's declared list and from nowhere
        // else, so the picker cannot offer a grouping no human wrote down.
        const [parts, projects, families] = await Promise.all([
          getParts(),
          getProjects(),
          getFamilies(),
        ]);
        if (!live) return;
        setChoices([
          ...parts.parts.map((part): ScopeRef => ({ kind: 'part', name: part.part_number })),
          ...projects.projects.map(
            (project): ScopeRef => ({
              kind: 'project',
              name: project.name,
            }),
          ),
          ...families.families.map(
            (family): ScopeRef => ({
              kind: 'family',
              name: family.name,
            }),
          ),
        ]);
      } catch (error) {
        if (live) setLoadError(error instanceof Error ? error.message : 'could not load scopes');
      }
    })();
    return () => {
      live = false;
    };
  }, [open, choices]);

  useEffect(() => {
    if (open) filterRef.current?.focus();
  }, [open]);

  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const all = choices ?? [];
    if (!needle) return all;
    return all.filter((choice) => choice.name.toLowerCase().includes(needle));
  }, [choices, filter]);

  // Whether *any* family is declared, not whether one survives the filter: the
  // note explains the vocabulary and should not vanish because the user typed
  // a part number.
  const anyFamily = (choices ?? []).some((choice) => choice.kind === 'family');

  const pick = (next: ScopeRef) => {
    setOpen(false);
    setFilter('');
    if (scopeKey(next) !== scopeKey(scope)) onChange(next);
  };

  return (
    <div className="chat-scope">
      <button
        type="button"
        className="chat-scope-chip"
        data-scope-kind={scope.kind}
        data-scope-name={scope.name}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={matchedVia ? `Resolved by ${matchedVia}` : 'Change the scope of this answer'}
        onClick={() => setOpen((was) => !was)}
      >
        <span className="chat-scope-kind">{scope.kind}</span>
        <span className="chat-scope-name">{scope.name}</span>
      </button>
      {open ? (
        <div className="chat-scope-picker" role="dialog" aria-label="Change scope">
          <input
            ref={filterRef}
            type="text"
            className="chat-scope-filter"
            aria-label="Filter scopes"
            placeholder="Filter parts, projects and families"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Escape') setOpen(false);
            }}
          />
          {loadError ? <span className="chat-scope-error">{loadError}</span> : null}
          {choices === null && !loadError ? (
            <span className="chat-scope-loading">Loading scopes…</span>
          ) : null}
          <ul className="chat-scope-list" role="listbox" aria-label="Scopes">
            {visible.map((choice) => (
              <li key={scopeKey(choice)} role="none">
                <button
                  type="button"
                  role="option"
                  aria-selected={scopeKey(choice) === scopeKey(scope)}
                  className="chat-scope-option"
                  data-scope-kind={choice.kind}
                  onClick={() => pick(choice)}
                >
                  <span className="chat-scope-kind">{choice.kind}</span>
                  <span className="chat-scope-name">{choice.name}</span>
                </button>
              </li>
            ))}
          </ul>
          {choices !== null && !loadError ? (
            // Rendered in both states once the list has loaded. A picker that
            // silently listed no families reads as "this build has none of
            // that", when the truth is "nobody has declared one yet" — and the
            // command that changes it is the useful half of saying so.
            <p className="chat-scope-families-note" data-any-family={anyFamily ? 'true' : 'false'}>
              {anyFamily ? FAMILIES_DECLARED_NOTE : NO_FAMILIES_NOTE}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export default ScopeChip;
