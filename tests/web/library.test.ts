/**
 * Ticket 20 — the Library, labels and Sessions screens.
 *
 * The API client is mocked module-wide: these tests exercise the screens'
 * behaviour, never a backend, and never a browser beyond jsdom. Two of the
 * assertions are made against the source files rather than the DOM — that no
 * copy of `ApplicabilityControl` exists in this directory, and that no screen
 * hand-builds a `fetch` — because both are properties of the code that cannot
 * be observed by rendering it.
 *
 * No JSX: the file is `.ts` (the path the ticket owns), so every element is
 * built with `createElement`.
 */
// This file lives outside the Vite root (`web/`), and the repository has no
// root-level `node_modules`, so a bare specifier does not resolve from here:
// the packages are addressed by path until the scaffold grows an alias.
// `describe`/`it`/`expect`/`beforeEach`/`vi` need no import — `test.globals`
// is on.
import { render, screen, waitFor, within } from '../../web/node_modules/@testing-library/react';
import userEvent from '../../web/node_modules/@testing-library/user-event';
import { createElement } from '../../web/src/test-kit';
import type { ComponentType, ReactNode } from '../../web/src/test-kit';
import { MemoryRouter, useLocation } from '../../web/node_modules/react-router-dom';

import { ApiError } from '../../web/src/api/client';
import type {
  Applicability,
  LibraryDocumentOut,
  LibraryOut,
  ProjectOut,
  SessionOut,
  SessionSummary,
  SessionsOut,
} from '../../web/src/api/types';
import { DocumentRow } from '../../web/src/routes/library/DocumentRow';
import { LibraryScreen } from '../../web/src/routes/library/route';
import type { ApplicabilityControlProps } from '../../web/src/routes/library/shellPrimitives';
import {
  addLabel,
  collectLabels,
  collectParts,
  filterDocuments,
  labelSuggestions,
  rebuildOffer,
  removeLabel,
  validateApplicability,
} from '../../web/src/routes/library/state';
import { downloadText } from '../../web/src/routes/sessions/download';
import { SessionsScreen } from '../../web/src/routes/sessions/route';
import {
  chatRestoreUrl,
  exportDescription,
  exportFilename,
  sortSessions,
} from '../../web/src/routes/sessions/state';

vi.mock('../../web/src/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../web/src/api/client')>();
  return {
    ...actual,
    getLibrary: vi.fn(),
    patchLibraryDocument: vi.fn(),
    listSessions: vi.fn(),
    getSession: vi.fn(),
    exportSession: vi.fn(),
    getProjects: vi.fn(),
    createProject: vi.fn(),
    addProjectParts: vi.fn(),
    removeProjectPart: vi.fn(),
  };
});

import * as client from '../../web/src/api/client';

const getLibrary = vi.mocked(client.getLibrary);
const patchLibraryDocument = vi.mocked(client.patchLibraryDocument);
const listSessions = vi.mocked(client.listSessions);
const getSession = vi.mocked(client.getSession);
const exportSession = vi.mocked(client.exportSession);
const getProjects = vi.mocked(client.getProjects);
const createProject = vi.mocked(client.createProject);
const addProjectParts = vi.mocked(client.addProjectParts);
const removeProjectPart = vi.mocked(client.removeProjectPart);

/** A project row, as `GET /api/projects` returns it. */
function projectOut(name: string, parts: string[] = []): ProjectOut {
  return {
    name,
    parts: parts.map((part_number) => ({ part_number, role: '', built: true })),
    interfaces: '',
    notes: '',
    built: false,
    error: '',
  };
}

// --- fixtures -----------------------------------------------------------------

function applicability(over: Partial<Applicability> = {}): Applicability {
  return { kind: 'all', parts: [], family: '', evidence: '', ...over };
}

function libraryDocument(over: Partial<LibraryDocumentOut> = {}): LibraryDocumentOut {
  return {
    content_hash: 'aaa111',
    path: '/shelf/lmx1204.pdf',
    filename: 'lmx1204.pdf',
    part_number: 'LMX1204',
    doc_type: 'datasheet',
    vendor: 'Texas Instruments',
    page_count: 84,
    applicability: applicability({
      kind: 'parts',
      parts: ['LMX1204'],
      evidence: 'title block names LMX1204',
    }),
    labels: ['reviewed'],
    added_at: '2026-08-01T09:00:00Z',
    parts_reached: ['LMX1204'],
    unbuilt_parts: [],
    rebuild_needed: [],
    ...over,
  };
}

