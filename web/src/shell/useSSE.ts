/**
 * `useSSE` — the client's SSE helper with a React lifetime around it.
 *
 * `api/client.ts` owns the wire format and returns an `SSEConnection` whose
 * `close()` aborts the request. What it deliberately does *not* own is when to
 * open, when to give up, and when to try again — those are the component's
 * concerns, and this hook is the one place they are answered so five screens
 * do not answer them five ways.
 *
 * Two guarantees:
 *
 * - **Cleanup on unmount.** The connection is closed in the effect's teardown,
 *   and a reconnect already scheduled is cancelled. A stream left open after a
 *   pane closes keeps a server generator alive for the life of the process.
 * - **Reconnect after a drop.** A dropped stream retries with a linear
 *   backoff up to `maxRetries`. Events arriving from a superseded connection
 *   are ignored, so a late frame from a dead socket cannot mutate state.
 *
 * `open` is injectable purely so tests can drive a fake: jsdom has no
 * `EventSource`, and the rule is that no test opens a socket.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { openSSE } from '../api/client';
import type { SSEConnection, SSEHandlers } from '../api/client';

/** Where the stream is. `reconnecting` is between a drop and the next attempt. */
export type SSEStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed' | 'error';

/** Signature of the client helper the hook drives; matches `openSSE`. */
export type SSEOpener = (path: string, handlers: SSEHandlers) => SSEConnection;

export interface UseSSEOptions {
  /** API-relative path (the client prefixes `/api`). `null` opens nothing. */
  path: string | null;
  onEvent: (event: string, data: string) => void;
  onError?: (error: unknown) => void;
  /** Set false to hold the stream closed without unmounting the component. */
  enabled?: boolean;
  /** Base delay before a retry; attempt *n* waits `n × delay`. */
  reconnectDelayMs?: number;
  maxRetries?: number;
  /** Defaults to `openSSE`; a test passes a fake. */
  open?: SSEOpener;
}

export interface UseSSEResult {
  status: SSEStatus;
  /** Reconnect attempts made since the last successful open. */
  retries: number;
  /** Close now and stop retrying. Idempotent. */
  close: () => void;
  /** Close and immediately reopen, resetting the retry count. */
  reconnect: () => void;
}

/** Subscribe to an SSE endpoint for as long as the component is mounted. */
export function useSSE({
  path,
  onEvent,
  onError,
  enabled = true,
  reconnectDelayMs = 1000,
  maxRetries = 5,
  open = openSSE,
}: UseSSEOptions): UseSSEResult {
  const [status, setStatus] = useState<SSEStatus>('idle');
  const [retries, setRetries] = useState(0);
  const [generation, setGeneration] = useState(0);

  // Handlers change identity every render; a ref keeps the effect from
  // tearing the connection down and back up on each one.
  const onEventRef = useRef(onEvent);
  const onErrorRef = useRef(onError);
  onEventRef.current = onEvent;
  onErrorRef.current = onError;

  const connectionRef = useRef<SSEConnection | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const stoppedRef = useRef(false);

  const close = useCallback(() => {
    stoppedRef.current = true;
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    connectionRef.current?.close();
    connectionRef.current = null;
    setStatus('closed');
  }, []);

  const reconnect = useCallback(() => {
    stoppedRef.current = false;
    setRetries(0);
    setGeneration((n) => n + 1);
  }, []);

  useEffect(() => {
    if (!enabled || path === null) {
      setStatus('idle');
      return;
    }
    stoppedRef.current = false;
    let disposed = false;
    let attempt = 0;

    const start = () => {
      if (disposed || stoppedRef.current) return;
      setStatus(attempt === 0 ? 'connecting' : 'reconnecting');
      connectionRef.current = open(path, {
        onOpen: () => {
          if (disposed) return;
          attempt = 0;
          setRetries(0);
          setStatus('open');
        },
        onEvent: (event, data) => {
          if (disposed) return;
          onEventRef.current(event, data);
        },
        onError: (error) => {
          if (disposed || stoppedRef.current) return;
          onErrorRef.current?.(error);
          connectionRef.current?.close();
          connectionRef.current = null;
          if (attempt >= maxRetries) {
            setStatus('error');
            return;
          }
          attempt += 1;
          setRetries(attempt);
          setStatus('reconnecting');
          timerRef.current = setTimeout(start, reconnectDelayMs * attempt);
        },
      });
    };

    start();

    return () => {
      disposed = true;
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      connectionRef.current?.close();
      connectionRef.current = null;
    };
  }, [path, enabled, maxRetries, reconnectDelayMs, open, generation]);

  return { status, retries, close, reconnect };
}

export default useSSE;
