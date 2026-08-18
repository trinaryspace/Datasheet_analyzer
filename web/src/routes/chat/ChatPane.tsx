/**
 * The chat pane: ask a question, watch the answer arrive, click a citation.
 *
 * Three decisions here are architectural rather than cosmetic.
 *
 * **Scope is resolved before the model is asked.** `POST /chat/resolve-scope`
 * runs first, and the stream is only opened once exactly one Part or Project
 * came back. When resolution is ambiguous the turn renders the candidates as
 * choices and no request to `/chat/{id}/message` is ever issued — the
 * "guess and apologise" path does not exist (ADR 0006).
 *
 * **Cross-pane state travels in the URL.** A citation click writes
 * `?doc=&part=&page=&needle=` via `useSearchParams`. This file does not
 * import the PDF pane, and must not: the two panes stay independently
 * testable only while neither knows the other's module exists.
 *
 * **Scroll anchoring yields to the user.** The transcript pins to the newest
 * token, but only while the user is already at the bottom. Scrolling up to
 * re-read an earlier answer releases the pin until they come back down.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import {
  createSession,
  getSession,
  openChatStream,
  resolveScope,
  type SSEConnection,
} from '../../api/client';
import {
  PDF_PARAM_DOC,
  PDF_PARAM_NEEDLE,
  PDF_PARAM_PAGE,
  PDF_PARAM_PART,
  type ChatEvent,
  type ScopeRef,
} from '../../api/types';
import { AnswerBody, citedInText } from './AnswerBody';
import { CitationLink } from './CitationLink';
import { ScopeChip, scopeKey } from './ScopeChip';
import {
  applyChatEvent,
  errorText,
  isActive,
  newTurn,
  replaceTurn,
  turnsFromSession,
  type CitedItem,
  type Turn,
} from './transcript';
import './chat.css';

/**
 * The session to restore, read from the URL.
 *
 * Contract gap: `api/types.ts` freezes `PDF_PARAM_*` for the pane handoff but
 * names no query parameter for the open session, so this one is declared here
 * and reported rather than added to the shared file.
 */
export const CHAT_PARAM_SESSION = 'session';

/** How close to the bottom still counts as "following the stream", in px. */
const SCROLL_ANCHOR_SLACK_PX = 48;

let turnCounter = 0;
function nextTurnId(): string {
  turnCounter += 1;
  return `turn-${turnCounter}`;
}

/**
 * The needle `/locate` searches the page for.
 *
 * `citation.needle` is the record's own printed text — the spec row's
 * parameter name, the figure's caption, the section's title — so the
 * highlight lands on the row the answer came from. The section number is the
 * fallback for a corpus built before citations carried one; it finds the
 * heading, which is why it is second and not first. A miss is honest by
 * design: the page opens with no highlight.
 */
function needleFor(item: CitedItem): string {
  return item.citation.needle || item.citation.section || item.citation.doc;
}

export interface ChatPaneProps {
  /** Test seam: skip the URL and open this session directly. */
  sessionId?: string;
}