const DATASHEET = libraryDocument();

const APPNOTE = libraryDocument({
  content_hash: 'bbb222',
  path: '/shelf/afe79xx-appnote.pdf',
  filename: 'afe79xx-appnote.pdf',
  part_number: 'AFE7950',
  doc_type: 'application note',
  page_count: 12,
  applicability: applicability({
    kind: 'family',
    family: 'AFE79xx',
    evidence: 'the abstract covers the AFE79xx family',
  }),
  labels: ['thermal'],
  parts_reached: ['AFE7950', 'AFE7951'],
  unbuilt_parts: ['AFE7951'],
  rebuild_needed: [],
});

function libraryOut(over: Partial<LibraryOut> = {}): LibraryOut {
  const documents = over.documents ?? [DATASHEET, APPNOTE];
  return {
    documents,
    count: documents.length,
    labels: over.labels ?? ['jesd204', 'reviewed', 'thermal'],
    ...over,
  };
}

function sessionSummary(over: Partial<SessionSummary> = {}): SessionSummary {
  return {
    id: 's1',
    title: 'LMX1204 phase noise',
    scope: { kind: 'part', name: 'LMX1204' },
    n_messages: 4,
    created_at: '2026-08-10T10:00:00Z',
    updated_at: '2026-08-10T10:30:00Z',
    ...over,
  };
}

function sessionOut(over: Partial<SessionOut> = {}): SessionOut {
  return {
    id: 's1',
    title: 'LMX1204 phase noise',
    scope: { kind: 'part', name: 'LMX1204' },
    messages: [
      {
        role: 'user',
        text: 'What is the additive phase noise at 100 kHz?',
        citations: [],
        created_at: '2026-08-10T10:00:00Z',
      },
      {
        role: 'assistant',
        text: '-152 dBc/Hz.',
        citations: [
          {
            doc: 'lmx1204.pdf',
            doc_hash: 'aaa111',
            section: '7.5',
            page_start: 22,
            page_end: 22,
            part: 'LMX1204',
            pages: 'p.22',
            label: '§7.5, p.22',
            needle: 'Phase noise',
          },
        ],
        created_at: '2026-08-10T10:01:00Z',
      },
    ],
    created_at: '2026-08-10T10:00:00Z',
    updated_at: '2026-08-10T10:30:00Z',
    n_messages: 2,
    ...over,
  };
}

function sessionsOut(sessions: SessionSummary[]): SessionsOut {
  return { sessions, count: sessions.length };
}

/**
 * A stand-in for the shell's `ApplicabilityControl` (ticket 16).
 *
 * The screen is given the control rather than importing one, so this stub
 * exercises exactly the seam the shell will fill: a controlled value plus an
 * `onChange`. It is a test double and lives here, not in `src/`.
 */
function stubControl(next: Applicability): ComponentType<ApplicabilityControlProps> {
  return function StubApplicabilityEditor({
    value,
    onChange,
    label: name,
  }: ApplicabilityControlProps) {
    return createElement(
      'div',
      null,
      createElement('span', null, `control shows ${value.kind}`),
      createElement(
        'button',
        { type: 'button', onClick: () => onChange(next) },
        `Edit ${name ?? 'applicability'}`,
      ),
    );
  };
}

function LocationProbe() {
  const location = useLocation();
  return createElement('div', { 'data-testid': 'location' }, `${location.pathname}${location.search}`);
}

