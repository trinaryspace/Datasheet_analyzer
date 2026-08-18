/**
 * Step three: watch it build.
 *
 * One row per job, live from the run's SSE stream. Three behaviours matter
 * more than the layout:
 *
 * - a part reaching `done` gets its "Ask about this" link **immediately**,
 *   because a forty-PDF run must not block the first question;
 * - a failed job shows its error in its own row and nothing else stops;
 * - a dropped stream reconnects and re-renders from the snapshot the server
 *   sends on connect, so the rows never blank out.
 */
import { Link } from 'react-router-dom';

import type { AnalyzeJob } from '../../api/types';
import { basename } from './proposals';
import { STATE_LABEL, countByState, useAnalyzeRun } from './useAnalyzeRun';

export interface ProgressStepProps {
  runId: string;
  directory: string;
  onRestart: () => void;
}

/**
 * Where "Ask about this" goes.
 *
 * Cross-screen state travels in the URL rather than through an import, so
 * this screen never reaches into the chat pane (ticket 18). `part` is the
 * parameter name; ticket 00 froze only the `PDF_PARAM_*` names, so this one
 * is recorded as a contract gap.
 */
export function askUrl(partNumber: string): string {
  return `/chat?part=${encodeURIComponent(partNumber)}`;
}

function JobRow({ job }: { job: AnalyzeJob }) {
  const failed = job.state === 'failed';
  const label = job.detail || STATE_LABEL[job.state] || job.state;
  return (
    <li className={`analyze-job analyze-job--${job.state}`} data-state={job.state}>
      <span className="analyze-job-part">{job.part_number || '(no part number)'}</span>
      <span className="analyze-job-file">{basename(job.pdf_path)}</span>
      <span className="analyze-job-state">{STATE_LABEL[job.state] ?? job.state}</span>
      {failed ? (
        <span role="alert" className="analyze-job-error">
          {job.error || job.detail || 'This document failed.'}
        </span>
      ) : (
        <span className="analyze-job-detail">{label}</span>
      )}
      {job.state === 'done' && job.part_number ? (
        <Link className="analyze-job-ask" to={askUrl(job.part_number)}>
          Ask about {job.part_number}
        </Link>
      ) : null}
    </li>
  );
}

export default function ProgressStep({ runId, directory, onRestart }: ProgressStepProps) {
  const run = useAnalyzeRun(runId);
  const counts = countByState(run.jobs);
  const failed = counts.failed ?? 0;
  const finished = (counts.done ?? 0) + failed + (counts.skipped ?? 0);

  return (
    <section className="analyze-step analyze-progress" aria-labelledby="analyze-progress-heading">
      <h2 id="analyze-progress-heading">Building {run.directory || directory}</h2>
      <p className="analyze-hint">
        {finished} of {run.jobs.length} finished
        {failed > 0 ? `, ${failed} failed` : ''}. Parts finish one at a time — ask about a
        part as soon as it is done.
      </p>

      {run.status === 'reconnecting' ? (
        <p role="status" className="analyze-error">
          Connection lost — reconnecting. The rows below stay as they were and refresh from
          the server the moment the stream is back.
        </p>
      ) : null}

      {!run.hasSnapshot && run.status !== 'ended' ? (
        <p role="status" className="analyze-loading">
          Connecting to the run…
        </p>
      ) : null}

      {run.hasSnapshot && run.jobs.length === 0 ? (
        <p className="analyze-empty">This run has no jobs. Nothing was queued.</p>
      ) : null}

      <ul className="analyze-jobs">
        {run.jobs.map((job) => (
          <JobRow key={job.id} job={job} />
        ))}
      </ul>

      {run.done && run.jobs.length > 0 ? (
        <p role="status" className="analyze-done">
          Run finished.
        </p>
      ) : null}

      <div className="analyze-actions">
        <button type="button" onClick={onRestart}>
          Scan another directory
        </button>
      </div>
    </section>
  );
}
