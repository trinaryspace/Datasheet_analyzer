/**
 * Ticket 19 — the PDF pane and its highlight overlay.
 *
 * Hermetic by construction: PDF.js is replaced with a fake document (no
 * worker, no bytes, no canvas), `/api/locate` is a stubbed `fetch`, and the
 * "nothing is fetched from a CDN" claim is checked by reading the pane's own
 * source rather than by opening a network connection.
 *
 * Written as `.ts` rather than `.tsx` because the ticket names the file:
 * components are built with `createElement`.
 *
 * The package imports are spelled relative to `web/node_modules` because
 * `tests/` sits outside the frontend package and node resolution from here
 * finds nothing — a gap in the scaffold, worked around rather than fixed,
 * since `web/tsconfig.json` and `web/vite.config.ts` belong to ticket 00.
 * Vitest's globals supply `describe`/`it`/`expect`/`vi`.
 */
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '../../web/node_modules/@testing-library/react';
// @ts-ignore -- react ships no types of its own; @types/react is not reachable
// through a path import from outside the frontend package.
import { Fragment, createElement } from '../../web/node_modules/react';
import { MemoryRouter, useNavigate } from '../../web/node_modules/react-router-dom';

const hoisted = vi.hoisted(() => ({
  getDocumentMock: vi.fn(),
  workerOptions: { workerSrc: '' },
}));

// The resolved id of `pdfjs-dist` as `web/src/routes/pdf/pdfjs.ts` imports it.
vi.mock('../../web/node_modules/pdfjs-dist/build/pdf.mjs', () => ({
  GlobalWorkerOptions: hoisted.workerOptions,
  getDocument: hoisted.getDocumentMock,
}));

import type { LocateOut, RectOut } from '../../web/src/api/types';
import PdfPane from '../../web/src/routes/pdf/PdfPane';
import {
  displaySize,
  fitWidthScale,
  highlightRects,
  nextZoom,
  normalizeRotation,
  rectToPixels,
} from '../../web/src/routes/pdf/geometry';
import { RANGE_REQUEST_OPTIONS, WORKER_SRC } from '../../web/src/routes/pdf/pdfjs';
import PdfRoute from '../../web/src/routes/pdf/route';
import { pdfTargetSearch, readPdfTarget, targetFromCitation } from '../../web/src/routes/pdf/target';

// --- fakes --------------------------------------------------------------------

interface FakePageSpec {
  width: number;
  height: number;
  rotate?: number;
}

interface FakeRenderParams {
  canvasContext: unknown;
  viewport: { width: number; height: number };
}

function makeFakeDoc(numPages: number, page: FakePageSpec) {
  const pageRender = vi.fn((_params: FakeRenderParams) => ({
    promise: Promise.resolve(),
    cancel: vi.fn(),
  }));
  const getPage = vi.fn(async (pageNumber: number) => ({
    pageNumber,
    rotate: page.rotate ?? 0,
    getViewport: ({ scale, rotation }: { scale: number; rotation?: number }) => {
      const applied = normalizeRotation(rotation ?? page.rotate ?? 0);
      const swapped = applied === 90 || applied === 270;
      return {
        width: (swapped ? page.height : page.width) * scale,
        height: (swapped ? page.width : page.height) * scale,
      };
    },
    render: pageRender,
    cleanup: vi.fn(),
  }));
  return { numPages, getPage, destroy: vi.fn(), render: pageRender };
}

type FakeDoc = ReturnType<typeof makeFakeDoc>;

/** Every `getDocument(...)` resolves to `doc`, whatever the URL. */
function serveDoc(doc: FakeDoc) {
  hoisted.getDocumentMock.mockImplementation(() => ({
    promise: Promise.resolve(doc),
    destroy: vi.fn(),
  }));
}

