/**
 * The transcript model: pure functions, no React, no fetch.
 *
 * A conversation is a list of **turns**, not a flat list of messages. A turn
 * owns the question, the answer streaming into it, the citations that back
 * that answer, and — the part that matters for ADR 0006 — the scope the
 * answer was drawn from. Keeping the scope on the turn is what makes
 * "change the scope and re-ask the same question" a local edit rather than a
 * new thread.
 *
 * Everything here is a pure transform of `(turn, event) -> turn`, so the
 * stream handling is testable without a DOM and without a server.
 */
import type {
  ChatEvent,
  ChatMessage,
  CitationOut,
  ScopeRef,
  SessionOut,
} from '../../api/types';

/** Where a turn is. `ambiguous` is a question back to the user, not a failure. */
export type TurnStatus =
  | 'resolving'
  | 'ambiguous'
  | 'streaming'
  | 'complete'
  | 'stopped'
  | 'error';

/** A citation plus the confidence the tool result reported for it. */
export interface CitedItem {
  citation: CitationOut;
  /** `"low" | "medium" | "high" | ""` — the server's own word, not ours. */
  confidence: string;
}

/** One question and the answer being written under it. */
export interface Turn {
  id: string;
  question: string;
  /** The resolved scope, shown on the answer and editable. `null` until resolved. */
  scope: ScopeRef | null;
  /** How resolution decided, e.g. `part-name`; rendered as the chip's tooltip. */
  matchedVia: string;
  status: TurnStatus;
  text: string;
  citations: CitedItem[];
  /** Transient tool activity, cleared the moment text starts arriving. */
  tool: string;
  /** Populated only when `status === 'ambiguous'`. */
  candidates: ScopeRef[];
  /** The server's question back to the user when resolution is ambiguous. */
  prompt: string;
  error: string;
}

/** A turn is still consuming a stream (or about to open one). */
export function isActive(turn: Turn): boolean {
  return turn.status === 'resolving' || turn.status === 'streaming';
}

/** A fresh turn for `question`, before anything has been resolved. */
export function newTurn(id: string, question: string, scope: ScopeRef | null = null): Turn {
  return {
    id,
    question,
    scope,
    matchedVia: '',
    status: 'resolving',
    text: '',
    citations: [],
    tool: '',
    candidates: [],
    prompt: '',
    error: '',
  };
}

function sameCitation(a: CitationOut, b: CitationOut): boolean {
  return a.doc_hash === b.doc_hash && a.label === b.label && a.part === b.part;
}

/**
 * Fold one stream frame into a turn.
 *
 * Two rules are load-bearing:
 *
 * - a `token` clears `tool`, because the "searching specs…" line exists to
 *   fill the silence before text and is a lie once text is arriving;
 * - a `scope` frame with no scope is an **ask**, not an error — the server
 *   never called the model, so the turn becomes `ambiguous` and waits.
 */
export function applyChatEvent(turn: Turn, event: ChatEvent): Turn {
  switch (event.type) {
    case 'token':
      return { ...turn, status: 'streaming', tool: '', text: turn.text + event.text };

    case 'tool':
      return { ...turn, tool: event.summary || event.tool || 'working…' };

    case 'citation': {
      if (!event.citation) return turn;
      const citation = event.citation;
      if (turn.citations.some((held) => sameCitation(held.citation, citation))) return turn;
      return {
        ...turn,
        citations: [...turn.citations, { citation, confidence: event.confidence }],
      };
    }

    case 'scope': {
      const resolution = event.resolution;
      const scope = event.scope ?? resolution?.scope ?? null;
      if (scope) {
        return {
          ...turn,
          scope,
          matchedVia: resolution?.matched_via ?? turn.matchedVia,
          candidates: [],
          prompt: '',
          status: turn.status === 'resolving' ? 'streaming' : turn.status,
        };
      }
      return {
        ...turn,
        scope: null,
        status: 'ambiguous',
        tool: '',
        candidates: resolution?.candidates ?? [],
        prompt: resolution?.question ?? '',
        matchedVia: resolution?.matched_via ?? turn.matchedVia,
      };
    }

    case 'done':
      if (turn.status === 'error' || turn.status === 'ambiguous') return { ...turn, tool: '' };
      return { ...turn, tool: '', status: 'complete' };

    case 'error':
      return { ...turn, tool: '', status: 'error', error: event.message };

    default:
      return turn;
  }
}

/** The transcript a saved session restores to. */
export function turnsFromMessages(messages: ChatMessage[], scope: ScopeRef | null): Turn[] {
  const turns: Turn[] = [];
  for (const message of messages) {
    if (message.role === 'user') {
      const asked = newTurn(`restored-${turns.length}`, message.text, scope);
      turns.push({ ...asked, status: 'complete' });
      continue;
    }
    let target = turns[turns.length - 1];
    // An assistant message with no question before it (or one whose question
    // already has an answer) still belongs in the transcript, with an empty
    // question, rather than being dropped.
    if (!target || target.text !== '') {
      target = { ...newTurn(`restored-${turns.length}`, '', scope), status: 'complete' };
      turns.push(target);
    }
    target.text = message.text;
    target.citations = message.citations.map((citation) => ({ citation, confidence: '' }));
  }
  return turns;
}

/** The transcript for a whole restored session. */
export function turnsFromSession(session: SessionOut): Turn[] {
  return turnsFromMessages(session.messages, session.scope ?? null);
}

/** Replace one turn by id, leaving the rest of the transcript untouched. */
export function replaceTurn(turns: Turn[], id: string, update: (turn: Turn) => Turn): Turn[] {
  let changed = false;
  const next = turns.map((turn) => {
    if (turn.id !== id) return turn;
    changed = true;
    return update(turn);
  });
  return changed ? next : turns;
}

/** The message an unknown thrown value should be rendered as. */
export function errorText(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === 'string' && error) return error;
  return 'the answer stream failed';
}
