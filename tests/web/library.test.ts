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
  PartOut,
  ProjectOut,
  SessionOut,
  ShelfDocument,
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
    startAnalyze: vi.fn(),
    addToShelf: vi.fn(),
    getCategories: vi.fn(),
    getParts: vi.fn(),
    createCategory: vi.fn(),
    renameCategory: vi.fn(),
    removeCategory: vi.fn(),
    setPartCategory: vi.fn(),
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
const startAnalyze = vi.mocked(client.startAnalyze);
const addToShelf = vi.mocked(client.addToShelf);
const getCategories = vi.mocked(client.getCategories);
const getParts = vi.mocked(client.getParts);
const createCategory = vi.mocked(client.createCategory);
const setPartCategory = vi.mocked(client.setPartCategory);

/** A catalog row, as `GET /api/parts` returns it. */
function partOut(part_number: string, category: string, built = true): PartOut {
  return {
    part_number,
    built,
    revision: '',
    vendor: '',
    backends: [],
    sections: 0,
    specs: 0,
    plots: 0,
    tokens: 0,
    searchable: false,
    spec_confidence: {},
    plot_confidence: {},
    category,
    category_confirmed: false,
  };
}

/** A project row, as `GET /api/projects` returns it. */
function projectOut(name: string, parts: string[] = []): ProjectOut {
  return {
    name,
    parts: parts.map((part_number) => ({ part_number, role: '', built: true })),
    interfaces: '',
    notes: '',
    directory: '',
    excluded: [],
    built: false,
    error: '',
  };
}

/**
 * Render the Library inside a Router.
 *
 * The screen navigates to the Analyze run view when a part is built, so
 * `useNavigate` needs a router context. Wrapping here rather than at thirteen
 * call sites keeps the tests reading as tests.
 */
function renderLibrary(props: Parameters<typeof LibraryScreen>[0] = {}) {
  return render(
    createElement(
      MemoryRouter,
      null,
      createElement(LibraryScreen, props),
      // The screen navigates to the run view after a build; the probe is how
      // that is observed without asserting on router internals.
      createElement(LocationProbe),
    ),
  );
}

/** A `ShelfDocument`, as `POST /api/projects/{name}/shelf` returns one. */
function shelfDocument(over: Partial<ShelfDocument> = {}): ShelfDocument {
  return {
    filename: 'away.pdf',
    path: '/shelf/radar/away.pdf',
    relative_dir: '',
    content_hash: 'ccc333',
    processed: true,
    part_number: 'AD9081',
    parts_reached: ['AD9081'],
    labels: [],
    page_count: 12,
    excluded: false,
    ...over,
  };
}

// --- fixtures -----------------------------------------------------------------

