/**
 * Live state for one analyze run, fed by the SSE stream.
 *
 * The stream leads with a `snapshot` on **every** connect, which is what
 * makes reconnection cheap: a drop is repaired by re-opening and re-rendering
 * from the snapshot the server sends, never by replaying missed frames and
 * never by blanking the screen. Rows therefore stay on screen while the
 * connection is being rebuilt — a gap would read as "the run died".
 *
 * Reconnect is explicit rather than left to `EventSource`'s own retry so the
 * screen can say it is reconnecting, and so the behaviour is the same for
 * both the browser's stream and a test's fake one.
 */
import { useEffect, useMemo, useRef, useState } from 'react';

import { openAnalyzeStream } from '../../api/client';
import type { SSEConnection } from '../../api/client';
import type { AnalyzeJob, JobEvent, JobState, RunSnapshot } from '../../api/types';
import { JOB_TERMINAL_STATES } from '../../api/types';

/** Where the connection is. `ended` means the server sent `end`. */
export type StreamStatus = 'connecting' | 'live' | 'reconnecting' | 'ended';

/** Backoff between reconnect attempts: linear, then capped. */
export const RECONNECT_BASE_MS = 500;
export const RECONNECT_MAX_MS = 5_000;

export interface AnalyzeRunState {
  jobs: AnalyzeJob[];
  status: StreamStatus;
  /** True once a snapshot has arrived; until then the screen is loading. */
  hasSnapshot: boolean;
  /** Directory the server reports for this run. */
  directory: string;
  /** How many times the stream has been re-opened after a drop. */
  reconnects: number;
  done: boolean;
}

const EMPTY_APPLICABILITY = {
  kind: 'all' as const,
  parts: [],
  family: '',
  category: '',
  evidence: '',
};

/** A job the snapshot has not described yet, synthesized from its event. */
function jobFromEvent(event: JobEvent): AnalyzeJob {
  return {
    id: event.job_id,
    pdf_path: event.pdf_path,
    part_number: event.part_number,
    applicability: { ...EMPTY_APPLICABILITY },
    state: event.state,
    error: event.state === 'failed' ? event.detail : '',
    detail: event.detail,
    started_at: null,
    finished_at: null,
  };
}

function applyEvent(jobs: AnalyzeJob[], event: JobEvent): AnalyzeJob[] {
  let seen = false;
  const next = jobs.map((job) => {
    if (job.id !== event.job_id) return job;
    seen = true;
    return {
      ...job,
      state: event.state,
      detail: event.detail || job.detail,
      // A failure's text arrives as the transition's `detail`; keep any
      // error the snapshot already carried if this frame has none.
      error: event.state === 'failed' ? event.detail || job.error : job.error,
      part_number: event.part_number || job.part_number,
      pdf_path: event.pdf_path || job.pdf_path,
    };
  });
  return seen ? next : [...next, jobFromEvent(event)];
}

/** True once every job has reached a terminal state. */
export function allTerminal(jobs: AnalyzeJob[]): boolean {
  return jobs.length > 0 && jobs.every((job) => JOB_TERMINAL_STATES.includes(job.state));
}

/** Count of jobs in each state, for the run's one-line summary. */
export function countByState(jobs: AnalyzeJob[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const job of jobs) counts[job.state] = (counts[job.state] ?? 0) + 1;
  return counts;
}

/**
 * Subscribe to a run's stream for as long as the component is mounted.
 *
 * `runId` empty means "no run yet" and opens nothing. The connection is
 * closed on unmount and on a run change, so a screen that navigates away
 * leaves no stream behind.
 */
export function useAnalyzeRun(runId: string): AnalyzeRunState {
  const [jobs, setJobs] = useState<AnalyzeJob[]>([]);
  const [status, setStatus] = useState<StreamStatus>('connecting');
  const [hasSnapshot, setHasSnapshot] = useState(false);
  const [directory, setDirectory] = useState('');
  const [reconnects, setReconnects] = useState(0);
  const [done, setDone] = useState(false);
  const endedRef = useRef(false);

  useEffect(() => {
    if (!runId) return;
    endedRef.current = false;
    setJobs([]);
    setHasSnapshot(false);
    setReconnects(0);
    setDone(false);
    setStatus('connecting');

    let cancelled = false;
    let connection: SSEConnection | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;

    const finish = () => {
      endedRef.current = true;
      setStatus('ended');
      setDone(true);
    };

    const connect = () => {
      connection = openAnalyzeStream(runId, {
        onOpen: () => {
          if (cancelled || endedRef.current) return;
          attempt = 0;
          setStatus('live');
        },
        onSnapshot: (snapshot: RunSnapshot) => {
          if (cancelled) return;
          setJobs(snapshot.jobs);
          setDirectory(snapshot.directory);
          setHasSnapshot(true);
          setDone(snapshot.done);
          if (!endedRef.current) setStatus('live');
        },
        onJob: (event: JobEvent) => {
          if (cancelled) return;
          setJobs((current) => applyEvent(current, event));
        },
        onEnd: () => {
          if (cancelled) return;
          finish();
        },
        onError: () => {
          if (cancelled || endedRef.current) return;
          // The rows stay exactly as they are: the next snapshot repairs
          // them, so there is never a blank frame between the drop and it.
          setStatus('reconnecting');
          connection?.close();
          connection = null;
          attempt += 1;
          setReconnects(attempt);
          timer = setTimeout(connect, Math.min(RECONNECT_BASE_MS * attempt, RECONNECT_MAX_MS));
        },
      });
    };

    connect();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      connection?.close();
    };
  }, [runId]);

  return useMemo(
    () => ({ jobs, status, hasSnapshot, directory, reconnects, done: done || allTerminal(jobs) }),
    [jobs, status, hasSnapshot, directory, reconnects, done],
  );
}

/** Human wording for each state; the server's `detail` wins when present. */
export const STATE_LABEL: Record<JobState, string> = {
  queued: 'Queued',
  extracting: 'Extracting',
  structuring: 'Structuring',
  enriching: 'Enriching',
  publishing: 'Publishing',
  done: 'Done',
  failed: 'Failed',
  skipped: 'Skipped',
};
