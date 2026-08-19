/**
 * Ticket 17 — the analyze and review screens.
 *
 * Hermetic by construction: the API client is mocked, so no request leaves
 * the process and no SSE connection is opened; the shell's
 * `ApplicabilityControl` (ticket 16, built concurrently) is injected through
 * the screen's own resolver module. One test asserts by reading the source
 * that no local copy of that control exists — the property the ticket cares
 * about is structural, not behavioural, so it is checked structurally.
 */
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// This file lives outside the Vite root (`web/`), and the repository has no
// root-level `node_modules`, so a bare specifier does not resolve from here.
// Until the scaffold grows an alias, the packages are addressed by path.
// `describe`/`it`/`expect`/`vi` need no import: `test.globals` is on.
import { act, cleanup, fireEvent, render, screen, waitFor } from '../../web/node_modules/@testing-library/react';
import { createElement } from '../../web/src/test-kit';
import type { ReactElement } from '../../web/src/test-kit';
import { MemoryRouter } from '../../web/node_modules/react-router-dom';

import type { AnalyzeStreamHandlers } from '../../web/src/api/client';
import type {
  AnalyzeJob,
  Applicability,
  DocProposal,
  JobEvent,
  ProjectOut,
  RunSnapshot,
  ScanOut,
} from '../../web/src/api/types';

const mocks = vi.hoisted(() => ({
  scanDirectory: vi.fn(),
  startAnalyze: vi.fn(),
  openAnalyzeStream: vi.fn(),
  openProject: vi.fn(),
  getProjects: vi.fn(),
  setProjectExclusions: vi.fn(),
  openFolderDialog: vi.fn(),
  listDirectory: vi.fn(),
  getCategories: vi.fn(),
  categorizeParts: vi.fn(),
  setPartCategory: vi.fn(),
}));

vi.mock('../../web/src/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../web/src/api/client')>();
  return {
    ...actual,
    scanDirectory: mocks.scanDirectory,
    startAnalyze: mocks.startAnalyze,
    openAnalyzeStream: mocks.openAnalyzeStream,
    openProject: mocks.openProject,
    getProjects: mocks.getProjects,
    setProjectExclusions: mocks.setProjectExclusions,
    openFolderDialog: mocks.openFolderDialog,
    listDirectory: mocks.listDirectory,
    getCategories: mocks.getCategories,
    categorizeParts: mocks.categorizeParts,
    setPartCategory: mocks.setPartCategory,
  };
});

/**
 * Stand in for the shell primitive.
 *
 * The real control belongs to `web/src/shell/**` and is resolved at runtime
 * by `shellPrimitives.ts`; mocking that resolver is how this screen is tested
 * without depending on another wave-1 ticket's files existing yet.
 */
vi.mock('../../web/src/routes/analyze/shellPrimitives', async () => {
  const react = await import('../../web/src/test-kit');
  type Props = {
    value: Applicability;
    onChange: (next: Applicability) => void;
    id?: string;
    label?: string;
    disabled?: boolean;
  };
  const Fake = ({ value, onChange, id, label, disabled }: Props) =>
    react.createElement(
      'div',
      { 'data-testid': id },
      react.createElement(
        'span',
        null,
        `applies:${value.kind}:${value.parts.join('|')}${value.family}`,
      ),
      react.createElement(
        'button',
        {
          type: 'button',
          disabled,
          onClick: () =>
            onChange({
              kind: 'parts',
              parts: ['AFE7950', 'AFE7951'],
              family: '',
              category: '',
              evidence: 'confirmed by user',
            }),
        },
        `Set applicability: ${label ?? ''}`,
      ),
    );
  return { getApplicabilityControl: () => Fake };
});

import { ApiError } from '../../web/src/api/client';
import AnalyzeScreen from '../../web/src/routes/analyze/route';

const ANALYZE_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '../../web/src/routes/analyze');

// --- fixtures -----------------------------------------------------------------

function applicability(patch: Partial<Applicability> = {}): Applicability {
  return { kind: 'all', parts: [], family: '', category: '', evidence: '', ...patch };
}