export function ChatPane({ sessionId: fixedSessionId }: ChatPaneProps = {}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlSession = fixedSessionId ?? searchParams.get(CHAT_PARAM_SESSION) ?? '';

  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState('');
  const [sessionId, setSessionId] = useState(urlSession);
  const [sessionError, setSessionError] = useState('');
  const [restoring, setRestoring] = useState(Boolean(urlSession));

  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;
  const connectionRef = useRef<SSEConnection | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  // --- session: restore a saved transcript, or open a fresh one ---------------

  useEffect(() => {
    let live = true;
    void (async () => {
      if (urlSession) {
        setRestoring(true);
        try {
          const session = await getSession(urlSession);
          if (!live) return;
          setSessionId(session.id);
          setTurns(turnsFromSession(session));
        } catch (error) {
          if (live) setSessionError(errorText(error));
        } finally {
          if (live) setRestoring(false);
        }
        return;
      }
      try {
        const session = await createSession({});
        if (live) setSessionId(session.id);
      } catch (error) {
        if (live) setSessionError(errorText(error));
      }
    })();
    return () => {
      live = false;
    };
  }, [urlSession]);

  // Abort any live stream when the pane goes away; `close()` is idempotent.
  useEffect(() => () => connectionRef.current?.close(), []);

  // --- scroll anchoring -------------------------------------------------------

  const onScroll = useCallback(() => {
    const element = scrollRef.current;
    if (!element) return;
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight;
    stickToBottom.current = distance <= SCROLL_ANCHOR_SLACK_PX;
  }, []);

  // No dependency array on purpose: every render that appended a token should
  // re-pin, and only the ref decides whether it may.
  useLayoutEffect(() => {
    const element = scrollRef.current;
    if (element && stickToBottom.current) element.scrollTop = element.scrollHeight;
  });

  // --- the turn lifecycle -----------------------------------------------------

  const update = useCallback((id: string, change: (turn: Turn) => Turn) => {
    setTurns((current) => replaceTurn(current, id, change));
  }, []);

  const stream = useCallback(
    (id: string, text: string, scope: ScopeRef, session: string) => {
      update(id, (turn) => ({ ...turn, scope, status: 'streaming', error: '' }));
      const connection = openChatStream(
        session,
        { question: text, scope },
        {
          onEvent: (event: ChatEvent) => update(id, (turn) => applyChatEvent(turn, event)),
          onError: (error) =>
            update(id, (turn) => ({
              ...turn,
              tool: '',
              status: 'error',
              error: errorText(error),
            })),
          onClose: () => {
            connectionRef.current = null;
            update(id, (turn) =>
              turn.status === 'streaming' ? { ...turn, tool: '', status: 'complete' } : turn,
            );
          },
        },
      );
      connectionRef.current = connection;
    },
    [update],
  );

  const run = useCallback(
    async (id: string, text: string, scope: ScopeRef | null) => {
      let session = sessionIdRef.current;
      if (!session) {
        try {
          session = (await createSession({})).id;
          setSessionId(session);
        } catch (error) {
          update(id, (turn) => ({ ...turn, status: 'error', error: errorText(error) }));
          return;
        }
      }

      if (scope) {
        stream(id, text, scope, session);
        return;
      }

      update(id, (turn) => ({ ...turn, status: 'resolving', error: '', candidates: [] }));
      let resolution;
      try {
        resolution = await resolveScope({ question: text });
      } catch (error) {
        update(id, (turn) => ({ ...turn, status: 'error', error: errorText(error) }));
        return;
      }
      // Ambiguous: render the choices and stop. No model request is issued.
      if (!resolution.scope) {
        update(id, (turn) => ({
          ...turn,
          status: 'ambiguous',
          scope: null,
          candidates: resolution.candidates,
          prompt: resolution.question || 'Which one did you mean?',
          matchedVia: resolution.matched_via,
        }));
        return;
      }
      update(id, (turn) => ({ ...turn, matchedVia: resolution.matched_via }));
      stream(id, text, resolution.scope, session);
    },
    [stream, update],
  );

  const ask = useCallback(
    (text: string, scope: ScopeRef | null = null) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      const id = nextTurnId();
      stickToBottom.current = true;
      setTurns((current) => [...current, newTurn(id, trimmed, scope)]);
      void run(id, trimmed, scope);
    },
    [run],
  );

  /**
   * Re-ask an existing question under a different scope.
   *
   * The turn is reset in place rather than appended, because the user is
   * correcting *this* answer's scope — a second copy of the same question
   * further down the transcript is a different, worse thing.
   */
  const reask = useCallback(
    (turn: Turn, scope: ScopeRef) => {
      connectionRef.current?.close();
      connectionRef.current = null;
      update(turn.id, (current) => ({ ...newTurn(current.id, current.question, scope) }));
      void run(turn.id, turn.question, scope);
    },
    [run, update],
  );

  const stop = useCallback(() => {
    const active = turns.find(isActive);
    connectionRef.current?.close();
    connectionRef.current = null;
    if (active) update(active.id, (turn) => ({ ...turn, tool: '', status: 'stopped' }));
  }, [turns, update]);

  const openCitation = useCallback(
    (item: CitedItem) => {
      const next = new URLSearchParams(searchParams);
      next.set(PDF_PARAM_DOC, item.citation.doc_hash);
      next.set(PDF_PARAM_PART, item.citation.part);
      next.set(PDF_PARAM_PAGE, String(item.citation.page_start ?? 1));
      next.set(PDF_PARAM_NEEDLE, needleFor(item));
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const busy = turns.some(isActive);

  return (
    <section className="chat-pane" aria-label="Chat">
      {sessionError ? (
        <p className="chat-session-error" role="alert">
          {sessionError}
        </p>
      ) : null}

      <div
        className="chat-transcript"
        data-testid="chat-transcript"
        ref={scrollRef}
        onScroll={onScroll}
        role="log"
        aria-live="polite"
        aria-busy={busy}
      >
        {restoring ? <p className="chat-restoring">Restoring conversation…</p> : null}
        {turns.length === 0 && !restoring ? (
          <p className="chat-empty">
            Ask a question. The scope it resolves to is shown on the answer and can be changed
            there.
          </p>
        ) : null}
        {turns.map((turn) => (
          <TurnView key={turn.id} turn={turn} onScope={reask} onCitation={openCitation} />
        ))}
      </div>

      <form
        className="chat-composer"
        onSubmit={(event) => {
          event.preventDefault();
          ask(question);
          setQuestion('');
        }}
      >
        <textarea
          className="chat-question"
          aria-label="Question"
          placeholder="What is the maximum junction temperature?"
          rows={2}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              ask(question);
              setQuestion('');
            }
          }}
        />
        <div className="chat-composer-actions">
          <button type="submit" className="chat-ask" disabled={!question.trim()}>
            Ask
          </button>
          {busy ? (
            <button type="button" className="chat-stop" onClick={stop}>
              Stop
            </button>
          ) : null}
        </div>
      </form>
    </section>
  );
}

