/**
 * Chat pane tests — ticket 18.
 *
 * Hermetic in the same sense the Python suite is: no network, no live model,
 * no browser. `fetch` is replaced by a router over fake responses, and the
 * chat turn is driven by a hand-fed SSE body reader so every frame's arrival
 * is a step the test controls. The pane is exercised through the DOM the user
 * sees — no assertions on React internals.
 *
 * This file is `.ts` rather than `.tsx` because that is the filename the
 * ticket owns; elements are built with `createElement`.
 */
import {
  act,
  chatSourceFiles,
  cleanup,
  createElement,
  fireEvent,
  MemoryRouter,
  render,
  screen,
  useLocation,
  userEvent,
  waitFor,
  within,
  type ReactNode,
} from '../../web/src/routes/chat/test-kit';

import type { ChatEvent, CitationOut, ScopeRef } from '../../web/src/api/types';
import { ChatPane } from '../../web/src/routes/chat/ChatPane';
import {
  applyChatEvent,
  newTurn,
  turnsFromSession,
} from '../../web/src/routes/chat/transcript';

// --- fixtures ------------------------------------------------------------------

const AFE: ScopeRef = { kind: 'part', name: 'AFE7950' };
const LMX: ScopeRef = { kind: 'part', name: 'LMX1204' };

function citation(overrides: Partial<CitationOut> = {}): CitationOut {
  return {
    doc: 'afe7950.pdf',
    doc_hash: 'hash-afe',
    section: '4.5 Thermal Characteristics',
    page_start: 7,
    page_end: 7,
    part: 'AFE7950',
    pages: 'p.7',
    label: '§4.5, p.7',
    needle: 'Junction temperature',
    ...overrides,
  };
}

