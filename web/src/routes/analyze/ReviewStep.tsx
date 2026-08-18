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
import { useMemo, useState } from 'react';

import { ApiError, startAnalyze } from '../../api/client';
import type { Applicability, DocProposal, ScanOut } from '../../api/types';
import {
  ATTENTION_LABEL,
  attentionReason,
  describeApplicability,
  displayName,
  proposalKey,
  sortProposals,
} from './proposals';
import { getApplicabilityControl } from './shellPrimitives';

export interface ReviewStepProps {
  scan: ScanOut;
  onStarted: (runId: string, directory: string) => void;
  onBack: () => void;
}

function messageFor(error: unknown): string {
  if (error instanceof ApiError) return error.detail;
  if (error instanceof Error && error.message) return error.message;
  return 'The build could not be started.';
}

export default function ReviewStep({ scan, onStarted, onBack }: ReviewStepProps) {
  // Scan order is preserved for what gets posted; the sort below is display
  // only, so the payload stays recognisably the thing the server sent back.
  const [proposals, setProposals] = useState<DocProposal[]>(scan.proposals);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState('');

  const ApplicabilityControl = useMemo(() => getApplicabilityControl(), []);
  const rows = useMemo(() => sortProposals(proposals), [proposals]);
  const missingPartNumber = proposals.filter((p) => !p.part_number.trim()).length;

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
      // Verbatim: whatever the user confirmed is what the server builds.
      const started = await startAnalyze({ directory: scan.directory, proposals });
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

      {ApplicabilityControl ? null : (
        <p role="alert" className="analyze-error">
          The shell&apos;s applicability control is unavailable, so applicability is shown
          read-only. It is deliberately not reimplemented here — one control, one set of
          rules.
        </p>
      )}

      <ul className="analyze-rows">
        {rows.map((proposal) => {
          const key = proposalKey(proposal);
          const reason = attentionReason(proposal);
          return (
            <li key={key} className={`analyze-row analyze-row--${reason}`} data-attention={reason}>
              <h3 className="analyze-row-name">{displayName(proposal)}</h3>
              <span className="analyze-row-badge">{ATTENTION_LABEL[reason]}</span>

              <div className="analyze-field">
                <label htmlFor={`part-${key}`}>Part number</label>
                <input
                  id={`part-${key}`}
                  type="text"
                  value={proposal.part_number}
                  disabled={starting}
                  onChange={(event) => update(key, { part_number: event.target.value })}
                />
                <p className="analyze-evidence">
                  <span className="analyze-evidence-label">Part evidence:</span>{' '}
                  {proposal.evidence || 'none recorded'}
                </p>
              </div>

              <div className="analyze-field">
                <span className="analyze-field-label" id={`applicability-label-${key}`}>
                  Applies to
                </span>
                {ApplicabilityControl ? (
                  <ApplicabilityControl
                    id={`applicability-${key}`}
                    label={`Applicability for ${displayName(proposal)}`}
                    value={proposal.applicability}
                    disabled={starting}
                    onChange={(next: Applicability) => update(key, { applicability: next })}
                  />
                ) : (
                  <span className="analyze-applicability-readonly">
                    {describeApplicability(proposal.applicability)}
                  </span>
                )}
                <p className="analyze-evidence">
                  <span className="analyze-evidence-label">Applicability evidence:</span>{' '}
                  {proposal.applicability.evidence || 'none recorded'}
                </p>
              </div>
            </li>
          );
        })}
      </ul>

      {missingPartNumber > 0 ? (
        <p role="alert" className="analyze-error">
          {missingPartNumber} document(s) have no part number. Give each one a part number
          before building.
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
