/**
 * One library document: what it is, what it applies to, what it reaches, and
 * the two things a user may change about it.
 *
 * Labels are the only user-writable data in the whole application, so the
 * label editor is the part of this row that gets the affordances: add inline,
 * remove in one action, autocomplete from labels already in use. Applicability
 * is edited through the shell's control — never a local copy — and guarded by
 * `validateApplicability` before it is sent, because this row is what calls
 * `PATCH /api/library/{hash}`.
 */
import { useState } from 'react';
import type { ComponentType, FormEvent } from 'react';

import { patchLibraryDocument } from '../../api/client';
import type { Applicability, LibraryDocumentOut } from '../../api/types';
import type { ApplicabilityControlProps } from './shellPrimitives';
import {
  addLabel,
  describeApplicability,
  errorMessage,
  labelSuggestions,
  normalizeApplicability,
  rebuildOffer,
  removeLabel,
  validateApplicability,
} from './state';

export interface DocumentRowProps {
  document: LibraryDocumentOut;
  /** Every label in use, for autocomplete. */
  knownLabels: string[];
  /** The shell's control, or `null` when the shell is not built yet. */
  applicabilityControl: ComponentType<ApplicabilityControlProps> | null;
  /** Called with the server's own updated document after every successful patch. */
  onPatched: (next: LibraryDocumentOut) => void;
}

export function DocumentRow({
  document: entry,
  knownLabels,
  applicabilityControl: Control,
  onPatched,
}: DocumentRowProps) {
  // `null` means "unchanged from the server's copy", so a patch response
  // resets the editor without an effect chasing the prop.
  const [draft, setDraft] = useState<Applicability | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [labelQuery, setLabelQuery] = useState('');
  const [labelBusy, setLabelBusy] = useState(false);
  const [labelError, setLabelError] = useState('');

  const applicability = draft ?? entry.applicability;
  const unbuilt = new Set(entry.unbuilt_parts);
  const offer = rebuildOffer(entry.rebuild_needed);
  // Suggestions appear as the user types; the full set is always available
  // through the input's datalist, so the row is not a wall of buttons.
  const suggestions = labelQuery.trim()
    ? labelSuggestions(knownLabels, entry.labels, labelQuery)
    : [];
  const datalistId = `library-label-options-${entry.content_hash}`;

  async function patch(
    body: Parameters<typeof patchLibraryDocument>[1],
    onFailure: (message: string) => void,
    onSuccess: () => void,
  ): Promise<void> {
    try {
      const next = await patchLibraryDocument(entry.content_hash, body);
      onSuccess();
      onPatched(next);
    } catch (error) {
      onFailure(errorMessage(error, 'the change could not be saved'));
    }
  }

  async function saveApplicability(): Promise<void> {
    const candidate = normalizeApplicability(applicability);
    const invalid = validateApplicability(candidate);
    if (invalid) {
      // Blocked here: nothing is sent, so the server never sees an
      // applicability that cannot mean anything.
      setSaveError(invalid);
      return;
    }
    setSaveError('');
    setSaving(true);
    await patch({ applicability: candidate }, setSaveError, () => setDraft(null));
    setSaving(false);
  }

  async function commitLabels(labels: string[]): Promise<void> {
    setLabelError('');
    setLabelBusy(true);
    await patch({ labels }, setLabelError, () => setLabelQuery(''));
    setLabelBusy(false);
  }

  async function onAddLabel(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const next = addLabel(entry.labels, labelQuery);
    if (next === entry.labels) {
      setLabelError(labelQuery.trim() ? 'that label is already on this document' : '');
      return;
    }
    await commitLabels(next);
  }

  return (
    <article className="library-row" aria-label={`Document ${entry.filename}`}>
      <header>
        <h3>{entry.filename}</h3>
        <p className="library-row-meta">
          <span>{entry.part_number || 'unknown part'}</span>
          <span>{entry.doc_type || 'unknown type'}</span>
          <span>{entry.vendor || 'unknown vendor'}</span>
          <span>{entry.page_count} pages</span>
        </p>
      </header>

      <section aria-label={`Applicability of ${entry.filename}`}>
        <h4>Applicability</h4>
        <p className="library-applicability">{describeApplicability(entry.applicability)}</p>
        {entry.applicability.evidence ? (
          <p className="library-evidence">Evidence: {entry.applicability.evidence}</p>
        ) : null}
        {Control ? (
          <>
            <Control
              value={applicability}
              onChange={(next) => {
                setSaveError('');
                setDraft(next);
              }}
              id={`applicability-${entry.content_hash}`}
              label={`Applicability of ${entry.filename}`}
              disabled={saving}
            />
            <button
              type="button"
              onClick={() => void saveApplicability()}
              disabled={saving || draft === null}
            >
              {saving ? 'Saving…' : `Save applicability for ${entry.filename}`}
            </button>
          </>
        ) : (
          <p className="library-note">
            Applicability is read-only here until the shell&apos;s applicability control is
            installed; this screen will not keep a second copy of it.
          </p>
        )}
        {saveError ? <p role="alert">{saveError}</p> : null}
      </section>

      <section aria-label={`Labels on ${entry.filename}`}>
        <h4>Labels</h4>
        {entry.labels.length === 0 ? (
          <p className="library-empty-labels">No labels yet.</p>
        ) : (
          <ul className="library-labels">
            {entry.labels.map((label) => (
              <li key={label}>
                <span>{label}</span>
                <button
                  type="button"
                  disabled={labelBusy}
                  onClick={() => void commitLabels(removeLabel(entry.labels, label))}
                >
                  {`Remove label ${label} from ${entry.filename}`}
                </button>
              </li>
            ))}
          </ul>
        )}
        <form onSubmit={(event) => void onAddLabel(event)}>
          <input
            type="text"
            value={labelQuery}
            list={datalistId}
            aria-label={`Add a label to ${entry.filename}`}
            placeholder="reviewed, thermal, jesd204…"
            disabled={labelBusy}
            onChange={(event) => {
              setLabelError('');
              setLabelQuery(event.target.value);
            }}
          />
          <datalist id={datalistId}>
            {labelSuggestions(knownLabels, entry.labels, '', 100).map((label) => (
              <option key={label} value={label} />
            ))}
          </datalist>
          <button type="submit" disabled={labelBusy || !labelQuery.trim()}>
            {`Add label to ${entry.filename}`}
          </button>
        </form>
        {suggestions.length > 0 ? (
          <ul aria-label={`Label suggestions for ${entry.filename}`}>
            {suggestions.map((label) => (
              <li key={label}>
                <button
                  type="button"
                  disabled={labelBusy}
                  onClick={() => void commitLabels(addLabel(entry.labels, label))}
                >
                  {`Apply label ${label} to ${entry.filename}`}
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        {labelError ? <p role="alert">{labelError}</p> : null}
      </section>

      <section aria-label={`Parts reached by ${entry.filename}`}>
        <h4>Parts reached</h4>
        {entry.parts_reached.length === 0 ? (
          <p>This document reaches no parts.</p>
        ) : (
          <ul>
            {entry.parts_reached.map((part) => (
              <li key={part}>
                <span>{part}</span>
                {unbuilt.has(part) ? <span className="library-unbuilt"> — unbuilt</span> : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      {offer ? (
        <p className="library-offer" role="status">
          {offer}
        </p>
      ) : null}
    </article>
  );
}

export default DocumentRow;