function applicability(over: Partial<Applicability> = {}): Applicability {
  return { kind: 'all', parts: [], family: '', category: '', evidence: '', ...over };
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
    revision_state: {
      staleness: 'unknown',
      checked_at: null,
      upstream_revision: '',
      upstream_sha256: '',
      content_drift: false,
      note: '',
    },
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
    category: '',
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
  startAnalyze.mockResolvedValue({ run_id: 'run-1', n_jobs: 1 });
  addToShelf.mockResolvedValue({
    document: shelfDocument(),
    copied: true,
    renamed: false,
    reason: '',
    parts_added: [],
  });
  // The taxonomy the shelf is filed into, and which category each part is in.
  getCategories.mockResolvedValue({
    categories: [
      { id: 'amplifiers', name: 'Amplifiers', count: 1 },
      { id: 'data-converters', name: 'Data converters', count: 1 },
      { id: 'uncategorized', name: 'Uncategorized', count: 0 },
    ],
    // The filing the Library groups by. It comes from the same part records
    // the counts do, so a category's number always matches what it opens to.
    // AFE7951 is unbuilt and still filed: the map is the part *records*, so
    // a part that is filed but not yet built still appears in its category.
    parts: {
      LMX1204: 'amplifiers',
      AFE7950: 'data-converters',
      AFE7951: 'data-converters',
      AD9081: 'data-converters',
    },
  });
  getParts.mockResolvedValue({
    parts: [
      partOut('LMX1204', 'amplifiers'),
      partOut('AFE7950', 'data-converters'),
      partOut('AFE7951', 'data-converters', false),
      partOut('AD9081', 'data-converters'),
    ],
    count: 4,
  });
  createCategory.mockImplementation(async ({ name }) => ({
    id: name.toLowerCase().replace(/\s+/g, '-'),
    name,
    count: 0,
  }));
  setPartCategory.mockImplementation(async (part_number, body) => ({
    part_number,
    category: body.category,
    evidence: 'set by hand',
    confirmed: true,
    confident: true,
  }));
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
  it('shows a loading state, then the taxonomy and what is filed in it', async () => {
    const pending = deferred<LibraryOut>();
    getLibrary.mockReturnValue(pending.promise);

    renderLibrary();
    expect(screen.getByRole('status')).toHaveTextContent(/loading the library/i);

    pending.resolve(libraryOut());

    // The bookshelf is categories first: a flat list is what made finding a
    // part you used two years ago a search rather than a scan.
    const tree = await screen.findByRole('navigation', { name: 'Categories' });
    expect(within(tree).getByRole('button', { name: /^Amplifiers/ })).toBeInTheDocument();
    expect(within(tree).getByRole('button', { name: /^Data converters/ })).toBeInTheDocument();
    expect(within(tree).getByRole('button', { name: /^Uncategorized/ })).toBeInTheDocument();
  });

  it('lists a category’s parts, and their documents under them', async () => {
    renderLibrary();
    const tree = await screen.findByRole('navigation', { name: 'Categories' });
    await userEvent.setup().click(within(tree).getByRole('button', { name: /^Amplifiers/ }));

    // LMX1204 is filed under amplifiers by the catalog fixture.
    const contents = await screen.findByRole('region', { name: /Contents of Amplifiers/ });
    expect(within(contents).getByText('LMX1204')).toBeInTheDocument();
    expect(within(contents).getByRole('button', { name: /Open lmx1204\.pdf/ })).toBeInTheDocument();
  });

  it('separates supporting documents from a part’s own documents', async () => {
    // A layout note that applies to the whole category and to no part.
    getLibrary.mockResolvedValue(
      libraryOut({
        documents: [
          DATASHEET,
          libraryDocument({
            content_hash: 'sup1',
            path: '/shelf/hf-layout.pdf',
            filename: 'hf-layout.pdf',
            part_number: '',
            parts_reached: [],
            applicability: applicability({
              kind: 'category',
              category: 'amplifiers',
              evidence: 'covers every amplifier',
            }),
          }),
        ],
      }),
    );

    renderLibrary();
    const tree = await screen.findByRole('navigation', { name: 'Categories' });
    await userEvent.setup().click(within(tree).getByRole('button', { name: /^Amplifiers/ }));

    const supporting = await screen.findByRole('region', {
      name: /Supporting documents for Amplifiers/,
    });
    expect(within(supporting).getByText('hf-layout.pdf')).toBeInTheDocument();
    // It is listed once, under the category — not repeated under every part.
    expect(screen.getAllByText('hf-layout.pdf')).toHaveLength(1);
  });

  it('opens a document in the PDF pane when clicked', async () => {
    renderLibrary();
    const tree = await screen.findByRole('navigation', { name: 'Categories' });
    const user = userEvent.setup();
    await user.click(within(tree).getByRole('button', { name: /^Amplifiers/ }));
    await user.click(await screen.findByRole('button', { name: /Open lmx1204\.pdf/ }));

    await waitFor(() =>
      expect(screen.getByTestId('location').textContent).toContain('doc=aaa111'),
    );
  });

  it('edits applicability and labels in a panel, not on every row', async () => {
    const user = userEvent.setup();
    const widened = applicability({ kind: 'all', evidence: 'set by user' });
    patchLibraryDocument.mockResolvedValue(
      libraryDocument({ applicability: widened, parts_reached: ['LMX1204', 'AFE7950'] }),
    );

    renderLibrary({ applicabilityControl: stubControl(widened) });
    const tree = await screen.findByRole('navigation', { name: 'Categories' });
    await user.click(within(tree).getByRole('button', { name: /^Amplifiers/ }));

    // Compact by default: the editor exists only once you ask for it.
    expect(screen.queryByRole('article', { name: 'Document lmx1204.pdf' })).toBeNull();
    await user.click(await screen.findByRole('button', { name: /Edit lmx1204\.pdf/ }));

    const panel = await screen.findByRole('region', { name: /Edit lmx1204\.pdf/ });
    await user.click(within(panel).getByRole('button', { name: /Edit Applicability/ }));
    await user.click(within(panel).getByRole('button', { name: /Save applicability/ }));

    await waitFor(() =>
      expect(patchLibraryDocument).toHaveBeenCalledWith('aaa111', { applicability: widened }),
    );
  });

  it('adds a category and files a part into it', async () => {
    const user = userEvent.setup();
    renderLibrary();
    await screen.findByRole('navigation', { name: 'Categories' });

    await user.type(screen.getByLabelText('New category name'), 'Circulators');
    await user.click(screen.getByRole('button', { name: 'Add category' }));

    await waitFor(() => expect(createCategory).toHaveBeenCalledWith({ name: 'Circulators' }));
  });

  it('shows an empty state when nothing has been analyzed yet', async () => {
    getLibrary.mockResolvedValue(libraryOut({ documents: [], count: 0, labels: [] }));
    renderLibrary();
    expect(await screen.findByText(/the library is empty/i)).toBeInTheDocument();
  });

  it("renders the server's own message when the library cannot be read, and retries", async () => {
    getLibrary.mockRejectedValueOnce(new ApiError(500, 'library store is unreadable'));
    const user = userEvent.setup();

    renderLibrary();
    expect(await screen.findByRole('alert')).toHaveTextContent('library store is unreadable');

    getLibrary.mockResolvedValue(libraryOut());
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('navigation', { name: 'Categories' })).toBeInTheDocument();
  });

  it('stays usable when the taxonomy cannot be read', async () => {
    // A shelf whose categories will not load is still a shelf.
    getCategories.mockRejectedValueOnce(new ApiError(500, 'taxonomy unreadable'));
    renderLibrary();
    expect(await screen.findByRole('alert')).toHaveTextContent('taxonomy unreadable');
    expect(screen.getByRole('heading', { name: 'Library' })).toBeInTheDocument();
  });
});

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
    renderLibrary();
    await screen.findByRole('navigation', { name: 'Categories' });

    await user.selectOptions(screen.getByLabelText('Working set'), 'LNA front-end');

    // The project holds AFE7950 only, so LMX1204 leaves the view — without
    // anything being deleted.
    // LMX1204 lives under amplifiers and is not in this project, so selecting
    // that category shows nothing while the project scopes the shelf.
    const tree = screen.getByRole('navigation', { name: 'Categories' });
    await user.click(within(tree).getByRole('button', { name: /^Amplifiers/ }));
    await waitFor(() => expect(screen.queryByText('lmx1204.pdf')).toBeNull());

    await user.selectOptions(screen.getByLabelText('Working set'), '');
    await waitFor(() => expect(screen.getByText('lmx1204.pdf')).toBeInTheDocument());
  });

  it('creates a project and selects it', async () => {
    const user = userEvent.setup();
    renderLibrary();
    await screen.findByRole('navigation', { name: 'Categories' });

    await user.type(screen.getByLabelText('New project name'), 'mixer chain');
    await user.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() => expect(createProject).toHaveBeenCalledWith({ name: 'mixer chain' }));
    expect(screen.getByLabelText('Working set')).toHaveValue('mixer chain');
  });

  it('adds a part to the working set and drops one from it', async () => {
    const user = userEvent.setup();
    renderLibrary();
    await screen.findByRole('navigation', { name: 'Categories' });
    await user.selectOptions(screen.getByLabelText('Working set'), 'LNA front-end');

    await user.selectOptions(screen.getByLabelText('Add a part to LNA front-end'), 'LMX1204');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    await waitFor(() =>
      expect(addProjectParts).toHaveBeenCalledWith('LNA front-end', { parts: ['LMX1204'] }),
    );

    const tree2 = screen.getByRole('navigation', { name: 'Categories' });
    await user.click(within(tree2).getByRole('button', { name: /^Data converters/ }));
    await user.click(
      await screen.findByRole('button', { name: /Remove AFE7950 from this project/ }),
    );
    await waitFor(() =>
      expect(removeProjectPart).toHaveBeenCalledWith('LNA front-end', 'AFE7950'),
    );
  });

  it('stays usable when projects cannot be read', async () => {
    getProjects.mockRejectedValueOnce(new ApiError(500, 'projects dir is unreadable'));
    renderLibrary();

    // The shelf still renders; only the working-set control reports trouble.
    expect(await screen.findByText('lmx1204.pdf')).toBeInTheDocument();
    expect(await screen.findByRole('alert')).toHaveTextContent('projects dir is unreadable');
  });
});