/** `getDocument(...)` resolves per URL — for the "click into another doc" case. */
function serveDocsByHash(byHash: Record<string, FakeDoc>) {
  hoisted.getDocumentMock.mockImplementation((params: { url: string }) => {
    const hash = params.url.split('/').pop() ?? '';
    const doc = byHash[hash];
    if (!doc) {
      return { promise: Promise.reject(notFound()), destroy: vi.fn() };
    }
    return { promise: Promise.resolve(doc), destroy: vi.fn() };
  });
}

function notFound(): Error {
  return Object.assign(new Error('Missing PDF'), {
    name: 'MissingPDFException',
    status: 404,
  });
}

function failDocLoad(error: Error) {
  hoisted.getDocumentMock.mockImplementation(() => ({
    promise: Promise.reject(error),
    destroy: vi.fn(),
  }));
}

const LOCATE_DEFAULTS: LocateOut = {
  found: false,
  page: 1,
  rects: [],
  reason: '',
  needle: '',
  page_width: 0,
  page_height: 0,
  rotation: 0,
};

let locateUrls: string[] = [];

function serveLocate(body: Partial<LocateOut>) {
  const payload: LocateOut = { ...LOCATE_DEFAULTS, ...body };
  const fetchMock = vi.fn(async (input: unknown) => {
    locateUrls.push(String(input));
    return {
      ok: true,
      status: 200,
      json: async () => payload,
    } as unknown as Response;
  });
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

function rect(x0: number, y0: number, x1: number, y1: number): RectOut {
  return { x0, y0, x1, y1 };
}

let stubbedClientWidth = 900;

beforeAll(() => {
  // jsdom has no canvas implementation. A stand-in context keeps the real
  // paint path exercised (and keeps jsdom's "not implemented" noise out of
  // the run) without pulling in a native canvas dependency.
  (HTMLCanvasElement.prototype as unknown as { getContext: () => unknown }).getContext = () =>
    ({}) as CanvasRenderingContext2D;

  // jsdom lays nothing out, so the pane's measured width is stubbed. Fit-width
  // is a real behaviour and must be exercised, not skipped.
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
    configurable: true,
    get() {
      return stubbedClientWidth;
    },
  });
});

afterAll(() => {
  delete (HTMLElement.prototype as unknown as Record<string, unknown>).clientWidth;
});

beforeEach(() => {
  stubbedClientWidth = 900;
  locateUrls = [];
  hoisted.getDocumentMock.mockReset();
  serveDoc(makeFakeDoc(3, { width: 612, height: 792 }));
  serveLocate({});
});

afterEach(() => {
  cleanup();
});

function styleOf(element: HTMLElement) {
  return {
    left: element.style.left,
    top: element.style.top,
    width: element.style.width,
    height: element.style.height,
  };
}

function renderPane(target: {
  doc_hash: string;
  part?: string;
  page?: number;
  needle?: string;
}) {
  return render(
    createElement(PdfPane, {
      target: {
        doc_hash: target.doc_hash,
        part: target.part ?? 'AFE7950',
        page: target.page ?? 1,
        needle: target.needle ?? '',
      },
    }),
  );
}

function pageInput(): HTMLInputElement {
  return screen.getByLabelText('Page number') as HTMLInputElement;
}

function zoomText(): string {
  return screen.getByTestId('pdf-zoom').textContent ?? '';
}

// --- geometry: rects in PDF points, boxes in canvas pixels ---------------------