function proposal(patch: Partial<DocProposal> = {}): DocProposal {
  return {
    pdf_path: '/shelf/sbas123e.pdf',
    filename: 'sbas123e.pdf',
    part_number: 'AFE7950',
    applicability: applicability({
      kind: 'parts',
      parts: ['AFE7950'],
      evidence: 'title block: AFE7950 Quad RF Transceiver',
    }),
    evidence: 'page 1 title: AFE7950',
    page_count: 210,
    doc_type: 'datasheet',
    content_hash: 'hash-a',
    build_state: 'new',
    build_reason: 'no corpus for AFE7950 yet',
    relative_dir: '',
    is_datasheet: true,
    ...patch,
  };
}

function scanOut(proposals: DocProposal[], directory = '/shelf'): ScanOut {
  const states: Partial<Record<DocProposal['build_state'], number>> = {};
  for (const p of proposals) states[p.build_state] = (states[p.build_state] ?? 0) + 1;
  return { directory, proposals, count: proposals.length, states, skipped: [] };
}

function job(patch: Partial<AnalyzeJob> = {}): AnalyzeJob {
  return {
    id: 'job-1',
    pdf_path: '/shelf/sbas123e.pdf',
    part_number: 'AFE7950',
    applicability: applicability(),
    state: 'queued',
    error: '',
    detail: '',
    started_at: null,
    finished_at: null,
    ...patch,
  };
}

function snapshot(jobs: AnalyzeJob[], patch: Partial<RunSnapshot> = {}): RunSnapshot {
  return { run_id: 'run-1', directory: '/shelf', jobs, done: false, ...patch };
}

function jobEvent(patch: Partial<JobEvent> = {}): JobEvent {
  return {
    run_id: 'run-1',
    job_id: 'job-1',
    part_number: 'AFE7950',
    pdf_path: '/shelf/sbas123e.pdf',
    state: 'extracting',
    detail: '',
    at: '2026-01-01T00:00:00Z',
    ...patch,
  };
}

// --- fake stream --------------------------------------------------------------

interface FakeStream {
  runId: string;
  handlers: AnalyzeStreamHandlers;
  closed: boolean;
}

let streams: FakeStream[] = [];
let fetchSpy: ReturnType<typeof vi.fn>;

function latest(): FakeStream {
  const stream = streams[streams.length - 1];
  if (!stream) throw new Error('no analyze stream was opened');
  return stream;
}

async function emit(fn: () => void): Promise<void> {
  await act(async () => {
    fn();
  });
}

function ui(): ReactElement {
  return createElement(
    MemoryRouter,
    { initialEntries: ['/analyze'] },
    createElement(AnalyzeScreen),
  );
}

/** A project row, as `POST /api/projects/open` returns it. */
function projectOut(directory: string, over: Partial<ProjectOut> = {}): ProjectOut {
  return {
    name: 'shelf',
    parts: [],
    interfaces: '',
    notes: '',
    directory,
    excluded: [],
    built: false,
    error: '',
    ...over,
  };
}

/**
 * Open a folder and land wherever the scan sends us.
 *
 * The flow is "open a project folder", so every test that needs the review
 * screen goes through opening one — that *is* the entry point now, and a
 * harness that skipped it would be testing a path no user takes.
 */
