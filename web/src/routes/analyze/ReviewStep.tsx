/**
 * Step two: review what inference proposed, before anything is built.
 *
 * One row per PDF, every inferred value editable in place, and the evidence
 * beside it — the evidence is what makes editing possible at all. A user
 * cannot judge `AFE79xx` from a confidence score; they can judge it from the
 * line it was read off. So both evidences are shown: the part number's, and
 * the applicability's own separate record.
 *
 * Applicability is edited through the shell's `ApplicabilityControl` (ticket
 * 16). This screen and the library screen (ticket 20) are written in
 * parallel and must not validate the same model two different ways, so the
 * control lives in the shell and neither screen owns a copy.
 */
import { useEffect, useMemo, useState } from 'react';

import { ApiError, getCategories, startAnalyze } from '../../api/client';
import type { Applicability, DocProposal, ScanOut } from '../../api/types';
import {
  ATTENTION_LABEL,
  attentionReason,
  defaultSelection,
  describeApplicability,
  displayName,
  groupByFolder,
  isCurrent,
  proposalKey,
  selectionKey,
  summarise,
} from './proposals';
import { getApplicabilityControl } from './shellPrimitives';

export interface ReviewStepProps {
  scan: ScanOut;
  onStarted: (runId: string, directory: string) => void;
  onBack: () => void;
  /** Content hashes this project has already rejected; those start unticked. */
  excluded?: readonly string[];
  /**
   * Persist the rejections. Called with every content hash left unticked that
   * the user could have ticked — a recursive walk re-proposes rejected files
   * on every scan, so an exclusion that did not stick would be re-made forever.
   */
  onExclude?: (hashes: string[]) => void;
}

function messageFor(error: unknown): string {
  if (error instanceof ApiError) return error.detail;
  if (error instanceof Error && error.message) return error.message;
  return 'The build could not be started.';
}