function routed(children: ReactNode) {
  return createElement(
    MemoryRouter,
    { initialEntries: ['/sessions'] },
    children,
    createElement(LocationProbe),
  );
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

beforeEach(() => {
  vi.clearAllMocks();
  getLibrary.mockResolvedValue(libraryOut());
  patchLibraryDocument.mockResolvedValue(DATASHEET);
  listSessions.mockResolvedValue(sessionsOut([sessionSummary()]));
  getSession.mockResolvedValue(sessionOut());
  exportSession.mockResolvedValue('# exported\n');
  getProjects.mockResolvedValue({ projects: [projectOut('LNA front-end', ['AFE7950'])], count: 1 });
  createProject.mockImplementation(async ({ name }) => projectOut(name));
  addProjectParts.mockImplementation(async (name, body) =>
    projectOut(name, ['AFE7950', ...body.parts]),
  );
  removeProjectPart.mockImplementation(async (name) => projectOut(name));
});

// --- the library model ---------------------------------------------------------

describe('library model', () => {
  it('rejects an applicability that cannot mean anything and accepts the three that can', () => {
    expect(validateApplicability(applicability({ kind: 'parts', parts: [] }))).toMatch(/at least one part/i);
    expect(validateApplicability(applicability({ kind: 'parts', parts: ['  '] }))).toMatch(/at least one part/i);
    expect(validateApplicability(applicability({ kind: 'family', family: '  ' }))).toMatch(/family prefix/i);
    expect(validateApplicability(applicability({ kind: 'parts', parts: ['LMX1204'] }))).toBe('');
    expect(validateApplicability(applicability({ kind: 'family', family: 'AFE79xx' }))).toBe('');
    expect(validateApplicability(applicability({ kind: 'all' }))).toBe('');
  });

  it('filters by label and by part, independently and together', () => {
    const documents = [DATASHEET, APPNOTE];
    expect(filterDocuments(documents, { label: 'thermal', part: '' })).toEqual([APPNOTE]);
    expect(filterDocuments(documents, { label: '', part: 'LMX1204' })).toEqual([DATASHEET]);
    expect(filterDocuments(documents, { label: 'thermal', part: 'AFE7951' })).toEqual([APPNOTE]);
    expect(filterDocuments(documents, { label: 'thermal', part: 'LMX1204' })).toEqual([]);
    expect(filterDocuments(documents, { label: '', part: '' })).toEqual(documents);
  });

  it('collects the labels and parts the filters offer', () => {
    expect(collectLabels([DATASHEET, APPNOTE], ['jesd204'])).toEqual([
      'jesd204',
      'reviewed',
      'thermal',
    ]);
    expect(collectParts([DATASHEET, APPNOTE])).toEqual(['AFE7950', 'AFE7951', 'LMX1204']);
  });

  it('adds and removes labels case-insensitively without duplicating them', () => {
    expect(addLabel(['reviewed'], 'thermal')).toEqual(['reviewed', 'thermal']);
    expect(addLabel(['reviewed'], '  Reviewed ')).toEqual(['reviewed']);
    expect(addLabel(['reviewed'], '   ')).toEqual(['reviewed']);
    expect(removeLabel(['reviewed', 'thermal'], 'REVIEWED')).toEqual(['thermal']);
  });

  it('suggests labels already in use, minus the ones the document has', () => {
    const known = ['jesd204', 'reviewed', 'thermal'];
    expect(labelSuggestions(known, ['reviewed'], '')).toEqual(['jesd204', 'thermal']);
    expect(labelSuggestions(known, ['reviewed'], 'the')).toEqual(['thermal']);
    expect(labelSuggestions(known, ['reviewed', 'thermal'], 'the')).toEqual([]);
  });

  it('phrases rebuild_needed as an offer that names the parts', () => {
    expect(rebuildOffer([])).toBe('');
    expect(rebuildOffer(['AFE7951'])).toContain('AFE7951');
    expect(rebuildOffer(['AFE7951', 'AFE7952'])).toContain('AFE7951, AFE7952');
  });
});

// --- the library screen --------------------------------------------------------

describe('library screen', () => {
  it('shows a loading state, then lists every document with applicability, labels and reach', async () => {
    const pending = deferred<LibraryOut>();
    getLibrary.mockReturnValue(pending.promise);

    render(createElement(LibraryScreen));
    expect(screen.getByRole('status')).toHaveTextContent(/loading the library/i);

    pending.resolve(libraryOut());

    const datasheet = await screen.findByRole('article', { name: 'Document lmx1204.pdf' });
    expect(within(datasheet).getByText('Parts: LMX1204')).toBeInTheDocument();
    expect(within(datasheet).getByText(/title block names LMX1204/)).toBeInTheDocument();
    expect(within(datasheet).getByText('reviewed')).toBeInTheDocument();

    // The shelf is part-first now, so a family appnote is listed under every
    // part it reaches — that is ADR 0005's relation working, not duplication.
    // Scope the assertion to one part rather than expecting a single row.
    const appnotes = screen.getAllByRole('article', {
      name: 'Document afe79xx-appnote.pdf',
    });
    expect(appnotes.length).toBeGreaterThan(1);
    const appnote = appnotes[0];
    expect(within(appnote).getByText('Family: AFE79xx')).toBeInTheDocument();
    expect(within(appnote).getByText('thermal')).toBeInTheDocument();
    const reach = within(appnote).getByRole('region', {
      name: 'Parts reached by afe79xx-appnote.pdf',
    });
    expect(reach).toHaveTextContent('AFE7950');
    expect(reach).toHaveTextContent('AFE7951 — unbuilt');
  });

  it('groups the shelf by part, one collapsed row each', async () => {
    render(createElement(LibraryScreen));
    await screen.findByRole('article', { name: 'Document lmx1204.pdf' });

    const parts = document.querySelectorAll('.library-part');
    const names = [...parts].map((row) => row.getAttribute('data-part'));
    expect(names).toContain('LMX1204');
    expect(names).toContain('AFE7950');
    // A part nothing has been built for is still listed, marked unbuilt,
    // rather than hidden.
    expect(names).toContain('AFE7951');
    const unbuilt = document.querySelector('.library-part[data-part="AFE7951"]');
    expect(unbuilt?.getAttribute('data-built')).toBe('false');
  });

  it('shows an empty state when nothing has been analyzed yet', async () => {
    getLibrary.mockResolvedValue(libraryOut({ documents: [], count: 0, labels: [] }));
    render(createElement(LibraryScreen));
    expect(await screen.findByText(/the library is empty/i)).toBeInTheDocument();
  });

  it("renders the server's own message when the library cannot be read, and retries", async () => {
    getLibrary.mockRejectedValueOnce(new ApiError(500, 'library store is unreadable'));
    const user = userEvent.setup();

    render(createElement(LibraryScreen));
    expect(await screen.findByRole('alert')).toHaveTextContent('library store is unreadable');

    getLibrary.mockResolvedValue(libraryOut());
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('article', { name: 'Document lmx1204.pdf' })).toBeInTheDocument();
  });

  it('filters the list by label and by part', async () => {
    const user = userEvent.setup();
    render(createElement(LibraryScreen));
    await screen.findByRole('article', { name: 'Document lmx1204.pdf' });

    await user.selectOptions(screen.getByLabelText('Filter by label'), 'thermal');
    expect(screen.queryByRole('article', { name: 'Document lmx1204.pdf' })).not.toBeInTheDocument();
    expect(
      screen.getAllByRole('article', { name: 'Document afe79xx-appnote.pdf' }).length,
    ).toBeGreaterThan(0);

    await user.click(screen.getByRole('button', { name: 'Clear filters' }));
    await user.selectOptions(screen.getByLabelText('Filter by part'), 'LMX1204');
    expect(screen.getByRole('article', { name: 'Document lmx1204.pdf' })).toBeInTheDocument();
    expect(
      screen.queryByRole('article', { name: 'Document afe79xx-appnote.pdf' }),
    ).not.toBeInTheDocument();
  });

  it('persists an applicability edit through PATCH and re-renders the reach it produced', async () => {
    const widened = applicability({
      kind: 'parts',
      parts: ['LMX1204', 'LMX1205'],
      evidence: 'title block names LMX1204',
    });
    const patched = libraryDocument({
      applicability: widened,
      parts_reached: ['LMX1204', 'LMX1205'],
      unbuilt_parts: ['LMX1205'],
      rebuild_needed: ['LMX1205'],
    });
    patchLibraryDocument.mockResolvedValue(patched);
    const user = userEvent.setup();

    render(createElement(LibraryScreen, { applicabilityControl: stubControl(widened) }));
    const row = await screen.findByRole('article', { name: 'Document lmx1204.pdf' });

    await user.click(
      within(row).getByRole('button', { name: 'Edit Applicability of lmx1204.pdf' }),
    );
    await user.click(
      within(row).getByRole('button', { name: 'Save applicability for lmx1204.pdf' }),
    );

    await waitFor(() => expect(patchLibraryDocument).toHaveBeenCalledTimes(1));
    expect(patchLibraryDocument).toHaveBeenCalledWith('aaa111', {
      applicability: {
        kind: 'parts',
        parts: ['LMX1204', 'LMX1205'],
        family: '',
        evidence: 'title block names LMX1204',
      },
    });

    // Widening to a part that does not exist yet is legal (ADR 0005): the new
    // part is shown as unbuilt, and rebuild_needed becomes a named offer.
    expect(await within(row).findByText('Parts: LMX1204, LMX1205')).toBeInTheDocument();
    const reach = within(row).getByRole('region', { name: 'Parts reached by lmx1204.pdf' });
    expect(reach).toHaveTextContent('LMX1205 — unbuilt');
    const offer = within(row).getByText(/LMX1205/, { selector: '.library-offer' });
    expect(offer).toHaveTextContent(/build LMX1205/i);
  });

  it('blocks an invalid applicability in the UI before it reaches the server', async () => {
    const user = userEvent.setup();
    render(
      createElement(LibraryScreen, {
        applicabilityControl: stubControl(applicability({ kind: 'parts', parts: [] })),
      }),
    );
    const row = await screen.findByRole('article', { name: 'Document lmx1204.pdf' });

    await user.click(
      within(row).getByRole('button', { name: 'Edit Applicability of lmx1204.pdf' }),
    );
    await user.click(
      within(row).getByRole('button', { name: 'Save applicability for lmx1204.pdf' }),
    );

    expect(within(row).getByRole('alert')).toHaveTextContent(/at least one part/i);
    expect(patchLibraryDocument).not.toHaveBeenCalled();
  });

  it('adds a label inline, autocompleting from the labels already in use', async () => {
    patchLibraryDocument.mockResolvedValue(
      libraryDocument({ labels: ['reviewed', 'thermal'] }),
    );
    const user = userEvent.setup();

    render(createElement(LibraryScreen));
    const row = await screen.findByRole('article', { name: 'Document lmx1204.pdf' });

    // The datalist offers every label in use that this document lacks.
    const input = within(row).getByLabelText('Add a label to lmx1204.pdf');
    const listId = input.getAttribute('list') ?? '';
    const options = Array.from(
      row.ownerDocument.getElementById(listId)?.querySelectorAll('option') ?? [],
    ).map((option) => option.getAttribute('value'));
    expect(options).toEqual(['jesd204', 'thermal']);

    await user.type(input, 'the');
    const suggestion = within(row).getByRole('button', {
      name: 'Apply label thermal to lmx1204.pdf',
    });
    await user.click(suggestion);

    await waitFor(() =>
      expect(patchLibraryDocument).toHaveBeenCalledWith('aaa111', {
        labels: ['reviewed', 'thermal'],
      }),
    );
    expect(await within(row).findByText('thermal')).toBeInTheDocument();
  });

  it('adds a brand-new label from the form and removes a label in one action', async () => {
    patchLibraryDocument.mockResolvedValue(libraryDocument({ labels: ['reviewed', 'errata'] }));
    const user = userEvent.setup();

    render(createElement(LibraryScreen));
    const row = await screen.findByRole('article', { name: 'Document lmx1204.pdf' });

    await user.type(within(row).getByLabelText('Add a label to lmx1204.pdf'), 'errata');
    await user.click(within(row).getByRole('button', { name: 'Add label to lmx1204.pdf' }));
    await waitFor(() =>
      expect(patchLibraryDocument).toHaveBeenCalledWith('aaa111', {
        labels: ['reviewed', 'errata'],
      }),
    );
    expect(await within(row).findByText('errata')).toBeInTheDocument();

    // Removing is one action per label, and the patch carries what is left.
    patchLibraryDocument.mockResolvedValue(libraryDocument({ labels: ['errata'] }));
    await user.click(
      within(row).getByRole('button', { name: 'Remove label reviewed from lmx1204.pdf' }),
    );
    await waitFor(() =>
      expect(patchLibraryDocument).toHaveBeenLastCalledWith('aaa111', { labels: ['errata'] }),
    );
    await waitFor(() => expect(within(row).queryByText('reviewed')).not.toBeInTheDocument());

    patchLibraryDocument.mockResolvedValue(libraryDocument({ labels: [] }));
    await user.click(
      within(row).getByRole('button', { name: 'Remove label errata from lmx1204.pdf' }),
    );
    await waitFor(() =>
      expect(patchLibraryDocument).toHaveBeenLastCalledWith('aaa111', { labels: [] }),
    );
    expect(await within(row).findByText(/no labels yet/i)).toBeInTheDocument();
  });

  it("renders the server's message when a patch is refused", async () => {
    patchLibraryDocument.mockRejectedValue(new ApiError(404, 'no document with that hash'));
    const user = userEvent.setup();

    render(
      createElement(DocumentRow, {
        document: DATASHEET,
        knownLabels: ['reviewed'],
        applicabilityControl: null,
        onPatched: vi.fn(),
      }),
    );

    await user.type(screen.getByLabelText('Add a label to lmx1204.pdf'), 'errata');
    await user.click(screen.getByRole('button', { name: 'Add label to lmx1204.pdf' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('no document with that hash');
  });

  it('falls back to read-only applicability when the shell control is absent', async () => {
    render(createElement(LibraryScreen, { applicabilityControl: null }));
    const row = await screen.findByRole('article', { name: 'Document lmx1204.pdf' });
    expect(within(row).getByText(/read-only/i)).toBeInTheDocument();
    expect(
      within(row).queryByRole('button', { name: 'Save applicability for lmx1204.pdf' }),
    ).not.toBeInTheDocument();
  });
});

// --- the sessions model --------------------------------------------------------

describe('sessions model', () => {
  it('orders sessions newest first, with an undated one last', () => {
    const ordered = sortSessions([
      sessionSummary({ id: 'old', title: 'old', updated_at: '2026-08-01T00:00:00Z' }),
      sessionSummary({ id: 'none', title: 'none', created_at: null, updated_at: null }),
      sessionSummary({ id: 'new', title: 'new', updated_at: '2026-08-12T00:00:00Z' }),
    ]);
    expect(ordered.map((session) => session.id)).toEqual(['new', 'old', 'none']);
  });

  it('names the golden export exactly as the fixture it becomes', () => {
    const session = sessionSummary();
    expect(exportFilename(session, 'golden')).toBe('golden_qa_LMX1204.yaml');
    expect(exportFilename(session, 'markdown')).toBe('session-lmx1204-phase-noise.md');
    expect(exportDescription('golden')).toMatch(/golden_qa_<PART>\.yaml/);
    expect(exportDescription('golden')).toMatch(/regression test/i);
  });

  it('hands a session to the chat pane through the URL, not through an import', () => {
    expect(chatRestoreUrl('s 1')).toBe('/chat?session=s%201');
  });

  it('downloads text as a file without touching the network', () => {
    const created = vi.fn(() => 'blob:mock');
    const revoked = vi.fn();
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    Object.defineProperty(URL, 'createObjectURL', { value: created, configurable: true });
    Object.defineProperty(URL, 'revokeObjectURL', { value: revoked, configurable: true });

    downloadText('golden_qa_LMX1204.yaml', '- question: x\n', 'application/yaml');

    expect(created).toHaveBeenCalledTimes(1);
    expect(clicked).toHaveBeenCalledTimes(1);
    expect(revoked).toHaveBeenCalledWith('blob:mock');
    clicked.mockRestore();
  });
});

// --- the sessions screen -------------------------------------------------------

describe('sessions screen', () => {
  it('shows a loading state, then lists sessions newest first with scope and message count', async () => {
    const pending = deferred<SessionsOut>();
    listSessions.mockReturnValue(pending.promise);

    render(routed(createElement(SessionsScreen)));
    expect(screen.getByRole('status')).toHaveTextContent(/loading saved conversations/i);

    pending.resolve(
      sessionsOut([
        sessionSummary({ id: 'older', title: 'AFE7950 JESD204C lanes', updated_at: '2026-08-02T00:00:00Z' }),
        sessionSummary({ id: 'newer', title: 'LMX1204 phase noise', updated_at: '2026-08-09T00:00:00Z' }),
      ]),
    );

    const rows = await screen.findAllByRole('article');
    expect(rows.map((row) => within(row).getByRole('heading').textContent)).toEqual([
      'LMX1204 phase noise',
      'AFE7950 JESD204C lanes',
    ]);
    expect(within(rows[0]).getByText('part LMX1204')).toBeInTheDocument();
    expect(within(rows[0]).getByText('4 messages')).toBeInTheDocument();
  });

  it('shows an empty state when nothing has been saved', async () => {
    listSessions.mockResolvedValue(sessionsOut([]));
    render(routed(createElement(SessionsScreen)));
    expect(await screen.findByText(/no saved conversations yet/i)).toBeInTheDocument();
  });

  it("renders the server's own message when the list cannot be read", async () => {
    listSessions.mockRejectedValue(new ApiError(500, 'sessions directory is unreadable'));
    render(routed(createElement(SessionsScreen)));
    expect(await screen.findByRole('alert')).toHaveTextContent('sessions directory is unreadable');
  });

  it('opens a session: loads the transcript and points the chat pane at it', async () => {
    const user = userEvent.setup();
    render(routed(createElement(SessionsScreen)));
    await screen.findByRole('article', { name: 'Session LMX1204 phase noise' });

    await user.click(
      screen.getByRole('button', { name: 'Open LMX1204 phase noise in the chat pane' }),
    );

    await waitFor(() => expect(getSession).toHaveBeenCalledWith('s1'));
    expect(screen.getByTestId('location')).toHaveTextContent('/chat?session=s1');
    expect(await screen.findByText(/restoring 2 messages/i)).toBeInTheDocument();
  });

  it('reports an unreadable session where the user clicked', async () => {
    getSession.mockRejectedValue(new ApiError(404, 'no session with that id'));
    const user = userEvent.setup();

    render(routed(createElement(SessionsScreen)));
    await screen.findByRole('article', { name: 'Session LMX1204 phase noise' });
    await user.click(
      screen.getByRole('button', { name: 'Open LMX1204 phase noise in the chat pane' }),
    );

    expect(await screen.findByRole('alert')).toHaveTextContent('no session with that id');
    expect(screen.getByTestId('location')).toHaveTextContent('/sessions');
  });

  it('downloads both export formats, and says what the golden one is for', async () => {
    const download = vi.fn();
    const user = userEvent.setup();
    exportSession.mockImplementation(async (_id, format) =>
      format === 'golden' ? '- question: x\n' : '# LMX1204 phase noise\n',
    );

    render(routed(createElement(SessionsScreen, { download })));
    await screen.findByRole('article', { name: 'Session LMX1204 phase noise' });

    await user.click(
      screen.getByRole('button', { name: 'Export markdown for LMX1204 phase noise' }),
    );
    await waitFor(() => expect(exportSession).toHaveBeenCalledWith('s1', 'markdown'));
    expect(download).toHaveBeenCalledWith(
      'session-lmx1204-phase-noise.md',
      '# LMX1204 phase noise\n',
      'text/markdown',
    );

    await user.click(
      screen.getByRole('button', {
        name: 'Export golden Q&A fixture for LMX1204 phase noise',
      }),
    );
    await waitFor(() => expect(exportSession).toHaveBeenCalledWith('s1', 'golden'));
    expect(download).toHaveBeenLastCalledWith(
      'golden_qa_LMX1204.yaml',
      '- question: x\n',
      'application/yaml',
    );

    // The second format has to say what it is for, or nobody finds it.
    expect(screen.getByText(/golden_qa_<PART>\.yaml/)).toHaveTextContent(/regression test/i);
  });

  it("renders the server's message when an export fails", async () => {
    exportSession.mockRejectedValue(new ApiError(500, 'that session has no answers to export'));
    const user = userEvent.setup();

    render(routed(createElement(SessionsScreen, { download: vi.fn() })));
    await screen.findByRole('article', { name: 'Session LMX1204 phase noise' });
    await user.click(
      screen.getByRole('button', { name: 'Export markdown for LMX1204 phase noise' }),
    );
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'that session has no answers to export',
    );
  });
});

// --- properties of the source, not of the render -------------------------------

/**
 * Every file this ticket owns, read as text through Vite's `?raw` rather than
 * `node:fs` — the same resolver the application is built with, and no Node
 * types needed in a file that has none available.
 */
const OWNED_SOURCES = import.meta.glob<string>(
  ['../../web/src/routes/library/*.{ts,tsx}', '../../web/src/routes/sessions/*.{ts,tsx}'],
  { query: '?raw', import: 'default', eager: true },
);

function ownedSources(): { file: string; source: string }[] {
  return Object.entries(OWNED_SOURCES).map(([file, source]) => ({ file, source }));
}

describe('screen source', () => {
  it('reads every file the ticket owns', () => {
    expect(ownedSources().length).toBeGreaterThanOrEqual(6);
  });

  it('keeps no local copy of ApplicabilityControl — the shell owns it', () => {
    for (const { file, source } of ownedSources()) {
      expect(source, file).not.toMatch(/(function|const|class)\s+ApplicabilityControl\b/);
    }
    const [, shellSeam] =
      ownedSources()
        .map(({ file, source }): [string, string] => [file, source])
        .find(([file]) => file.endsWith('library/shellPrimitives.ts')) ?? ['', ''];
    expect(shellSeam).toContain("import.meta.glob<ShellModule>('../../shell/**/*.{ts,tsx}'");
    expect(shellSeam).toMatch(/ApplicabilityControl/);
  });

  it('routes every server call through api/client.ts', () => {
    let importsTheClient = 0;
    for (const { file, source } of ownedSources()) {
      expect(source, file).not.toMatch(/\bfetch\s*\(/);
      expect(source, file).not.toMatch(/['"`]\/api\//);
      expect(source, file).not.toMatch(/new\s+EventSource\b/);
      if (source.includes("from '../../api/client'")) importsTheClient += 1;
    }
    expect(importsTheClient).toBeGreaterThanOrEqual(2);
  });
});

// --- the working set -----------------------------------------------------------

describe('the working set', () => {
  it('narrows the shelf to the selected project, and widens again', async () => {
    const user = userEvent.setup();
    render(createElement(LibraryScreen));
    await screen.findByRole('article', { name: 'Document lmx1204.pdf' });

    await user.selectOptions(screen.getByLabelText('Working set'), 'LNA front-end');

    // The project holds AFE7950 only, so LMX1204 leaves the view — without
    // anything being deleted.
    await waitFor(() => {
      expect(document.querySelector('.library-part[data-part="AFE7950"]')).not.toBeNull();
    });
    expect(document.querySelector('.library-part[data-part="LMX1204"]')).toBeNull();

    await user.selectOptions(screen.getByLabelText('Working set'), '');
    await waitFor(() => {
      expect(document.querySelector('.library-part[data-part="LMX1204"]')).not.toBeNull();
    });
  });

  it('creates a project and selects it', async () => {
    const user = userEvent.setup();
    render(createElement(LibraryScreen));
    await screen.findByRole('article', { name: 'Document lmx1204.pdf' });

    await user.type(screen.getByLabelText('New project name'), 'mixer chain');
    await user.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() => expect(createProject).toHaveBeenCalledWith({ name: 'mixer chain' }));
    expect(screen.getByLabelText('Working set')).toHaveValue('mixer chain');
  });

  it('adds a part to the working set and drops one from it', async () => {
    const user = userEvent.setup();
    render(createElement(LibraryScreen));
    await screen.findByRole('article', { name: 'Document lmx1204.pdf' });
    await user.selectOptions(screen.getByLabelText('Working set'), 'LNA front-end');

    await user.selectOptions(screen.getByLabelText('Add a part to LNA front-end'), 'LMX1204');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    await waitFor(() =>
      expect(addProjectParts).toHaveBeenCalledWith('LNA front-end', { parts: ['LMX1204'] }),
    );

    await user.click(await screen.findByRole('button', { name: /Remove AFE7950 from this project/ }));
    await waitFor(() =>
      expect(removeProjectPart).toHaveBeenCalledWith('LNA front-end', 'AFE7950'),
    );
  });

  it('stays usable when projects cannot be read', async () => {
    getProjects.mockRejectedValueOnce(new ApiError(500, 'projects dir is unreadable'));
    render(createElement(LibraryScreen));

    // The shelf still renders; only the working-set control reports trouble.
    expect(await screen.findByRole('article', { name: 'Document lmx1204.pdf' })).toBeInTheDocument();
    expect(await screen.findByRole('alert')).toHaveTextContent('projects dir is unreadable');
  });
});