function chatEvent(overrides: Partial<ChatEvent>): ChatEvent {
  return {
    type: 'token',
    text: '',
    tool: '',
    summary: '',
    citation: null,
    scope: null,
    resolution: null,
    confidence: '',
    message: '',
    at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

/** One SSE frame exactly as `sse-starlette` writes it. */
function frame(overrides: Partial<ChatEvent>): string {
  const event = chatEvent(overrides);
  return `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`;
}

// --- a body reader the test feeds by hand ---------------------------------------

interface FakeStream {
  push: (chunk: string) => Promise<void>;
  finish: () => Promise<void>;
  signal: AbortSignal;
  body: { getReader: () => { read: () => Promise<{ done: boolean; value?: Uint8Array }> } };
}

function makeStream(signal: AbortSignal): FakeStream {
  const encoder = new TextEncoder();
  const pending: Uint8Array[] = [];
  let waiting: ((result: { done: boolean; value?: Uint8Array }) => void) | null = null;
  let ended = false;

  const settle = () => {
    if (!waiting) return;
    const resolve = waiting;
    waiting = null;
    if (pending.length > 0) resolve({ done: false, value: pending.shift() });
    else if (ended) resolve({ done: true });
    else waiting = resolve;
  };

  // A real abort ends the response body; the fake does the same so the client's
  // read loop exits instead of hanging the test.
  signal.addEventListener('abort', () => {
    ended = true;
    settle();
  });

  return {
    signal,
    async push(chunk: string) {
      pending.push(encoder.encode(chunk));
      await act(async () => {
        settle();
        await Promise.resolve();
        await Promise.resolve();
      });
    },
    async finish() {
      ended = true;
      await act(async () => {
        settle();
        await Promise.resolve();
        await Promise.resolve();
      });
    },
    body: {
      getReader: () => ({
        read: () =>
          new Promise<{ done: boolean; value?: Uint8Array }>((resolve) => {
            waiting = resolve;
            settle();
          }),
      }),
    },
  };
}

// --- the fake server -------------------------------------------------------------

interface ServerOptions {
  session?: Record<string, unknown>;
  resolution?: Record<string, unknown>;
  parts?: string[];
  projects?: string[];
  sessionsFail?: string;
}

interface FakeServer {
  chatRequests: { url: string; body: { question: string; scope?: ScopeRef | null } }[];
  streams: FakeStream[];
  lastStream: () => FakeStream;
}

function emptySession(id = 's1') {
  return {
    id,
    title: 'Untitled',
    scope: { kind: 'part', name: '' },
    messages: [],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    n_messages: 0,
  };
}

function jsonResponse(data: unknown) {
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    json: async () => data,
    text: async () => JSON.stringify(data),
  };
}

function installServer(options: ServerOptions = {}): FakeServer {
  const server: FakeServer = {
    chatRequests: [],
    streams: [],
    lastStream: () => {
      const stream = server.streams[server.streams.length - 1];
      if (!stream) throw new Error('no chat stream was opened');
      return stream;
    },
  };
  const parts = options.parts ?? ['AFE7950', 'LMX1204'];
  const projects = options.projects ?? ['rx-frontend'];

  const fake = async (input: unknown, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? 'GET').toUpperCase();

    if (url.endsWith('/api/sessions') && method === 'POST') {
      if (options.sessionsFail) {
        return {
          ok: false,
          status: 500,
          statusText: 'error',
          json: async () => ({ detail: options.sessionsFail }),
          text: async () => options.sessionsFail as string,
        };
      }
      return jsonResponse(emptySession());
    }
    if (/\/api\/sessions\/[^/]+$/.test(url) && method === 'GET') {
      return jsonResponse(options.session ?? emptySession(url.split('/').pop() as string));
    }
    if (url.endsWith('/api/chat/resolve-scope')) {
      return jsonResponse(
        options.resolution ?? {
          scope: AFE,
          confident: true,
          candidates: [],
          question: '',
          matched_via: 'part-name',
        },
      );
    }
    if (url.includes('/api/chat/') && url.endsWith('/message')) {
      server.chatRequests.push({ url, body: JSON.parse(String(init?.body ?? '{}')) });
      const stream = makeStream(init?.signal as AbortSignal);
      server.streams.push(stream);
      return { ok: true, status: 200, statusText: 'OK', body: stream.body };
    }
    if (url.endsWith('/api/parts')) {
      return jsonResponse({
        parts: parts.map((part_number) => ({
          part_number,
          built: true,
          revision: '',
          vendor: '',
          backends: [],
          sections: 0,
          specs: 0,
          plots: 0,
          tokens: 0,
          searchable: true,
          spec_confidence: {},
          plot_confidence: {},
        })),
        count: parts.length,
      });
    }
    if (url.endsWith('/api/projects')) {
      return jsonResponse({
        projects: projects.map((name) => ({
          name,
          parts: [],
          interfaces: '',
          notes: '',
          built: true,
          error: '',
        })),
        count: projects.length,
      });
    }
    throw new Error(`the chat pane called an endpoint no test stubbed: ${method} ${url}`);
  };

  vi.stubGlobal('fetch', vi.fn(fake));
  return server;
}

// --- rendering -------------------------------------------------------------------

/** Reports the URL query, so citation clicks can be asserted as shared state. */
function LocationProbe() {
  const location = useLocation();
  return createElement('output', { 'data-testid': 'location-search' }, location.search);
}

function renderPane(props: { sessionId?: string } = {}, entries: string[] = ['/chat']): void {
  const children: ReactNode[] = [
    createElement(ChatPane, { key: 'pane', ...props }),
    createElement(LocationProbe, { key: 'probe' }),
  ];
  render(createElement(MemoryRouter, { initialEntries: entries }, children));
}

/** Wait out the session load so the transcript is ready for a question. */
async function settled(): Promise<void> {
  await waitFor(() => expect(screen.queryByText('Restoring conversation…')).toBeNull());
}

