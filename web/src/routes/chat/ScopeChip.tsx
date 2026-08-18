/**
 * The scope chip: the visible, editable half of ADR 0006.
 *
 * Auto-resolution is only defensible because the resolved scope is shown on
 * the answer and can be changed there. So this is a control, not a caption:
 * it renders the Part or Project the answer came from and opens a picker on
 * click. Choosing a different scope re-asks the same question — the caller
 * does that; this component only reports the choice.
 */
import { useEffect, useMemo, useRef, useState } from 'react';

import { getParts, getProjects } from '../../api/client';
import type { ScopeRef } from '../../api/types';

export interface ScopeChipProps {
  scope: ScopeRef;
  /** How resolution decided; shown as the chip's tooltip. */
  matchedVia?: string;
  disabled?: boolean;
  onChange: (scope: ScopeRef) => void;
}

/** `part:AFE7950` — stable identity for a scope across two lists. */
export function scopeKey(scope: ScopeRef): string {
  return `${scope.kind}:${scope.name}`;
}

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
        const [parts, projects] = await Promise.all([getParts(), getProjects()]);
        if (!live) return;
        setChoices([
          ...parts.parts.map((part): ScopeRef => ({ kind: 'part', name: part.part_number })),
          ...projects.projects.map((project): ScopeRef => ({
            kind: 'project',
            name: project.name,
          })),
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
            placeholder="Filter parts and projects"
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
                  onClick={() => pick(choice)}
                >
                  <span className="chat-scope-kind">{choice.kind}</span>
                  <span className="chat-scope-name">{choice.name}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export default ScopeChip;