describe('highlight geometry', () => {
  const page = { width: 612, height: 792, rotation: 0 as const };

  it('places a rect at its PDF-point position at 100% zoom', () => {
    expect(rectToPixels(rect(72, 100, 300, 120), page, 1)).toEqual({
      left: 72,
      top: 100,
      width: 228,
      height: 20,
    });
  });

  it('scales with zoom rather than caching pixels', () => {
    expect(rectToPixels(rect(72, 100, 300, 120), page, 2)).toEqual({
      left: 144,
      top: 200,
      width: 456,
      height: 40,
    });
    expect(rectToPixels(rect(72, 100, 300, 120), page, 0.5)).toEqual({
      left: 36,
      top: 50,
      width: 114,
      height: 10,
    });
  });

  it('normalizes rects whose corners arrive in either order', () => {
    expect(rectToPixels(rect(300, 120, 72, 100), page, 1)).toEqual(
      rectToPixels(rect(72, 100, 300, 120), page, 1),
    );
  });

  it('rotates the page: a top-left rect lands in the right corner for each turn', () => {
    const corner = rect(0, 0, 12, 20); // top-left of the unrotated page
    const w = 612;
    const h = 792;

    expect(rectToPixels(corner, { width: w, height: h, rotation: 0 }, 1)).toEqual({
      left: 0,
      top: 0,
      width: 12,
      height: 20,
    });
    // 90° clockwise: the unrotated top-left becomes the displayed top-right.
    expect(rectToPixels(corner, { width: w, height: h, rotation: 90 }, 1)).toEqual({
      left: h - 20,
      top: 0,
      width: 20,
      height: 12,
    });
    expect(rectToPixels(corner, { width: w, height: h, rotation: 180 }, 1)).toEqual({
      left: w - 12,
      top: h - 20,
      width: 12,
      height: 20,
    });
    expect(rectToPixels(corner, { width: w, height: h, rotation: 270 }, 1)).toEqual({
      left: 0,
      top: w - 12,
      width: 20,
      height: 12,
    });
  });

  it('keeps every rotated rect inside the displayed page', () => {
    const some = rect(100, 300, 400, 340);
    for (const rotation of [0, 90, 180, 270] as const) {
      const geom = { width: 612, height: 792, rotation };
      const box = rectToPixels(some, geom, 1.5);
      const size = displaySize(geom, 1.5);
      expect(box.left).toBeGreaterThanOrEqual(0);
      expect(box.top).toBeGreaterThanOrEqual(0);
      expect(box.left + box.width).toBeLessThanOrEqual(size.width + 1e-9);
      expect(box.top + box.height).toBeLessThanOrEqual(size.height + 1e-9);
    }
  });

  it('swaps the display size on a quarter turn', () => {
    expect(displaySize({ width: 612, height: 792, rotation: 0 }, 2)).toEqual({
      width: 1224,
      height: 1584,
    });
    expect(displaySize({ width: 612, height: 792, rotation: 90 }, 1)).toEqual({
      width: 792,
      height: 612,
    });
  });

  it('fits width against the displayed edge, rotation included', () => {
    expect(fitWidthScale(1224, { width: 612, height: 792, rotation: 0 })).toBe(2);
    expect(fitWidthScale(792, { width: 612, height: 792, rotation: 90 })).toBe(1);
    expect(fitWidthScale(0, { width: 612, height: 792, rotation: 0 })).toBe(1);
  });

  it('snaps odd rotations and refuses nonsense', () => {
    expect(normalizeRotation(-90)).toBe(270);
    expect(normalizeRotation(450)).toBe(90);
    expect(normalizeRotation(Number.NaN)).toBe(0);
  });

  it('draws nothing for an honest miss, whatever rects are attached', () => {
    const miss: LocateOut = {
      ...LOCATE_DEFAULTS,
      found: false,
      rects: [rect(1, 2, 3, 4)],
      reason: 'not on this page',
    };
    expect(highlightRects(miss, page, 1)).toEqual([]);
  });

  it('steps zoom through the toolbar levels and saturates', () => {
    expect(nextZoom(1, 1)).toBe(1.25);
    expect(nextZoom(1, -1)).toBe(0.75);
    expect(nextZoom(4, 1)).toBe(4);
    expect(nextZoom(0.5, -1)).toBe(0.5);
  });
});

// --- the target lives in the URL ----------------------------------------------