interface TurnViewProps {
  turn: Turn;
  onScope: (turn: Turn, scope: ScopeRef) => void;
  onCitation: (item: CitedItem) => void;
}

function TurnView({ turn, onScope, onCitation }: TurnViewProps) {
  // Anything the answer already cites in place is not repeated underneath;
  // what is left is what the model read but never referred to, and dropping
  // it silently would hide a source the reader is entitled to check.
  const unreferenced = turn.citations.filter((item) => !citedInText(turn.text, item));

  return (
    <article className="chat-turn" data-turn-id={turn.id} data-status={turn.status}>
      {turn.question ? (
        <p className="chat-question-text" data-role="user">
          {turn.question}
        </p>
      ) : null}

      <div className="chat-answer" data-role="assistant">
        <div className="chat-answer-head">
          {turn.scope ? (
            <ScopeChip
              scope={turn.scope}
              matchedVia={turn.matchedVia}
              disabled={isActive(turn)}
              onChange={(scope) => onScope(turn, scope)}
            />
          ) : null}
          {turn.status === 'resolving' ? (
            <span className="chat-resolving">Resolving scope…</span>
          ) : null}
          {turn.status === 'stopped' ? <span className="chat-stopped">Stopped</span> : null}
        </div>

        {turn.tool ? (
          <p className="chat-tool" data-testid="chat-tool" role="status">
            {turn.tool}
          </p>
        ) : null}

        {turn.text ? (
          <AnswerBody text={turn.text} citations={turn.citations} onCitation={onCitation} />
        ) : null}

        {unreferenced.length > 0 ? (
          <p className="chat-citations" aria-label="Other sources read">
            <span className="chat-citations-label">Also read</span>
            {unreferenced.map((item) => (
              <CitationLink
                key={`${item.citation.doc_hash}:${item.citation.label}`}
                item={item}
                onOpen={onCitation}
              />
            ))}
          </p>
        ) : null}

        {turn.status === 'ambiguous' ? (
          <div className="chat-ambiguous" data-testid="chat-ambiguous">
            <p className="chat-ambiguous-prompt">{turn.prompt}</p>
            <ul className="chat-candidates">
              {turn.candidates.map((candidate) => (
                <li key={scopeKey(candidate)}>
                  <button
                    type="button"
                    className="chat-candidate"
                    data-scope-kind={candidate.kind}
                    onClick={() => onScope(turn, candidate)}
                  >
                    {candidate.name}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {turn.status === 'error' ? (
          <p className="chat-error" role="alert">
            {turn.error}
          </p>
        ) : null}
      </div>
    </article>
  );
}

export default ChatPane;