async function ask(text: string): Promise<void> {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Question'), text);
  await user.click(screen.getByRole('button', { name: 'Ask' }));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// --- the transcript model ----------------------------------------------------------

describe('the transcript model', () => {
  it('appends token text and clears tool activity when text begins', () => {
    let turn = newTurn('t', 'how hot?');
    const tool = chatEvent({ type: 'tool', tool: 'search_specs', summary: 'searching specs…' });
    turn = applyChatEvent(turn, tool);
    expect(turn.tool).toBe('searching specs…');

    turn = applyChatEvent(turn, chatEvent({ type: 'token', text: '125' }));
    turn = applyChatEvent(turn, chatEvent({ type: 'token', text: ' °C' }));
    expect(turn.text).toBe('125 °C');
    expect(turn.tool).toBe('');
    expect(turn.status).toBe('streaming');
  });

  it('treats a scope frame with no scope as a question, not a failure', () => {
    const turn = applyChatEvent(
      newTurn('t', 'gain?'),
      chatEvent({
        type: 'scope',
        scope: null,
        resolution: {
          scope: null,
          confident: false,
          candidates: [AFE, LMX],
          question: 'Which part did you mean?',
          matched_via: 'ambiguous',
        },
      }),
    );
    expect(turn.status).toBe('ambiguous');
    expect(turn.candidates).toEqual([AFE, LMX]);
    expect(turn.error).toBe('');
  });

  it('keeps a turn whole across an error frame', () => {
    let turn = applyChatEvent(newTurn('t', 'q'), chatEvent({ type: 'token', text: 'partial' }));
    turn = applyChatEvent(turn, chatEvent({ type: 'error', message: 'the tool exploded' }));
    expect(turn.text).toBe('partial');
    expect(turn.status).toBe('error');
    expect(turn.error).toBe('the tool exploded');
  });

  it('never duplicates a citation the model cited twice', () => {
    let turn = newTurn('t', 'q');
    turn = applyChatEvent(turn, chatEvent({ type: 'citation', citation: citation() }));
    turn = applyChatEvent(turn, chatEvent({ type: 'citation', citation: citation() }));
    expect(turn.citations).toHaveLength(1);
  });

  it('pairs a saved session back into question-and-answer turns', () => {
    const turns = turnsFromSession({
      id: 's9',
      title: 'thermal',
      scope: AFE,
      messages: [
        { role: 'user', text: 'how hot?', citations: [], created_at: '2026-01-01T00:00:00Z' },
        {
          role: 'assistant',
          text: '125 °C',
          citations: [citation()],
          created_at: '2026-01-01T00:00:01Z',
        },
      ],
      created_at: null,
      updated_at: null,
      n_messages: 2,
    });
    expect(turns).toHaveLength(1);
    expect(turns[0].question).toBe('how hot?');
    expect(turns[0].text).toBe('125 °C');
    expect(turns[0].scope).toEqual(AFE);
  });
});

// --- streaming ---------------------------------------------------------------------

describe('asking a question', () => {
  let server: FakeServer;

  beforeEach(() => {
    server = installServer();
  });

  it('streams tokens into the transcript as they arrive', async () => {
    renderPane({ sessionId: 's1' });
    await settled();
    await ask('how hot can it run?');

    await waitFor(() => expect(server.streams.length).toBe(1));
    const stream = server.lastStream();

    await stream.push(frame({ type: 'token', text: 'The maximum ' }));
    expect(await screen.findByText('The maximum')).toBeInTheDocument();

    await stream.push(frame({ type: 'token', text: 'junction temperature is 125 °C.' }));
    expect(
      await screen.findByText('The maximum junction temperature is 125 °C.'),
    ).toBeInTheDocument();

    await stream.push(frame({ type: 'done' }));
    await stream.finish();
    await waitFor(() =>
      expect(screen.getByRole('article')).toHaveAttribute('data-status', 'complete'),
    );
  });

  it('shows tool activity while running and clears it when text begins', async () => {
    renderPane({ sessionId: 's1' });
    await settled();
    await ask('how hot can it run?');
    await waitFor(() => expect(server.streams.length).toBe(1));
    const stream = server.lastStream();

    await stream.push(frame({ type: 'tool', tool: 'search_specs', summary: 'searching specs…' }));
    expect(await screen.findByTestId('chat-tool')).toHaveTextContent('searching specs…');

    await stream.push(frame({ type: 'token', text: '125 °C' }));
    await waitFor(() => expect(screen.queryByTestId('chat-tool')).toBeNull());
    expect(screen.getByText('125 °C')).toBeInTheDocument();
  });

  it('renders an error frame inline and preserves the transcript', async () => {
    renderPane({ sessionId: 's1' });
    await settled();
    await ask('how hot can it run?');
    await waitFor(() => expect(server.streams.length).toBe(1));
    const stream = server.lastStream();

    await stream.push(frame({ type: 'token', text: 'The maximum is ' }));
    await stream.push(frame({ type: 'error', message: 'the retrieval tool failed' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('the retrieval tool failed');
    expect(screen.getByText('The maximum is')).toBeInTheDocument();
    expect(screen.getByText('how hot can it run?')).toBeInTheDocument();
  });

  it('stops the in-flight request and leaves the partial text in place', async () => {
    renderPane({ sessionId: 's1' });
    await settled();
    await ask('how hot can it run?');
    await waitFor(() => expect(server.streams.length).toBe(1));
    const stream = server.lastStream();

    await stream.push(frame({ type: 'token', text: 'The maximum is ' }));
    expect(stream.signal.aborted).toBe(false);

    await userEvent.setup().click(await screen.findByRole('button', { name: 'Stop' }));

    await waitFor(() => expect(stream.signal.aborted).toBe(true));
    expect(screen.getByText('The maximum is')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole('article')).toHaveAttribute('data-status', 'stopped'),
    );
  });
});

// --- scope --------------------------------------------------------------------------

describe('the scope chip', () => {
  it('shows the resolved part and opens a picker on click', async () => {
    const server = installServer();
    renderPane({ sessionId: 's1' });
    await settled();
    await ask('how hot can it run?');
    await waitFor(() => expect(server.streams.length).toBe(1));

    const chip = await screen.findByRole('button', { name: /AFE7950/ });
    expect(chip).toHaveAttribute('data-scope-name', 'AFE7950');
    expect(chip).toHaveAttribute('data-scope-kind', 'part');
    expect(chip).toHaveAttribute('title', 'Resolved by part-name');

    await server.lastStream().push(frame({ type: 'token', text: '125 °C' }));
    await server.lastStream().push(frame({ type: 'done' }));
    await server.lastStream().finish();

    await userEvent.setup().click(chip);
    const picker = await screen.findByRole('dialog', { name: 'Change scope' });
    expect(within(picker).getByRole('option', { name: /LMX1204/ })).toBeInTheDocument();
    expect(within(picker).getByRole('option', { name: /rx-frontend/ })).toBeInTheDocument();
  });

  it('re-asks the same question under a scope chosen from the picker', async () => {
    const server = installServer();
    renderPane({ sessionId: 's1' });
    await settled();
    await ask('how hot can it run?');
    await waitFor(() => expect(server.streams.length).toBe(1));

    await server.lastStream().push(frame({ type: 'token', text: 'AFE answer' }));
    await server.lastStream().push(frame({ type: 'done' }));
    await server.lastStream().finish();

    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /AFE7950/ }));
    await user.click(await screen.findByRole('option', { name: /LMX1204/ }));

    await waitFor(() => expect(server.chatRequests).toHaveLength(2));
    expect(server.chatRequests[1].body).toEqual({ question: 'how hot can it run?', scope: LMX });

    // Re-asked, not re-threaded: one question, one answer, now the new one.
    expect(screen.getAllByRole('article')).toHaveLength(1);
    expect(screen.getAllByText('how hot can it run?')).toHaveLength(1);
    await server.lastStream().push(frame({ type: 'token', text: 'LMX answer' }));
    expect(await screen.findByText('LMX answer')).toBeInTheDocument();
    expect(screen.queryByText('AFE answer')).toBeNull();
  });

  it('asks which part rather than guessing, and issues no model request', async () => {
    const server = installServer({
      resolution: {
        scope: null,
        confident: false,
        candidates: [AFE, LMX],
        question: 'Two parts match "gain". Which did you mean?',
        matched_via: 'ambiguous',
      },
    });
    renderPane({ sessionId: 's1' });
    await settled();
    await ask('what is the gain?');

    const choices = await screen.findByTestId('chat-ambiguous');
    expect(choices).toHaveTextContent('Two parts match "gain". Which did you mean?');
    expect(within(choices).getByRole('button', { name: 'AFE7950' })).toBeInTheDocument();
    expect(within(choices).getByRole('button', { name: 'LMX1204' })).toBeInTheDocument();

    // The whole point: the model was never asked.
    expect(server.chatRequests).toHaveLength(0);
    expect(screen.queryByRole('alert')).toBeNull();

    await userEvent.setup().click(within(choices).getByRole('button', { name: 'LMX1204' }));
    await waitFor(() => expect(server.chatRequests).toHaveLength(1));
    expect(server.chatRequests[0].body).toEqual({ question: 'what is the gain?', scope: LMX });
  });
});