// --- ticket 30: build an unbuilt part where you meet it --------------------------

describe('a category opens to exactly what it counted', () => {
  it('groups by the part records, so a filed-but-unbuilt part still appears', async () => {
    // The regression: grouping used to come from the parts catalog, which
    // lists only what is *built*. A category could report three parts and
    // open empty. The filing now comes from the same records the counts do.
    renderLibrary();
    const tree = await screen.findByRole('navigation', { name: 'Categories' });
    await userEvent.setup().click(within(tree).getByRole('button', { name: /^Data converters/ }));

    const pane = await screen.findByRole('region', { name: /Contents of Data converters/ });
    expect(within(pane).getByText('AFE7951')).toBeInTheDocument();
  });
});

describe('building an unbuilt part from the library', () => {
  /** AFE7950 and AFE7951 are filed under data converters by the catalog fixture. */
  async function toConverters(): Promise<void> {
    renderLibrary();
    const tree = await screen.findByRole('navigation', { name: 'Categories' });
    await userEvent.setup().click(within(tree).getByRole('button', { name: /^Data converters/ }));
    await screen.findByRole('region', { name: /Contents of Data converters/ });
  }

  it('offers to build an unbuilt part and not a built one', async () => {
    await toConverters();

    // AFE7951 is reached by the appnote but has no corpus.
    expect(
      screen.getByRole('button', { name: /Build AFE7951 from its documents/ }),
    ).toBeInTheDocument();
    // LMX1204 is built, so there is nothing to offer.
    expect(
      screen.queryByRole('button', { name: /Build AFE7950 from its documents/ }),
    ).toBeNull();
  });

  it('sends one proposal per document reaching the part, applicability intact', async () => {
    const user = userEvent.setup();
    startAnalyze.mockResolvedValue({ run_id: 'run-7', n_jobs: 1 });
    await toConverters();

    await user.click(screen.getByRole('button', { name: /Build AFE7951 from its documents/ }));

    await waitFor(() => expect(startAnalyze).toHaveBeenCalledTimes(1));
    const sent = startAnalyze.mock.calls[0][0];
    expect(sent.proposals).toHaveLength(1);
    expect(sent.proposals[0].part_number).toBe('AFE7951');
    expect(sent.proposals[0].pdf_path).toBe('/shelf/afe79xx-appnote.pdf');
    // The family applicability is carried through, not flattened to one part.
    expect(sent.proposals[0].applicability.kind).toBe('family');
    expect(sent.proposals[0].applicability.family).toBe('AFE79xx');
    // The directory the documents actually live in, not a blank.
    expect(sent.directory).toBe('/shelf');
  });

  it('hands off to the analyze run view with the run id in the URL', async () => {
    const user = userEvent.setup();
    startAnalyze.mockResolvedValue({ run_id: 'run-7', n_jobs: 1 });
    await toConverters();

    await user.click(screen.getByRole('button', { name: /Build AFE7951 from its documents/ }));

    await waitFor(() =>
      expect(screen.getByTestId('location').textContent).toContain('run=run-7'),
    );
  });

  it("renders the server's own message when the build cannot start", async () => {
    const user = userEvent.setup();
    startAnalyze.mockRejectedValue(new ApiError(400, 'the recorded path no longer exists'));
    await toConverters();

    await user.click(screen.getByRole('button', { name: /Build AFE7951 from its documents/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('the recorded path no longer exists');
  });
});

// --- the bookshelf, seen through the open project (round 3) ----------------------

describe('the library as a bookshelf', () => {
  const SHELF = '/shelf/radar';

  function withProject(directory: string) {
    getProjects.mockResolvedValue({
      projects: [{ ...projectOut('radar', ['AFE7950']), directory }],
      count: 1,
    });
  }

  it('defaults to the documents in the open project folder', async () => {
    const user = userEvent.setup();
    withProject(SHELF);
    getLibrary.mockResolvedValue(
      libraryOut({
        documents: [
          libraryDocument({ path: `${SHELF}/here.pdf`, filename: 'here.pdf' }),
          libraryDocument({
            content_hash: 'ccc333',
            path: '/somewhere/else/away.pdf',
            filename: 'away.pdf',
            part_number: 'AD9081',
            parts_reached: ['AD9081'],
          }),
        ],
      }),
    );

    renderLibrary();
    await user.selectOptions(await screen.findByLabelText('Working set'), 'radar');
    await screen.findByRole('button', { name: 'In radar' });

    await waitFor(() =>
      expect(screen.queryByRole('article', { name: 'Document away.pdf' })).toBeNull(),
    );
    expect(screen.getByText('here.pdf')).toBeInTheDocument();
  });

  it('opens the whole bookshelf on demand — that is what it is for', async () => {
    const user = userEvent.setup();
    withProject(SHELF);
    getLibrary.mockResolvedValue(
      libraryOut({
        documents: [
          libraryDocument({ path: `${SHELF}/here.pdf`, filename: 'here.pdf' }),
          libraryDocument({
            content_hash: 'ccc333',
            path: '/somewhere/else/away.pdf',
            filename: 'away.pdf',
            part_number: 'AD9081',
            parts_reached: ['AD9081'],
          }),
        ],
      }),
    );

    renderLibrary();
    await user.selectOptions(await screen.findByLabelText('Working set'), 'radar');
    await user.click(await screen.findByRole('button', { name: 'All documents' }));
    const tree = screen.getByRole('navigation', { name: 'Categories' });
    await user.click(within(tree).getByRole('button', { name: /^Data converters/ }));

    expect(await screen.findByText('away.pdf')).toBeInTheDocument();
  });

  it('adds a document from the bookshelf to the project, copying the PDF', async () => {
    const user = userEvent.setup();
    withProject(SHELF);
    getLibrary.mockResolvedValue(
      libraryOut({
        documents: [
          libraryDocument({
            content_hash: 'ccc333',
            path: '/somewhere/else/away.pdf',
            filename: 'away.pdf',
            part_number: 'AD9081',
            parts_reached: ['AD9081'],
          }),
        ],
      }),
    );
    addToShelf.mockResolvedValue({
      document: shelfDocument(),
      copied: true,
      renamed: false,
      reason: '',
      parts_added: ['AD9081'],
    });

    renderLibrary();
    await user.selectOptions(await screen.findByLabelText('Working set'), 'radar');
    await user.click(await screen.findByRole('button', { name: 'All documents' }));
    const tree = screen.getByRole('navigation', { name: 'Categories' });
    await user.click(within(tree).getByRole('button', { name: /^Data converters/ }));

    await user.click(
      await screen.findByRole('button', { name: 'Add away.pdf to this project' }),
    );

    await waitFor(() =>
      expect(addToShelf).toHaveBeenCalledWith('radar', { content_hash: 'ccc333' }),
    );
  });

  it('says when a name clash was copied alongside rather than over', async () => {
    const user = userEvent.setup();
    withProject(SHELF);
    getLibrary.mockResolvedValue(
      libraryOut({
        documents: [
          libraryDocument({
            content_hash: 'ccc333',
            path: '/elsewhere/ad9081.pdf',
            filename: 'ad9081.pdf',
            part_number: 'AD9081',
            parts_reached: ['AD9081'],
          }),
        ],
      }),
    );
    addToShelf.mockResolvedValue({
      document: shelfDocument({ filename: 'ad9081 (2).pdf' }),
      copied: true,
      renamed: true,
      reason: 'a different file was already called ad9081.pdf; copied as ad9081 (2).pdf',
      parts_added: [],
    });

    renderLibrary();
    await user.selectOptions(await screen.findByLabelText('Working set'), 'radar');
    await user.click(await screen.findByRole('button', { name: 'All documents' }));
    const tree = screen.getByRole('navigation', { name: 'Categories' });
    await user.click(within(tree).getByRole('button', { name: /^Data converters/ }));
    await user.click(
      await screen.findByRole('button', { name: 'Add ad9081.pdf to this project' }),
    );

    // The user now has two files that look like one document, and must be told.
    expect(await screen.findByText(/copied as ad9081 \(2\)\.pdf/)).toBeInTheDocument();
  });
});
