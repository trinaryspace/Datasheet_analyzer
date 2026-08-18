/**
 * PDF.js, wired for a machine with no internet.
 *
 * Two things are load-bearing here and both are the reason this file exists
 * rather than a `getDocument` call inline in the pane.
 *
 * **The worker is a bundled asset, never a CDN URL.** `?url` makes Vite emit
 * `pdf.worker.min.mjs` into `dist/assets` and hand back its local path, so the
 * app works with the network unplugged. A remotely hosted worker — the shape
 * every PDF.js snippet on the web uses — would make the viewer fail exactly
 * where this application is meant to run.
 *
 * **Range requests are left switched on.** `GET /api/pdf/{content_hash}`
 * serves `206 Partial Content`, and `disableAutoFetch` stops PDF.js from
 * quietly streaming the rest of the file once the first chunk lands. Opening
 * page 47 of a 200-page datasheet then costs page 47, which is precisely the
 * document where it matters.
 */
import { GlobalWorkerOptions, getDocument } from 'pdfjs-dist';
import workerSrc from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

GlobalWorkerOptions.workerSrc = workerSrc;

/** The bundled worker's URL — same-origin, asserted by the tests. */
export const WORKER_SRC: string = workerSrc;

/**
 * Fetch only what a page needs.
 *
 * - `disableRange: false` — issue HTTP range requests.
 * - `disableStream: false` — read the response as it arrives.
 * - `disableAutoFetch: true` — do **not** backfill the rest of the document.
 * - `rangeChunkSize` — 64 KiB, PDF.js's own default, stated so it is visible.
 */
export const RANGE_REQUEST_OPTIONS = {
  disableRange: false,
  disableStream: false,
  disableAutoFetch: true,
  rangeChunkSize: 65536,
} as const;

/** A viewport as the pane uses it — PDF.js returns more; this is what we read. */
export interface PageViewport {
  width: number;
  height: number;
}

/** A cancellable paint. Cancelling a superseded render is not an error. */
export interface RenderTask {
  promise: Promise<void>;
  cancel: () => void;
}

/** The slice of `PDFPageProxy` the pane touches. */
export interface PdfPageProxy {
  /** The page's own rotation, in degrees. */
  rotate: number;
  getViewport(params: { scale: number; rotation?: number }): PageViewport;
  render(params: { canvasContext: CanvasRenderingContext2D; viewport: PageViewport }): RenderTask;
  cleanup?: () => void;
}

/** The slice of `PDFDocumentProxy` the pane touches. */
export interface PdfDocumentProxy {
  numPages: number;
  getPage(pageNumber: number): Promise<PdfPageProxy>;
  destroy?: () => Promise<void> | void;
}

/** An in-flight document load. `destroy()` aborts it; safe from a cleanup. */
export interface PdfLoadTask {
  promise: Promise<PdfDocumentProxy>;
  destroy: () => void;
}

/**
 * Open `url` as a PDF, reading it in ranges.
 *
 * The URL comes from `pdfUrl(content_hash)` in the API client — PDF.js is
 * handed the URL rather than bytes precisely so it can do its own ranged
 * reads.
 */
export function loadPdf(url: string): PdfLoadTask {
  const task = getDocument({ url, ...RANGE_REQUEST_OPTIONS }) as unknown as {
    promise: Promise<PdfDocumentProxy>;
    destroy?: () => Promise<void> | void;
  };
  return {
    promise: task.promise,
    destroy: () => {
      try {
        void task.destroy?.();
      } catch {
        // A load that already settled has nothing to abort.
      }
    },
  };
}

/** True when a rejection is a render/load cancellation rather than a failure. */
export function isCancellation(error: unknown): boolean {
  const name = (error as { name?: unknown } | null)?.name;
  return name === 'RenderingCancelledException' || name === 'AbortException';
}

/** True when the document simply is not there — a 404 from the PDF route. */
export function isMissingPdf(error: unknown): boolean {
  const candidate = error as { name?: unknown; status?: unknown } | null;
  return candidate?.name === 'MissingPDFException' || candidate?.status === 404;
}