// --- citations ------------------------------------------------------------------------

describe('citations', () => {
  async function askAndCite(overrides: Partial<ChatEvent> = {}): Promise<FakeServer> {
    const server = installServer();
    renderPane({ sessionId: 's1' });
    await settled();
    await ask('how hot can it run?');
    await waitFor(() => expect(server.streams.length).toBe(1));
    const stream = server.lastStream();
    await stream.push(frame({ type: 'token', text: 'The maximum is 125 °C.' }));
    await stream.push(frame({ type: 'citation', citation: citation(), ...overrides }));
    return server;
  }

  it('renders the citation label the retrieval core built', async () => {
    await askAndCite();
    const link = await screen.findByRole('button', { name: /Open citation §4.5, p.7/ });
    expect(link).toHaveTextContent('§4.5, p.7');
  });

  /** A marker written where the claim is, backed by a citation the stream sent. */
  async function askAndAnswer(text: string): Promise<void> {
    const server = installServer();
    renderPane({ sessionId: 's1' });
    await settled();
    await ask('how hot can it run?');
    await waitFor(() => expect(server.streams.length).toBe(1));
    const stream = server.lastStream();
    await stream.push(frame({ type: 'token', text }));
    await stream.push(frame({ type: 'citation', citation: citation() }));
  }

  it('turns an inline marker into a link where the claim is made', async () => {
    await askAndAnswer('The maximum is **125 °C** [§4.5, p.7].');
    const body = await screen.findByTestId('chat-answer-body');
    const link = within(body).getByRole('button', { name: /Open citation §4.5, p.7/ });
    expect(link).toBeInTheDocument();
    // Cited in place, so it is not repeated in the trailing row.
    expect(screen.queryByLabelText('Other sources read')).toBeNull();
  });

  it('renders markdown rather than printing its punctuation', async () => {
    await askAndAnswer('The maximum is **125 °C** [§4.5, p.7].');
    const body = await screen.findByTestId('chat-answer-body');
    expect(body.querySelector('strong')).toHaveTextContent('125 °C');
    expect(body.textContent).not.toContain('**');
  });

  it('never makes a link from a marker no tool returned', async () => {
    // §9.9 was invented by the model; only §4.5 was collected structurally.
    await askAndAnswer('Invented [§9.9, p.99]. Real [§4.5, p.7].');
    const body = await screen.findByTestId('chat-answer-body');
    expect(within(body).queryByRole('button', { name: /§9.9/ })).toBeNull();
    expect(body.textContent).toContain('[§9.9, p.99]');
    expect(within(body).getByRole('button', { name: /Open citation §4.5, p.7/ })).toBeInTheDocument();
  });

  it('keeps a citation the answer never referred to, under Also read', async () => {
    await askAndAnswer('An answer that cites nothing in prose.');
    const trailing = await screen.findByLabelText('Other sources read');
    expect(within(trailing).getByRole('button', { name: /Open citation §4.5, p.7/ })).toBeInTheDocument();
  });

  it('badges a low-confidence citation beside the link', async () => {
    await askAndCite({ type: 'citation', citation: citation(), confidence: 'low' });
    const badge = await screen.findByText('low confidence');
    expect(badge).toHaveAttribute('data-confidence', 'low');
    expect(
      within(badge.parentElement as HTMLElement).getByRole('button', { name: /Open citation/ }),
    ).toBeInTheDocument();
  });

  it('leaves a high-confidence citation unbadged', async () => {
    await askAndCite({ type: 'citation', citation: citation(), confidence: 'high' });
    await screen.findByRole('button', { name: /Open citation/ });
    expect(screen.queryByText('low confidence')).toBeNull();
  });

  it('writes the shared route state when a citation is clicked', async () => {
    await askAndCite();
    const link = await screen.findByRole('button', { name: /Open citation/ });
    await userEvent.setup().click(link);

    const search = new URLSearchParams(screen.getByTestId('location-search').textContent ?? '');
    expect(search.get('doc')).toBe('hash-afe');
    expect(search.get('part')).toBe('AFE7950');
    expect(search.get('page')).toBe('7');
    // The record's own printed text, not the section heading: searching the
    // page for "4.5 Thermal Characteristics" highlights the heading of a
    // section that may run for pages, never the row the value came from.
    expect(search.get('needle')).toBe('Junction temperature');
  });

  it('falls back to the section when a citation carries no needle', async () => {
    await askAndCite({ type: 'citation', citation: { ...citation(), needle: '' } });
    const link = await screen.findByRole('button', { name: /Open citation/ });
    await userEvent.setup().click(link);

    const search = new URLSearchParams(screen.getByTestId('location-search').textContent ?? '');
    expect(search.get('needle')).toBe('4.5 Thermal Characteristics');
  });

  it('activates from the keyboard, not the mouse alone', async () => {
    await askAndCite();
    const link = await screen.findByRole('button', { name: /Open citation/ });
    link.focus();
    expect(link).toHaveFocus();
    await userEvent.setup().keyboard('{Enter}');

    await waitFor(() =>
      expect(screen.getByTestId('location-search').textContent).toContain('doc=hash-afe'),
    );
  });

  it('does not import the PDF pane', () => {
    const sources = chatSourceFiles();
    expect(Object.keys(sources).length).toBeGreaterThan(0);
    for (const [file, text] of Object.entries(sources)) {
      for (const match of text.matchAll(/from\s+'([^']+)'/g)) {
        expect(`${file}: ${match[1]}`).not.toMatch(/pdf/i);
      }
    }
  });
});