describe('the pane target', () => {
  it('decodes the four cross-pane parameters', () => {
    expect(readPdfTarget('doc=abc123&part=AFE7950&page=47&needle=Supply+current')).toEqual({
      doc_hash: 'abc123',
      part: 'AFE7950',
      page: 47,
      needle: 'Supply current',
    });
  });

  it('is null with no document and holds the page when none is named', () => {
    expect(readPdfTarget('part=AFE7950&page=3')).toBeNull();
    expect(readPdfTarget('doc=abc123')?.page).toBe(0);
    expect(readPdfTarget('doc=abc123&page=not-a-page')?.page).toBe(0);
  });

  it('round-trips through a query string', () => {
    const target = { doc_hash: 'abc', part: 'LM741', page: 9, needle: 'Vos' };
    expect(readPdfTarget(pdfTargetSearch(target))).toEqual(target);
  });

  it('opens a citation at its first cited page', () => {
    expect(
      targetFromCitation({
        doc: 'lm741.pdf',
        doc_hash: 'deadbeef',
        section: '6.5 Electrical Characteristics',
        page_start: 7,
        page_end: 8,
        part: 'LM741',
        pages: 'pp.7-8',
        label: '§6.5, pp.7-8',
        needle: 'Output power',
      }),
    ).toEqual({
      doc_hash: 'deadbeef',
      part: 'LM741',
      page: 7,
      needle: '6.5 Electrical Characteristics',
    });
  });
});

// --- nothing leaves the origin -------------------------------------------------

describe('local-only delivery', () => {
  // Read as raw text through Vite's own glob, which is exactly the set of
  // files the bundler will include.
  const raw = import.meta.glob('../../web/src/routes/pdf/*', {
    query: '?raw',
    import: 'default',
    eager: true,
  }) as Record<string, string>;
  const sources = Object.entries(raw).map(([path, text]) => ({
    name: path.split('/').pop() ?? path,
    text,
    // Prose may discuss CDNs; code may not contain one.
    code: text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|\s)\/\/.*$/gm, ''),
  }));

  it('bundles the PDF.js worker instead of pointing at a CDN', () => {
    expect(WORKER_SRC).toBeTruthy();
    expect(WORKER_SRC).not.toMatch(/^https?:/);
    // A bundled asset: same-origin, relative or root-relative, never a host.
    expect(WORKER_SRC.startsWith('/') || WORKER_SRC.startsWith('.')).toBe(true);
    expect(WORKER_SRC).toContain('pdf.worker');
    expect(hoisted.workerOptions.workerSrc).toBe(WORKER_SRC);
    const wiring = sources.find((file) => file.name === 'pdfjs.ts');
    expect(wiring?.text).toContain("from 'pdfjs-dist/build/pdf.worker.min.mjs?url'");
  });

  it('has no absolute URL and no CDN host anywhere in the pane', () => {
    for (const file of sources) {
      expect(file.code, `${file.name} must not reach off-origin`).not.toMatch(/https?:\/\//);
      expect(file.code, `${file.name} must not name a CDN`).not.toMatch(
        /cdn|unpkg|jsdelivr|esm\.sh/i,
      );
    }
  });

  it('does not import another pane', () => {
    for (const file of sources) {
      expect(file.code, `${file.name} must not import a sibling pane`).not.toMatch(
        /from '\.\.\/(chat|analyze|library)/,
      );
    }
  });
});

// --- opening a document --------------------------------------------------------