export default function ReviewStep({
  scan,
  onStarted,
  onBack,
  excluded = [],
  onExclude,
}: ReviewStepProps) {
  // Scan order is preserved for what gets posted; the sort below is display
  // only, so the payload stays recognisably the thing the server sent back.
  const [proposals, setProposals] = useState<DocProposal[]>(scan.proposals);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState('');

  const ApplicabilityControl = useMemo(() => getApplicabilityControl(), []);

  // The taxonomy, so a supporting document can be filed against a whole
  // category from the review rather than only from the Library afterwards.
  const [categories, setCategories] = useState<{ id: string; name: string }[]>([]);
  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const taxonomy = await getCategories();
        if (live) setCategories(taxonomy.categories);
      } catch {
        // A missing taxonomy hides the category option; it never blocks a build.
        if (live) setCategories([]);
      }
    })();
    return () => {
      live = false;
    };
  }, []);
  const folders = useMemo(() => groupByFolder(proposals), [proposals]);

  // Ticked rows. Seeded once from the scan so a later edit to a part number
  // does not silently re-tick something the user turned off.
  const [selected, setSelected] = useState<Set<string>>(() =>
    defaultSelection(scan.proposals, excluded),
  );
  const chosen = useMemo(
    () => proposals.filter((p) => selected.has(selectionKey(p))),
    [proposals, selected],
  );
  // A supporting document — an app note covering every amplifier — belongs to
  // a category and to no part, so demanding a part number for it would make it
  // unsubmittable. Only the kinds that describe part numbers need one.
  const needsPartNumber = (p: DocProposal) =>
    p.applicability.kind !== 'category' && p.applicability.kind !== 'all';
  const missingPartNumber = chosen.filter(
    (p) => needsPartNumber(p) && !p.part_number.trim(),
  ).length;
  const supporting = chosen.filter((p) => !needsPartNumber(p) && !p.part_number.trim()).length;

  function toggle(key: string, on: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });
  }

  function toggleFolder(rows: DocProposal[], on: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      for (const row of rows) {
        if (on) next.add(selectionKey(row));
        else next.delete(selectionKey(row));
      }
      return next;
    });
  }

  function update(key: string, patch: Partial<DocProposal>) {
    setProposals((current) =>
      current.map((proposal) =>
        proposalKey(proposal) === key ? { ...proposal, ...patch } : proposal,
      ),
    );
  }

  async function start() {
    setStarting(true);
    setError('');
    try {
      // Verbatim, and only what is ticked: whatever the user confirmed is what
      // the server builds.
      const started = await startAnalyze({ directory: scan.directory, proposals: chosen });
      // Everything left unticked is a rejection worth remembering — otherwise
      // the next recursive scan proposes all of it again.
      onExclude?.(
        proposals
          .filter((p) => !selected.has(selectionKey(p)) && p.content_hash)
          .map((p) => p.content_hash),
      );
      onStarted(started.run_id, scan.directory);
    } catch (caught) {
      setError(messageFor(caught));
    } finally {
      setStarting(false);
    }
  }

  if (scan.proposals.length === 0) {
    return (
      <section className="analyze-step analyze-review" aria-labelledby="analyze-review-heading">
        <h2 id="analyze-review-heading">Review</h2>
        <p className="analyze-empty">
          No PDFs were found directly inside {scan.directory}. Sub-directories are not
          scanned — point at the directory that holds the files.
        </p>
        <button type="button" onClick={onBack}>
          Pick another directory
        </button>
      </section>
    );
  }

  return (
    <section className="analyze-step analyze-review" aria-labelledby="analyze-review-heading">
      <h2 id="analyze-review-heading">Review {scan.count} document(s)</h2>
      <p className="analyze-hint">
        {scan.directory} — every value below is a proposal. Correct anything wrong; what
        you confirm is built exactly as it reads here.
      </p>

      {/* What will cost time, before the table rather than buried in it. */}
      {/* Not `role="status"`: it is rendered once with the table rather than
          announced, and a second live region competes with the real one. */}
      <p className="analyze-summary" data-testid="analyze-summary">
        {`${summarise(proposals)} — ${chosen.length} ticked`}
      </p>

      {ApplicabilityControl ? null : (
        <p role="alert" className="analyze-error">
          The shell&apos;s applicability control is unavailable, so applicability is shown
          read-only. It is deliberately not reimplemented here — one control, one set of
          rules.
        </p>
      )}

      {scan.skipped.length > 0 ? (
        <details className="analyze-skipped">
          <summary>{`${scan.skipped.length} folder(s) not searched`}</summary>
          <ul>
            {scan.skipped.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </details>
      ) : null}

      {folders.map((folder) => {
        const rows = folder.proposals;
        const allOn = rows.every((row) => selected.has(selectionKey(row)));
        const folderId = `folder-${folder.directory || 'root'}`;
        return (
          <section
            key={folder.directory}
            className="analyze-folder"
            data-directory={folder.directory}
            aria-labelledby={folderId}
          >
            <h3 className="analyze-folder-head">
              {/* One click to reject a whole `reference/` folder, which is the
                  reason grouping exists at all. */}
              <input
                type="checkbox"
                checked={allOn}
                disabled={starting}
                aria-label={`Include everything in ${folder.directory || 'the top level'}`}
                onChange={(event) => toggleFolder(rows, event.target.checked)}
              />
              <span id={folderId}>{folder.directory || 'top level'}</span>
              <span className="analyze-folder-count">{`${rows.length} document(s)`}</span>
            </h3>

            <ul className="analyze-rows">
              {rows.map((proposal) => {
                const key = proposalKey(proposal);
                const pick = selectionKey(proposal);
                const reason = attentionReason(proposal);
                const on = selected.has(pick);
                const applies = describeApplicability(proposal.applicability);
                return (
                  <li
                    key={key}
                    className={`analyze-row analyze-row--${reason}`}
                    data-attention={reason}
                    data-build-state={proposal.build_state}
                    data-selected={on}
                  >
                    {/* One line: tick, filename, part number, applicability,
                        state. Evidence is behind the disclosure, because it is
                        what you read for the one row that looks wrong — not for
                        all forty. A batch has to clear without scrolling. */}
                    <div className="analyze-row-head">
                      <input
                        type="checkbox"
                        className="analyze-row-pick"
                        checked={on}
                        disabled={starting}
                        aria-label={`Build ${displayName(proposal)}`}
                        onChange={(event) => toggle(pick, event.target.checked)}
                      />
                      <span className="analyze-row-name" title={displayName(proposal)}>
                        {displayName(proposal)}
                      </span>

                      <input
                        className="analyze-row-part"
                        id={`part-${key}`}
                        type="text"
                        value={proposal.part_number}
                        placeholder="part number"
                        aria-label={`Part number for ${displayName(proposal)}`}
                        disabled={starting || !on}
                        onChange={(event) => update(key, { part_number: event.target.value })}
                      />

                      <span className="analyze-row-applies" title={applies}>
                        {applies}
                      </span>

                      <span
                        className={`analyze-build-state analyze-build-state--${proposal.build_state}`}
                        title={proposal.build_reason}
                      >
                        {isCurrent(proposal) ? 'already built' : proposal.build_state}
                      </span>
                      {proposal.is_datasheet ? null : (
                        <span className="analyze-not-source" title="Unticked by default">
                          not a datasheet?
                        </span>
                      )}
                    </div>

                    <details className="analyze-row-detail">
                      <summary aria-label={`Evidence and applicability for ${displayName(proposal)}`}>
                        evidence &amp; applicability
                      </summary>

                      <p className="analyze-evidence">
                        <span className="analyze-evidence-label">Part evidence:</span>{' '}
                        {proposal.evidence || 'none recorded'}
                      </p>

                      <div className="analyze-field">
                        <span className="analyze-field-label" id={`applicability-label-${key}`}>
                          Applies to
                        </span>
                        {ApplicabilityControl ? (
                          <ApplicabilityControl
                            id={`applicability-${key}`}
                            label={`Applicability for ${displayName(proposal)}`}
                            value={proposal.applicability}
                            categories={categories}
                            disabled={starting || !on}
                            onChange={(next: Applicability) =>
                              update(key, { applicability: next })
                            }
                          />
                        ) : (
                          <span className="analyze-applicability-readonly">
                            {describeApplicability(proposal.applicability)}
                          </span>
                        )}
                        <p className="analyze-evidence">
                          <span className="analyze-evidence-label">
                            Applicability evidence:
                          </span>{' '}
                          {proposal.applicability.evidence || 'none recorded'}
                        </p>
                      </div>
                    </details>
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}

      {missingPartNumber > 0 ? (
        <p role="alert" className="analyze-error">
          {missingPartNumber} document(s) have no part number. Give each one a part number
          before building.
        </p>
      ) : null}

      {supporting > 0 ? (
        <p role="status" className="analyze-hint">
          {`${supporting} supporting document(s) will be filed, not built into a part of
            their own. Each joins a part's corpus the next time that part is built.`}
        </p>
      ) : null}

      {error ? (
        <p role="alert" className="analyze-error">
          {error}
        </p>
      ) : null}

      {starting ? (
        <p role="status" className="analyze-loading">
          Starting the build…
        </p>
      ) : null}

      <div className="analyze-actions">
        <button type="button" onClick={onBack} disabled={starting}>
          Back
        </button>
        <button
          type="button"
          onClick={() => void start()}
          disabled={starting || missingPartNumber > 0}
        >
          Build {scan.count} document(s)
        </button>
      </div>
    </section>
  );
}
