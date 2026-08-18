/**
 * The rescan case: everything in this directory is already built and current.
 *
 * Pick → Review → Build is right the first time and wrong every time after.
 * The engine already skips this work — `app/jobs.py` calls the same
 * `batch.skip_reason` gate `dsa batch` uses — but until the scan reported it,
 * a user could not tell "nothing to do" from "three hours of work" and so
 * hesitated over a button that costs nothing. This screen is that answer.
 *
 * **Rebuild anyway is not a decoration.** The gate is conservative and can
 * still be satisfied by a corpus a user has reason to distrust. Without an
 * override the only remedy is deleting directories by hand, so the escape
 * stays — one click, and it forces the whole set.
 */
import { useMemo, useState } from 'react';

import { ApiError, startAnalyze } from '../../api/client';
import type { ScanOut } from '../../api/types';
import { displayName, summarise } from './proposals';

export interface UpToDateStepProps {
  scan: ScanOut;
  onStarted: (runId: string, directory: string) => void;
  onBack: () => void;
}

export default function UpToDateStep({ scan, onStarted, onBack }: UpToDateStepProps) {
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState('');

  const parts = useMemo(
    () => [...new Set(scan.proposals.map((p) => p.part_number).filter(Boolean))].sort(),
    [scan.proposals],
  );

  async function rebuild() {
    setStarting(true);
    setError('');
    try {
      const started = await startAnalyze({
        directory: scan.directory,
        proposals: scan.proposals,
      });
      onStarted(started.run_id, scan.directory);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.detail
          : 'The rebuild could not be started.',
      );
      setStarting(false);
    }
  }

  return (
    <section className="analyze-uptodate" aria-labelledby="analyze-uptodate-heading">
      <h2 id="analyze-uptodate-heading">Nothing to build</h2>

      <p className="analyze-uptodate-lead" role="status">
        {`All ${scan.count} ${scan.count === 1 ? 'document' : 'documents'} in this directory are already built and current.`}
      </p>
      <p className="analyze-uptodate-dir">{scan.directory}</p>

      {parts.length > 0 ? (
        <p className="analyze-uptodate-parts">
          {`Ready to ask about: ${parts.join(', ')}`}
        </p>
      ) : null}

      <details className="analyze-uptodate-detail">
        <summary>{summarise(scan.proposals)}</summary>
        <ul>
          {scan.proposals.map((proposal) => (
            <li key={proposal.pdf_path}>
              <span className="analyze-uptodate-file">{displayName(proposal)}</span>
              <span className="analyze-uptodate-reason">{proposal.build_reason}</span>
            </li>
          ))}
        </ul>
      </details>

      {error ? (
        <p role="alert" className="analyze-error">
          {error}
        </p>
      ) : null}

      <div className="analyze-actions">
        <button type="button" onClick={onBack} disabled={starting}>
          Choose another directory
        </button>
        <button type="button" onClick={() => void rebuild()} disabled={starting}>
          {starting ? 'Starting…' : 'Rebuild anyway'}
        </button>
      </div>
    </section>
  );
}