describe('opening a document', () => {
  it('renders from /api/pdf/{content_hash} with range requests left on', async () => {
    const doc = makeFakeDoc(3, { width: 612, height: 792 });
    serveDoc(doc);
    renderPane({ doc_hash: 'abc123', page: 1 });
    await screen.findByTestId('pdf-page');

    // The page really is painted onto the canvas at the current zoom.
    await waitFor(() => expect(doc.render).toHaveBeenCalledTimes(1));
    expect(doc.render.mock.calls[0][0]).toMatchObject({
      viewport: { width: 612, height: 792 },
    });
    const canvas = screen.getByTestId('pdf-canvas') as HTMLCanvasElement;
    expect(canvas.width).toBe(612);
    expect(canvas.height).toBe(792);

    expect(hoisted.getDocumentMock).toHaveBeenCalledTimes(1);
    expect(hoisted.getDocumentMock).toHaveBeenCalledWith(
      expect.objectContaining({ url: '/api/pdf/abc123', ...RANGE_REQUEST_OPTIONS }),
    );
    expect(RANGE_REQUEST_OPTIONS).toEqual({
      disableRange: false,
      disableStream: false,
      disableAutoFetch: true,
      rangeChunkSize: 65536,
    });
  });

  it('fetches only the cited page of a long document', async () => {
    const doc = makeFakeDoc(200, { width: 612, height: 792 });
    serveDoc(doc);
    renderPane({ doc_hash: 'long', page: 47 });
    await screen.findByTestId('pdf-page');

    await waitFor(() => expect(pageInput().value).toBe('47'));
    expect(doc.getPage).toHaveBeenCalledTimes(1);
    expect(doc.getPage).toHaveBeenCalledWith(47);
  });

  it('names the document when the PDF is missing, rather than going blank', async () => {
    failDocLoad(notFound());
    renderPane({ doc_hash: 'gone-hash', part: 'AFE7950', page: 1 });

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('AFE7950');
    expect(alert).toHaveTextContent('gone-hash');
    expect(alert.textContent).toMatch(/not.*in the library/i);
    expect(screen.queryByTestId('pdf-page')).toBeNull();
  });

  it('names the document for any other load failure too', async () => {
    failDocLoad(new Error('unexpected server response (500)'));
    renderPane({ doc_hash: 'broken-hash', part: 'LM741', page: 1 });

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('LM741');
    expect(alert).toHaveTextContent('broken-hash');
    expect(alert).toHaveTextContent('unexpected server response (500)');
  });

  it('says so plainly when no citation has been clicked yet', () => {
    render(createElement(PdfPane, { target: null }));
    expect(screen.getByText(/no document open/i)).toBeInTheDocument();
    expect(hoisted.getDocumentMock).not.toHaveBeenCalled();
  });
});

// --- the overlay ----------------------------------------------------------------