async function openFolder(scan: ScanOut, project?: ProjectOut): Promise<void> {
  mocks.scanDirectory.mockResolvedValue(scan);
  mocks.openProject.mockResolvedValue(project ?? projectOut(scan.directory));
  render(ui());
  fireEvent.change(screen.getByLabelText('Project folder'), {
    target: { value: scan.directory },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Open' }));
}

/** Open a folder and land on the review screen. */
async function toReview(scan: ScanOut, project?: ProjectOut): Promise<void> {
  await openFolder(scan, project);
  await screen.findByRole('heading', { name: /Review/ });
}

/** Scan, confirm, and land on the progress screen with a live stream. */
async function toProgress(scan: ScanOut): Promise<void> {
  await toReview(scan);
  mocks.startAnalyze.mockResolvedValue({ run_id: 'run-1', n_jobs: scan.count });
  fireEvent.click(screen.getByRole('button', { name: /^Build/ }));
  await screen.findByRole('heading', { name: /Building/ });
  // The heading commits before the subscription effect flushes, so wait for
  // the stream itself rather than racing it.
  await waitFor(() => expect(streams.length).toBeGreaterThan(0));
}

beforeEach(() => {
  streams = [];
  mocks.scanDirectory.mockReset();
  mocks.startAnalyze.mockReset();
  mocks.openAnalyzeStream.mockReset();
  mocks.openProject.mockReset();
  mocks.getProjects.mockReset();
  mocks.getProjects.mockResolvedValue({ projects: [], count: 0 });
  mocks.setProjectExclusions.mockReset();
  mocks.setProjectExclusions.mockImplementation(async () => projectOut('/shelf'));
  mocks.openFolderDialog.mockReset();
  mocks.openFolderDialog.mockResolvedValue({
    available: true,
    picked: false,
    directory: '',
    reason: '',
  });
  mocks.listDirectory.mockReset();
  mocks.listDirectory.mockResolvedValue({ path: '', parent: '', entries: [] });
  mocks.getCategories.mockReset();
  mocks.getCategories.mockResolvedValue({
    categories: [
      { id: 'amplifiers', name: 'Amplifiers', count: 0 },
      { id: 'uncategorized', name: 'Uncategorized', count: 0 },
    ],
  });
  mocks.categorizeParts.mockReset();
  mocks.categorizeParts.mockResolvedValue({ parts: [] });
  mocks.setPartCategory.mockReset();
  mocks.openAnalyzeStream.mockImplementation((runId: string, handlers: AnalyzeStreamHandlers) => {
    const stream: FakeStream = { runId, handlers, closed: false };
    streams.push(stream);
    return {
      close: () => {
        stream.closed = true;
      },
    };
  });
  window.localStorage.clear();
  fetchSpy = vi.fn(() => Promise.reject(new Error('no screen may hand-build a fetch')));
  vi.stubGlobal('fetch', fetchSpy);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

// --- opening a folder ----------------------------------------------------------

describe('opening a project folder', () => {
  it('opens the folder, scans it recursively, and lands on review', async () => {
    await toReview(scanOut([proposal()]));

    expect(mocks.openProject).toHaveBeenCalledWith({ directory: '/shelf' });
    expect(mocks.scanDirectory).toHaveBeenCalledWith({ directory: '/shelf' });
    expect(screen.getByText('sbas123e.pdf')).toBeInTheDocument();
  });

  it("shows the server's message when the folder cannot be opened", async () => {
    mocks.openProject.mockRejectedValue(new ApiError(400, 'directory not found: /nope'));
    render(ui());

    fireEvent.change(screen.getByLabelText('Project folder'), { target: { value: '/nope' } });
    fireEvent.click(screen.getByRole('button', { name: 'Open' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('directory not found: /nope');
    expect(screen.queryByRole('heading', { name: /Review/ })).not.toBeInTheDocument();
  });

  it('offers a real folder dialog, because the app is local', async () => {
    mocks.openFolderDialog.mockResolvedValue({
      available: true,
      picked: true,
      directory: '/picked/shelf',
      reason: '',
    });
    mocks.scanDirectory.mockResolvedValue(scanOut([proposal()], '/picked/shelf'));
    mocks.openProject.mockResolvedValue(projectOut('/picked/shelf'));
    render(ui());

    fireEvent.click(screen.getByRole('button', { name: 'Browse…' }));

    await waitFor(() =>
      expect(mocks.openProject).toHaveBeenCalledWith({ directory: '/picked/shelf' }),
    );
  });

  it('cancelling the dialog does nothing at all', async () => {
    render(ui());
    fireEvent.click(screen.getByRole('button', { name: 'Browse…' }));

    await waitFor(() => expect(mocks.openFolderDialog).toHaveBeenCalled());
    expect(mocks.openProject).not.toHaveBeenCalled();
  });

  it('falls back to the in-app browser when no dialog can open', async () => {
    // A headless host has no dialog. The button must not silently do nothing.
    mocks.openFolderDialog.mockResolvedValue({
      available: false,
      picked: false,
      directory: '',
      reason: 'no native dialog: no display',
    });
    render(ui());

    fireEvent.click(screen.getByRole('button', { name: 'Browse…' }));

    expect(await screen.findByRole('status')).toHaveTextContent(/browse below/i);
    await waitFor(() => expect(mocks.listDirectory).toHaveBeenCalled());
  });

  it('lists recent projects, which come from the server and not the browser', async () => {
    mocks.getProjects.mockResolvedValue({
      projects: [projectOut('/work/radar', { name: 'radar' })],
      count: 1,
    });
    render(ui());

    const recent = await screen.findByRole('button', { name: /radar/ });
    expect(recent).toHaveTextContent('/work/radar');
  });
});

// --- review -------------------------------------------------------------------

describe('reviewing proposals', () => {
  it('renders the part number, the applicability and both evidences for every row', async () => {
    await toReview(
      scanOut([
        proposal(),
        proposal({
          pdf_path: '/shelf/an-jesd.pdf',
          filename: 'an-jesd.pdf',
          content_hash: 'hash-b',
          part_number: 'AFE7950',
          evidence: 'page 1 title: AFE79xx JESD204C Interface Guide',
          applicability: applicability({
            kind: 'family',
            family: 'AFE79xx',
            category: '',
            evidence: 'title names a family prefix',
          }),
        }),
      ]),
    );

    expect(screen.getByLabelText('Part number for sbas123e.pdf')).toHaveValue(
      'AFE7950',
    );
    expect(screen.getByText('applies:parts:AFE7950')).toBeInTheDocument();
    expect(screen.getByText('applies:family:AFE79xx')).toBeInTheDocument();
    expect(screen.getByText(/page 1 title: AFE7950/)).toBeInTheDocument();
    expect(screen.getByText(/title block: AFE7950 Quad RF Transceiver/)).toBeInTheDocument();
    expect(screen.getByText(/title names a family prefix/)).toBeInTheDocument();
  });

  it('posts edited part numbers and applicability verbatim to /api/analyze/start', async () => {
    const first = proposal();
    const second = proposal({
      pdf_path: '/shelf/an-jesd.pdf',
      filename: 'an-jesd.pdf',
      content_hash: 'hash-b',
      part_number: 'SBAA999',
      applicability: applicability({ evidence: 'fallback: no part token found' }),
    });
    await toReview(scanOut([first, second]));

    fireEvent.change(screen.getByLabelText('Part number for an-jesd.pdf'), {
      target: { value: 'AFE7951' },
    });
    fireEvent.click(
      screen.getByRole('button', { name: 'Set applicability: Applicability for an-jesd.pdf' }),
    );

    mocks.startAnalyze.mockResolvedValue({ run_id: 'run-1', n_jobs: 2 });
    fireEvent.click(screen.getByRole('button', { name: /^Build/ }));

    await waitFor(() => expect(mocks.startAnalyze).toHaveBeenCalledTimes(1));
    expect(mocks.startAnalyze).toHaveBeenCalledWith({
      directory: '/shelf',
      proposals: [
        first,
        {
          ...second,
          part_number: 'AFE7951',
          applicability: {
            kind: 'parts',
            parts: ['AFE7950', 'AFE7951'],
            family: '',
            category: '',
            evidence: 'confirmed by user',
          },
        },
      ],
    });
  });

  it('imports ApplicabilityControl from the shell and keeps no local copy', () => {
    const files: string[] = readdirSync(ANALYZE_DIR).filter((name: string) =>
      /\.(ts|tsx)$/.test(name),
    );
    expect(files.length).toBeGreaterThan(0);

    // A local copy would be a *definition*. Binding the shell's component to
    // a capitalized name so JSX can render it is not one, so the pattern
    // matches function/class declarations and component expressions only.
    const definition =
      /(?:function|class)\s+ApplicabilityControl\b|const\s+ApplicabilityControl\s*=\s*(?:\(|function\b|memo\b|forwardRef\b)/;
    for (const name of files) {
      const source = readFileSync(join(ANALYZE_DIR, name), 'utf8');
      expect(definition.test(source), `${name} defines its own ApplicabilityControl`).toBe(false);
    }
    expect(readFileSync(join(ANALYZE_DIR, 'ReviewStep.tsx'), 'utf8')).toContain(
      'getApplicabilityControl()',
    );

    const resolver = readFileSync(join(ANALYZE_DIR, 'shellPrimitives.ts'), 'utf8');
    expect(resolver).toContain('../../shell/');
    expect(resolver).toContain('ApplicabilityControl');
  });

  it('floats rows needing attention above multi-part rows above confident ones', async () => {
    await toReview(
      scanOut([
        proposal({
          filename: 'confident.pdf',
          content_hash: 'hash-confident',
          applicability: applicability({ kind: 'parts', parts: ['AFE7950'] }),
        }),
        proposal({
          filename: 'family.pdf',
          content_hash: 'hash-family',
          applicability: applicability({ kind: 'family', family: 'AFE79xx' }),
        }),
        proposal({
          filename: 'unresolved.pdf',
          content_hash: 'hash-unresolved',
          applicability: applicability({ kind: 'all' }),
        }),
        proposal({
          filename: 'two-parts.pdf',
          content_hash: 'hash-two',
          applicability: applicability({ kind: 'parts', parts: ['AFE7950', 'AFE7951'] }),
        }),
        proposal({
          filename: 'no-part.pdf',
          content_hash: 'hash-nopart',
          part_number: '',
          applicability: applicability({ kind: 'parts', parts: ['AFE7950'] }),
        }),
      ]),
    );

    // Rows are `h4` now: they sit inside a folder section whose heading is the
    // `h3`. Level 3 would pick up the folder header, not the documents.
    const names = [...document.querySelectorAll('.analyze-row-name')].map(
      (node) => node.textContent ?? '',
    );
    expect(names).toEqual([
      'no-part.pdf',
      'unresolved.pdf',
      'family.pdf',
      'two-parts.pdf',
      'confident.pdf',
    ]);
  });

  it('blocks the build while a row has no part number', async () => {
    await toReview(scanOut([proposal({ part_number: '' })]));

    expect(screen.getByRole('button', { name: /^Build/ })).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent('have no part number');

    fireEvent.change(screen.getByLabelText('Part number for sbas123e.pdf'), {
      target: { value: 'AFE7950' },
    });
    expect(screen.getByRole('button', { name: /^Build/ })).toBeEnabled();
  });

  it('lets a supporting document through with no part number, and says so', async () => {
    // An app note covering every amplifier belongs to a category and to no
    // part. Demanding a part number for it made it unsubmittable, which left
    // the one kind of document the category applicability exists for with no
    // way into the Library at all.
    await toReview(
      scanOut([
        proposal({
          filename: 'AN-1285.pdf',
          pdf_path: '/shelf/AN-1285.pdf',
          part_number: '',
          applicability: applicability({ kind: 'category', category: 'amplifiers' }),
        }),
      ]),
    );

    expect(screen.getByRole('button', { name: /^Build/ })).toBeEnabled();
    expect(screen.queryByText(/have no part number/)).toBeNull();
    expect(screen.getByText(/will be filed, not built into a part/)).toBeInTheDocument();
  });

  it('has an empty state for a directory with no PDFs', async () => {
    await toReview(scanOut([]));

    expect(screen.getByText(/No PDFs were found directly inside \/shelf/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Build/ })).not.toBeInTheDocument();
  });

  it('has a loading state while starting and shows a start failure inline', async () => {
    await toReview(scanOut([proposal()]));

    mocks.startAnalyze.mockReturnValue(new Promise(() => {}));
    fireEvent.click(screen.getByRole('button', { name: /^Build/ }));
    expect(await screen.findByRole('status')).toHaveTextContent('Starting the build…');

    cleanup();
    await toReview(scanOut([proposal()]));
    mocks.startAnalyze.mockRejectedValue(new ApiError(400, 'parts_dir is not writable'));
    fireEvent.click(screen.getByRole('button', { name: /^Build/ }));

    expect(await screen.findByRole('alert')).toHaveTextContent('parts_dir is not writable');
    expect(screen.getByRole('heading', { name: /Review/ })).toBeInTheDocument();
  });
});

// --- progress -----------------------------------------------------------------

describe('watching the run', () => {
  const twoDocs = scanOut([
    proposal(),
    proposal({
      pdf_path: '/shelf/an-jesd.pdf',
      filename: 'an-jesd.pdf',
      content_hash: 'hash-b',
      part_number: 'AFE7951',
    }),
  ]);

  const twoJobs = [
    job({ id: 'job-1', part_number: 'AFE7950' }),
    job({ id: 'job-2', part_number: 'AFE7951', pdf_path: '/shelf/an-jesd.pdf' }),
  ];

  it('shows a loading state until the first snapshot arrives', async () => {
    await toProgress(twoDocs);

    expect(mocks.openAnalyzeStream).toHaveBeenCalledWith('run-1', expect.anything());
    expect(screen.getByRole('status')).toHaveTextContent('Connecting to the run…');
  });

  it('has an empty state for a run with no jobs', async () => {
    await toProgress(twoDocs);
    await emit(() => latest().handlers.onSnapshot?.(snapshot([])));

    expect(screen.getByText(/This run has no jobs/)).toBeInTheDocument();
  });

  it('reflects live per-job state from the stream', async () => {
    await toProgress(twoDocs);
    await emit(() => latest().handlers.onSnapshot?.(snapshot(twoJobs)));

    const rows = () => Array.from(document.querySelectorAll('.analyze-job'));
    expect(rows().map((row) => row.getAttribute('data-state'))).toEqual(['queued', 'queued']);

    await emit(() =>
      latest().handlers.onJob?.(jobEvent({ job_id: 'job-1', state: 'extracting' })),
    );
    await emit(() =>
      latest().handlers.onJob?.(
        jobEvent({ job_id: 'job-2', state: 'structuring', detail: 'page 40 of 92' }),
      ),
    );

    expect(rows().map((row) => row.getAttribute('data-state'))).toEqual([
      'extracting',
      'structuring',
    ]);
    expect(screen.getByText('page 40 of 92')).toBeInTheDocument();
  });

  it('offers "Ask about this" as soon as one part is done, while others still run', async () => {
    await toProgress(twoDocs);
    await emit(() => latest().handlers.onSnapshot?.(snapshot(twoJobs)));
    await emit(() =>
      latest().handlers.onJob?.(jobEvent({ job_id: 'job-2', state: 'enriching' })),
    );
    await emit(() => latest().handlers.onJob?.(jobEvent({ job_id: 'job-1', state: 'done' })));

    const ask = screen.getByRole('link', { name: 'Ask about AFE7950' });
    expect(ask).toHaveAttribute('href', '/chat?part=AFE7950');
    expect(screen.queryByRole('link', { name: 'Ask about AFE7951' })).not.toBeInTheDocument();
    expect(document.querySelector('.analyze-job--enriching')).not.toBeNull();
  });

  it('shows a failed job’s error inline and lets the rest keep going', async () => {
    await toProgress(twoDocs);
    await emit(() => latest().handlers.onSnapshot?.(snapshot(twoJobs)));
    await emit(() =>
      latest().handlers.onJob?.(
        jobEvent({ job_id: 'job-2', state: 'failed', detail: 'PDF is encrypted' }),
      ),
    );
    await emit(() =>
      latest().handlers.onJob?.(jobEvent({ job_id: 'job-1', state: 'publishing' })),
    );

    expect(screen.getByRole('alert')).toHaveTextContent('PDF is encrypted');
    expect(document.querySelector('.analyze-job--publishing')).not.toBeNull();
    expect(document.querySelectorAll('.analyze-job')).toHaveLength(2);
  });

  it('reconnects after a dropped stream and re-renders from the snapshot with no gap', async () => {
    await toProgress(twoDocs);
    await emit(() => latest().handlers.onSnapshot?.(snapshot(twoJobs)));
    await emit(() =>
      latest().handlers.onJob?.(jobEvent({ job_id: 'job-1', state: 'extracting' })),
    );
    expect(mocks.openAnalyzeStream).toHaveBeenCalledTimes(1);

    vi.useFakeTimers();
    const dropped = latest();
    await emit(() => dropped.handlers.onError?.(new Event('error')));

    // No gap: the rows are still on screen while the stream is rebuilt.
    expect(document.querySelectorAll('.analyze-job')).toHaveLength(2);
    expect(dropped.closed).toBe(true);
    expect(screen.getByRole('status')).toHaveTextContent('reconnecting');

    await emit(() => {
      vi.advanceTimersByTime(500);
    });
    expect(mocks.openAnalyzeStream).toHaveBeenCalledTimes(2);
    expect(latest()).not.toBe(dropped);

    await emit(() =>
      latest().handlers.onSnapshot?.(
        snapshot([
          { ...twoJobs[0], state: 'done' },
          { ...twoJobs[1], state: 'publishing' },
        ]),
      ),
    );
    const states = Array.from(document.querySelectorAll('.analyze-job')).map((row) =>
      row.getAttribute('data-state'),
    );
    expect(states).toEqual(['done', 'publishing']);
    expect(screen.queryByText(/reconnecting/)).not.toBeInTheDocument();
  });

  it('closes the stream when the screen unmounts', async () => {
    await toProgress(twoDocs);
    const stream = latest();

    cleanup();

    expect(stream.closed).toBe(true);
  });
});

// --- the client is the only door ----------------------------------------------

describe('every server call goes through the client', () => {
  it('never hand-builds a fetch across the whole flow', async () => {
    await toProgress(scanOut([proposal()]));
    await emit(() => latest().handlers.onSnapshot?.(snapshot([job()])));
    await emit(() => latest().handlers.onJob?.(jobEvent({ state: 'done' })));

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(mocks.scanDirectory).toHaveBeenCalled();
    expect(mocks.startAnalyze).toHaveBeenCalled();
    expect(mocks.openAnalyzeStream).toHaveBeenCalled();
  });

  it('opens no EventSource of its own', async () => {
    const source = vi.fn();
    vi.stubGlobal('EventSource', source);

    await toProgress(scanOut([proposal()]));

    expect(source).not.toHaveBeenCalled();
  });
});

// --- ticket 29: analyze collapses when there is nothing to do --------------------

describe('a rescan with nothing to do', () => {
  /** Open a folder whose every document is already current. */
  async function toUpToDate(scan: ScanOut): Promise<void> {
    await openFolder(scan);
    await screen.findByRole('heading', { name: 'Nothing to build' });
  }

  const built = (over: Partial<DocProposal> = {}) =>
    proposal({
      build_state: 'current',
      build_reason: 'already built: PDF sha256, pipeline and extractor versions match',
      ...over,
    });

  it('says so and shows no review table', async () => {
    await toUpToDate(
      scanOut([
        built(),
        built({
          pdf_path: '/shelf/lm741.pdf',
          filename: 'lm741.pdf',
          part_number: 'LM741',
          content_hash: 'hash-b',
        }),
      ]),
    );

    expect(
      screen.getByText('All 2 documents in this directory are already built and current.'),
    ).toBeInTheDocument();
    // Skipped entirely, not rendered empty.
    expect(screen.queryByRole('heading', { name: /^Review/ })).toBeNull();
  });

  it('rebuild anyway starts a run for every proposal', async () => {
    await toUpToDate(scanOut([built()]));
    mocks.startAnalyze.mockResolvedValue({ run_id: 'run-9', n_jobs: 1 });

    fireEvent.click(screen.getByRole('button', { name: 'Rebuild anyway' }));

    await waitFor(() => expect(mocks.startAnalyze).toHaveBeenCalledTimes(1));
    expect(mocks.startAnalyze.mock.calls[0][0].proposals).toHaveLength(1);
  });

  it('a mixed scan still reviews, listing what will rebuild first', async () => {
    await toReview(
      scanOut([
        built(),
        proposal({
          pdf_path: '/shelf/older.pdf',
          filename: 'older.pdf',
          part_number: 'LM741',
          content_hash: 'hash-b',
          build_state: 'stale',
          build_reason: 'built by pipeline 0.1.0, current is 0.4.0',
        }),
      ]),
    );

    expect(screen.getByTestId('analyze-summary')).toHaveTextContent('1 current, 1 will rebuild');
    expect(screen.getByTestId('analyze-summary')).toHaveTextContent('1 stale');

    // What costs time is not buried under what does not.
    const rows = document.querySelectorAll('.analyze-row');
    expect(rows[0].getAttribute('data-build-state')).toBe('stale');
  });
});

// --- selection and exclusions ----------------------------------------------------

describe('choosing what to build', () => {
  const junk = () =>
    proposal({
      pdf_path: '/shelf/reference/po-4471.pdf',
      filename: 'po-4471.pdf',
      content_hash: 'hash-po',
      relative_dir: 'reference',
      is_datasheet: false,
      build_reason: 'no corpus yet',
    });

  it('ticks the work that needs doing and leaves the rest alone', async () => {
    await toReview(
      scanOut([
        proposal(),
        proposal({
          filename: 'built.pdf',
          content_hash: 'hash-built',
          build_state: 'current',
          build_reason: 'already built',
        }),
        junk(),
      ]),
    );

    // `new` is ticked; `current` and not-a-datasheet are not.
    expect(screen.getByRole('checkbox', { name: 'Build sbas123e.pdf' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Build built.pdf' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Build po-4471.pdf' })).not.toBeChecked();
  });

  it('starts a build for only the ticked rows', async () => {
    await toReview(scanOut([proposal(), junk()]));
    mocks.startAnalyze.mockResolvedValue({ run_id: 'run-1', n_jobs: 1 });

    fireEvent.click(screen.getByRole('button', { name: /^Build/ }));

    await waitFor(() => expect(mocks.startAnalyze).toHaveBeenCalled());
    const sent = mocks.startAnalyze.mock.calls[0][0];
    expect(sent.proposals.map((p: DocProposal) => p.filename)).toEqual(['sbas123e.pdf']);
  });

  it('remembers what was left unticked, so a rescan does not re-propose it', async () => {
    await toReview(scanOut([proposal(), junk()]));
    mocks.startAnalyze.mockResolvedValue({ run_id: 'run-1', n_jobs: 1 });

    fireEvent.click(screen.getByRole('button', { name: /^Build/ }));

    await waitFor(() => expect(mocks.setProjectExclusions).toHaveBeenCalled());
    expect(mocks.setProjectExclusions.mock.calls[0][1]).toEqual({ excluded: ['hash-po'] });
  });

  it('starts a previously excluded document unticked', async () => {
    await toReview(scanOut([proposal(), junk()]), projectOut('/shelf', { excluded: ['hash-a'] }));

    // `hash-a` is this project's rejection from a previous scan.
    expect(screen.getByRole('checkbox', { name: 'Build sbas123e.pdf' })).not.toBeChecked();
  });

  it('groups by subdirectory and excludes a whole folder in one click', async () => {
    await toReview(scanOut([proposal(), junk()]));

    const folders = [...document.querySelectorAll('.analyze-folder')].map((n) =>
      n.getAttribute('data-directory'),
    );
    expect(folders).toEqual(['', 'reference']);

    // One click rejects the folder, not twelve clicks rejecting its contents.
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Include everything in the top level' }),
    );
    expect(screen.getByRole('checkbox', { name: 'Build sbas123e.pdf' })).not.toBeChecked();
  });

  it('reports the folders the walk did not search', async () => {
    const scan = scanOut([proposal()]);
    await toReview({ ...scan, skipped: ['parts (not a source directory)'] });

    expect(screen.getByText(/1 folder\(s\) not searched/)).toBeInTheDocument();
    expect(screen.getByText('parts (not a source directory)')).toBeInTheDocument();
  });
});