// --- restoring and scrolling -------------------------------------------------------------

describe('the transcript', () => {
  it('restores from a saved session on load', async () => {
    installServer({
      session: {
        id: 'saved-1',
        title: 'thermal limits',
        scope: AFE,
        messages: [
          { role: 'user', text: 'how hot?', citations: [], created_at: '2026-01-01T00:00:00Z' },
          {
            role: 'assistant',
            text: '125 °C junction maximum.',
            citations: [citation()],
            created_at: '2026-01-01T00:00:01Z',
          },
        ],
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:01Z',
        n_messages: 2,
      },
    });
    renderPane({}, ['/chat?session=saved-1']);

    expect(await screen.findByText('how hot?')).toBeInTheDocument();
    expect(screen.getByText('125 °C junction maximum.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Open citation §4.5, p.7/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /AFE7950/ })).toHaveAttribute(
      'data-scope-name',
      'AFE7950',
    );
  });

  it('anchors to the newest token, and stops when the user scrolls up', async () => {
    const server = installServer();
    renderPane({ sessionId: 's1' });
    await settled();

    const transcript = screen.getByTestId('chat-transcript');
    Object.defineProperty(transcript, 'scrollHeight', { configurable: true, get: () => 4000 });
    Object.defineProperty(transcript, 'clientHeight', { configurable: true, get: () => 400 });

    await ask('how hot can it run?');
    await waitFor(() => expect(server.streams.length).toBe(1));
    await server.lastStream().push(frame({ type: 'token', text: 'first token' }));
    expect(transcript.scrollTop).toBe(4000);

    // The user scrolls up to re-read something. The pin must yield.
    transcript.scrollTop = 100;
    fireEvent.scroll(transcript);
    await server.lastStream().push(frame({ type: 'token', text: ' second token' }));
    expect(transcript.scrollTop).toBe(100);

    // Back at the bottom, the pin is taken again.
    transcript.scrollTop = 3600;
    fireEvent.scroll(transcript);
    await server.lastStream().push(frame({ type: 'token', text: ' third token' }));
    expect(transcript.scrollTop).toBe(4000);
  });
});