describe('the highlight overlay', () => {
  it('draws the located rects in position at 100% zoom', async () => {
    serveLocate({
      found: true,
      page: 5,
      rects: [rect(72, 100, 300, 120), rect(72, 130, 280, 150)],
      needle: 'Supply current',
      page_width: 612,
      page_height: 792,
    });
    renderPane({ doc_hash: 'abc123', page: 5, needle: 'Supply current' });

    const boxes = await screen.findAllByTestId('pdf-highlight');
    expect(boxes).toHaveLength(2);
    expect(styleOf(boxes[0])).toEqual({
      left: '72px',
      top: '100px',
      width: '228px',
      height: '20px',
    });
    expect(styleOf(boxes[1])).toEqual({
      left: '72px',
      top: '130px',
      width: '208px',
      height: '20px',
    });
    expect(locateUrls[0]).toContain('/api/locate?');
    expect(locateUrls[0]).toContain('doc_hash=abc123');
    expect(locateUrls[0]).toContain('page=5');
  });

  it('re-derives the box when the zoom changes', async () => {
    serveLocate({ found: true, page: 2, rects: [rect(72, 100, 300, 120)], needle: 'Vos' });
    renderPane({ doc_hash: 'abc123', page: 2, needle: 'Vos' });
    await screen.findByTestId('pdf-highlight');

    fireEvent.click(screen.getByLabelText('Zoom in')); // 100% -> 125%
    await waitFor(() => expect(zoomText()).toBe('125%'));
    await waitFor(() => {
      expect(styleOf(screen.getByTestId('pdf-highlight'))).toEqual({
        left: '90px',
        top: '125px',
        width: '285px',
        height: '25px',
      });
    });
  });

  it('re-derives the box when the window resizes under fit width', async () => {
    serveDoc(makeFakeDoc(2, { width: 600, height: 800 }));
    serveLocate({ found: true, page: 1, rects: [rect(60, 80, 300, 100)], needle: 'Vos' });
    stubbedClientWidth = 800; // 800 / 600pt = 1.3333
    renderPane({ doc_hash: 'abc123', page: 1, needle: 'Vos' });
    await screen.findByTestId('pdf-highlight');

    fireEvent.click(screen.getByLabelText('Fit width'));
    await waitFor(() => expect(zoomText()).toBe('133%'));
    await waitFor(() => expect(screen.getByTestId('pdf-highlight').style.left).toBe('80px'));

    stubbedClientWidth = 1200; // 1200 / 600pt = 2
    fireEvent(window, new Event('resize'));
    await waitFor(() => expect(zoomText()).toBe('200%'));
    expect(styleOf(screen.getByTestId('pdf-highlight'))).toEqual({
      left: '120px',
      top: '160px',
      width: '480px',
      height: '40px',
    });
  });

  it('stays aligned on a rotated page', async () => {
    serveDoc(makeFakeDoc(2, { width: 612, height: 792, rotate: 90 }));
    serveLocate({ found: true, page: 1, rects: [rect(0, 0, 12, 20)], needle: 'title' });
    renderPane({ doc_hash: 'rotated', page: 1, needle: 'title' });

    const box = await screen.findByTestId('pdf-highlight');
    // The page renders 792x612; the unrotated top-left sits at the top-right.
    expect(screen.getByTestId('pdf-page').style.width).toBe('792px');
    expect(screen.getByTestId('pdf-page').style.height).toBe('612px');
    expect(styleOf(box)).toEqual({
      left: '772px',
      top: '0px',
      width: '20px',
      height: '12px',
    });
  });

  it('announces the highlight to assistive technology', async () => {
    serveLocate({ found: true, page: 3, rects: [rect(10, 20, 30, 40)], needle: 'Vos' });
    renderPane({ doc_hash: 'abc123', page: 3, needle: 'Vos' });
    await screen.findByTestId('pdf-highlight');

    const status = screen.getByRole('status');
    expect(status).toHaveAttribute('aria-live', 'polite');
    expect(status).toHaveTextContent('Highlighted 1 region on page 3.');
  });

  it('opens the page with no highlight and shows the reason on an honest miss', async () => {
    serveLocate({
      found: false,
      page: 12,
      rects: [],
      reason: 'the cited row does not appear as printed on page 12',
      needle: 'Supply current',
    });
    renderPane({ doc_hash: 'abc123', page: 12, needle: 'Supply current' });

    await screen.findByTestId('pdf-page');
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent(
        'the cited row does not appear as printed on page 12',
      ),
    );
    expect(screen.queryAllByTestId('pdf-highlight')).toHaveLength(0);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('treats a failed locate call as a miss, never as an approximate box', async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: false,
      status: 404,
      json: async () => ({ detail: 'no such part: AFE7950' }),
    })) as unknown as typeof fetch;
    renderPane({ doc_hash: 'abc123', page: 4, needle: 'Supply current' });

    await screen.findByTestId('pdf-page');
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('no such part: AFE7950'),
    );
    expect(screen.queryAllByTestId('pdf-highlight')).toHaveLength(0);
  });

  it('never draws a highlight belonging to another page', async () => {
    serveLocate({ found: true, page: 2, rects: [rect(10, 20, 30, 40)], needle: 'Vos' });
    renderPane({ doc_hash: 'abc123', page: 2, needle: 'Vos' });
    await screen.findByTestId('pdf-highlight');

    fireEvent.click(screen.getByLabelText('Next page'));
    await waitFor(() => expect(pageInput().value).toBe('3'));
    expect(screen.queryAllByTestId('pdf-highlight')).toHaveLength(0);
  });

  it('asks nothing of /api/locate when the citation carries no needle', async () => {
    const fetchMock = serveLocate({});
    renderPane({ doc_hash: 'abc123', page: 1, needle: '' });
    await screen.findByTestId('pdf-page');
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryAllByTestId('pdf-highlight')).toHaveLength(0);
  });
});

// --- navigation is independent of citations ------------------------------------

describe('navigation, zoom and fit width', () => {
  it('pages forward and back with no citation in play', async () => {
    renderPane({ doc_hash: 'abc123', page: 1, needle: '' });
    await screen.findByTestId('pdf-page');

    expect(screen.getByLabelText('Previous page')).toBeDisabled();
    fireEvent.click(screen.getByLabelText('Next page'));
    await waitFor(() => expect(pageInput().value).toBe('2'));
    fireEvent.click(screen.getByLabelText('Next page'));
    await waitFor(() => expect(pageInput().value).toBe('3'));
    expect(screen.getByLabelText('Next page')).toBeDisabled();
    fireEvent.click(screen.getByLabelText('Previous page'));
    await waitFor(() => expect(pageInput().value).toBe('2'));
  });

  it('jumps to a typed page and clamps it to the document', async () => {
    renderPane({ doc_hash: 'abc123', page: 1, needle: '' });
    await screen.findByTestId('pdf-page');

    fireEvent.change(pageInput(), { target: { value: '3' } });
    await waitFor(() => expect(pageInput().value).toBe('3'));
    fireEvent.change(pageInput(), { target: { value: '99' } });
    await waitFor(() => expect(pageInput().value).toBe('3'));
  });

  it('zooms in and out through the toolbar', async () => {
    renderPane({ doc_hash: 'abc123', page: 1, needle: '' });
    await screen.findByTestId('pdf-page');

    expect(zoomText()).toBe('100%');
    fireEvent.click(screen.getByLabelText('Zoom in'));
    await waitFor(() => expect(zoomText()).toBe('125%'));
    expect(screen.getByTestId('pdf-page').style.width).toBe('765px');
    fireEvent.click(screen.getByLabelText('Zoom out'));
    fireEvent.click(screen.getByLabelText('Zoom out'));
    await waitFor(() => expect(zoomText()).toBe('75%'));
  });

  it('toggles fit width, and leaving it keeps the zoom it produced', async () => {
    serveDoc(makeFakeDoc(2, { width: 600, height: 800 }));
    stubbedClientWidth = 1200;
    renderPane({ doc_hash: 'abc123', page: 1, needle: '' });
    await screen.findByTestId('pdf-page');

    const fit = screen.getByLabelText('Fit width');
    fireEvent.click(fit);
    await waitFor(() => expect(zoomText()).toBe('200%'));
    expect(fit).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('pdf-page').style.width).toBe('1200px');

    fireEvent.click(screen.getByLabelText('Zoom in'));
    await waitFor(() => expect(fit).toHaveAttribute('aria-pressed', 'false'));
    expect(zoomText()).toBe('300%');
  });

  it('is keyboard navigable', async () => {
    renderPane({ doc_hash: 'abc123', page: 1, needle: '' });
    await screen.findByTestId('pdf-page');
    const viewer = screen.getByTestId('pdf-scroll');
    expect(viewer).toHaveAttribute('tabindex', '0');

    fireEvent.keyDown(viewer, { key: 'ArrowRight' });
    await waitFor(() => expect(pageInput().value).toBe('2'));
    fireEvent.keyDown(viewer, { key: 'PageDown' });
    await waitFor(() => expect(pageInput().value).toBe('3'));
    fireEvent.keyDown(viewer, { key: 'ArrowLeft' });
    await waitFor(() => expect(pageInput().value).toBe('2'));
    fireEvent.keyDown(viewer, { key: 'Home' });
    await waitFor(() => expect(pageInput().value).toBe('1'));
    fireEvent.keyDown(viewer, { key: 'End' });
    await waitFor(() => expect(pageInput().value).toBe('3'));

    fireEvent.keyDown(viewer, { key: '+' });
    await waitFor(() => expect(zoomText()).toBe('125%'));
    fireEvent.keyDown(viewer, { key: '-' });
    await waitFor(() => expect(zoomText()).toBe('100%'));
  });
});

// --- the citation click, through shared route state ----------------------------

interface HarnessProps {
  next: string;
}

function CitationHarness({ next }: HarnessProps) {
  const navigate = useNavigate();
  return createElement(
    Fragment,
    null,
    createElement(
      'button',
      { type: 'button', onClick: () => navigate(next) },
      'click a citation',
    ),
    createElement(PdfRoute),
  );
}

function renderRoute(initial: string, next: string) {
  return render(
    createElement(
      MemoryRouter,
      { initialEntries: [initial] },
      createElement(CitationHarness, { next }),
    ),
  );
}

describe('a citation click', () => {
  it('opens the right document at the right page', async () => {
    const first = makeFakeDoc(10, { width: 612, height: 792 });
    const second = makeFakeDoc(200, { width: 612, height: 792 });
    serveDocsByHash({ 'hash-a': first, 'hash-b': second });
    serveLocate({ found: true, page: 47, rects: [rect(72, 100, 300, 120)], needle: 'Vdd' });

    renderRoute('/pdf?doc=hash-a&part=LM741&page=2', '/pdf?doc=hash-b&part=AFE7950&page=47&needle=Vdd');
    await waitFor(() => expect(pageInput().value).toBe('2'));

    fireEvent.click(screen.getByText('click a citation'));

    await waitFor(() => expect(pageInput().value).toBe('47'));
    expect(hoisted.getDocumentMock).toHaveBeenCalledTimes(2);
    expect(hoisted.getDocumentMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ url: '/api/pdf/hash-b' }),
    );
    await waitFor(() => expect(second.getPage).toHaveBeenCalledWith(47));
    expect(second.getPage).toHaveBeenCalledTimes(1);
    await screen.findByTestId('pdf-highlight');
    expect(locateUrls.some((url) => url.includes('doc_hash=hash-b'))).toBe(true);
  });

  it('keeps the zoom, and the document, on a click into the same document', async () => {
    const doc = makeFakeDoc(50, { width: 612, height: 792 });
    serveDoc(doc);
    serveLocate({ found: true, page: 9, rects: [rect(72, 100, 300, 120)], needle: 'Vdd' });

    renderRoute('/pdf?doc=hash-a&part=LM741&page=3', '/pdf?doc=hash-a&part=LM741&page=9&needle=Vdd');
    await waitFor(() => expect(pageInput().value).toBe('3'));

    fireEvent.click(screen.getByLabelText('Zoom in'));
    fireEvent.click(screen.getByLabelText('Zoom in'));
    await waitFor(() => expect(zoomText()).toBe('150%'));

    fireEvent.click(screen.getByText('click a citation'));
    await waitFor(() => expect(pageInput().value).toBe('9'));

    // The document is not re-opened, and the user's zoom is not reset.
    expect(hoisted.getDocumentMock).toHaveBeenCalledTimes(1);
    expect(zoomText()).toBe('150%');
    const box = await screen.findByTestId('pdf-highlight');
    expect(styleOf(box)).toEqual({
      left: '108px',
      top: '150px',
      width: '342px',
      height: '30px',
    });
  });

  it('leaves a manually chosen page alone when the target does not change', async () => {
    serveDoc(makeFakeDoc(50, { width: 612, height: 792 }));
    renderRoute('/pdf?doc=hash-a&part=LM741&page=3', '/pdf?doc=hash-a&part=LM741&page=3');
    await waitFor(() => expect(pageInput().value).toBe('3'));

    fireEvent.click(screen.getByLabelText('Next page'));
    await waitFor(() => expect(pageInput().value).toBe('4'));

    fireEvent.click(screen.getByText('click a citation'));
    await waitFor(() => expect(pageInput().value).toBe('4'));
  });
});
