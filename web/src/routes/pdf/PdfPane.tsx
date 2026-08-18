/**
 * The PDF pane: the reason the application exists.
 *
 * An answer is only verified when the user has seen the row it came from, so
 * this pane opens the cited document at the cited page and draws the
 * rectangles `/api/locate` returns. It reads its target from the URL (see
 * `target.ts`) and imports no other pane.
 *
 * Three behaviours are deliberate rather than incidental:
 *
 * - **The overlay is a layer above the canvas, re-derived every paint.** Zoom
 *   and rotation are applied on the fly from the rectangles' PDF points, never
 *   cached as pixels, so a resize cannot leave a plausible box in the wrong
 *   place.
 * - **`found: false` draws nothing.** The server's `reason` is shown quietly
 *   and the page still opens. Approximating the location would turn a
 *   verification step into a lie, which is the one failure this feature cannot
 *   have.
 * - **Navigation is independent of citations.** Page, zoom and fit-width work
 *   with no citation at all, and a citation into the already-open document
 *   keeps the user's zoom instead of resetting the pane.
 */
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import { ApiError, locate as locateCitation, pdfUrl } from '../../api/client';
import type { LocateOut, PdfTarget } from '../../api/types';
import './pdf.css';
import {
  clampZoom,
  displaySize,
  fitWidthScale,
  highlightRects,
  nextZoom,
  normalizeRotation,
  px,
  type PageGeometry,
} from './geometry';
import {
  isCancellation,
  isMissingPdf,
  loadPdf,
  type PdfDocumentProxy,
  type PdfPageProxy,
} from './pdfjs';
import { documentLabel } from './target';

export interface PdfPaneProps {
  /** Which document, page and needle to show; `null` renders the empty state. */
  target: PdfTarget | null;
}

interface LoadedPage {
  proxy: PdfPageProxy;
  page: number;
  geometry: PageGeometry;
}

function describeLoadFailure(error: unknown, label: string): string {
  if (isMissingPdf(error)) {
    return `${label} could not be opened: no PDF with that content hash is in the library.`;
  }
  const detail =
    error instanceof ApiError
      ? error.detail
      : error instanceof Error
        ? error.message
        : String(error);
  return `${label} could not be opened: ${detail}`;
}

function missFromError(page: number, needle: string, error: unknown): LocateOut {
  const reason =
    error instanceof ApiError
      ? error.detail
      : error instanceof Error
        ? error.message
        : String(error);
  return {
    found: false,
    page,
    rects: [],
    reason,
    needle,
    page_width: 0,
    page_height: 0,
    rotation: 0,
  };
}

export function PdfPane({ target }: PdfPaneProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  const [doc, setDoc] = useState<PdfDocumentProxy | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [loadedPage, setLoadedPage] = useState<LoadedPage | null>(null);
  const [fixedScale, setFixedScale] = useState(1);
  const [fitWidth, setFitWidth] = useState(false);
  const [containerWidth, setContainerWidth] = useState(0);
  const [locateResult, setLocateResult] = useState<LocateOut | null>(null);

  const targetHash = target?.doc_hash ?? '';
  const targetPart = target?.part ?? '';
  const targetPage = target?.page ?? 0;
  const targetNeedle = target?.needle ?? '';

  // The label is only read when a load fails, so it travels in a ref rather
  // than in the effect's dependencies — a changed `part` must not re-fetch an
  // already-open document.
  const label = documentLabel(target);
  const labelRef = useRef(label);
  labelRef.current = label;

  // --- the document -----------------------------------------------------------

  useEffect(() => {
    if (!targetHash) {
      setDoc(null);
      setLoadError(null);
      setLoadedPage(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    const task = loadPdf(pdfUrl(targetHash));
    task.promise.then(
      (loaded) => {
        if (cancelled) {
          void loaded.destroy?.();
          return;
        }
        setDoc(loaded);
        setLoading(false);
      },
      (error: unknown) => {
        if (cancelled || isCancellation(error)) return;
        setDoc(null);
        setLoadedPage(null);
        setLoading(false);
        setLoadError(describeLoadFailure(error, labelRef.current));
      },
    );
    return () => {
      cancelled = true;
      task.destroy();
    };
  }, [targetHash]);

  /** A citation names a page; a page the document does not have is clamped. */
  useEffect(() => {
    if (targetPage >= 1) setPageNumber(targetPage);
  }, [targetHash, targetPage]);

  useEffect(() => {
    if (!doc) return;
    setPageNumber((current) => Math.min(Math.max(current, 1), Math.max(doc.numPages, 1)));
  }, [doc]);

  // --- the page ---------------------------------------------------------------

  useEffect(() => {
    if (!doc) {
      setLoadedPage(null);
      return;
    }
    let cancelled = false;
    doc.getPage(pageNumber).then(
      (proxy) => {
        if (cancelled) return;
        const base = proxy.getViewport({ scale: 1, rotation: 0 });
        setLoadedPage({
          proxy,
          page: pageNumber,
          geometry: {
            width: base.width,
            height: base.height,
            rotation: normalizeRotation(proxy.rotate ?? 0),
          },
        });
      },
      (error: unknown) => {
        if (cancelled || isCancellation(error)) return;
        setLoadError(describeLoadFailure(error, labelRef.current));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [doc, pageNumber]);

  // --- zoom -------------------------------------------------------------------

  const geometry = loadedPage?.geometry ?? null;

  const scale = useMemo(() => {
    if (fitWidth && geometry && containerWidth > 0) {
      return clampZoom(fitWidthScale(containerWidth, geometry));
    }
    return fixedScale;
  }, [fitWidth, geometry, containerWidth, fixedScale]);

  /** Width is measured, never assumed: fit-width must survive a window resize. */
  useLayoutEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const measure = () => setContainerWidth(element.clientWidth);
    measure();
    window.addEventListener('resize', measure);
    let observer: ResizeObserver | undefined;
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(measure);
      observer.observe(element);
    }
    return () => {
      window.removeEventListener('resize', measure);
      observer?.disconnect();
    };
  }, []);

  // --- painting ---------------------------------------------------------------

  const size = geometry ? displaySize(geometry, scale) : null;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !loadedPage || !size) return;
    const ratio = Math.min(Math.max(window.devicePixelRatio || 1, 1), 2);
    canvas.width = Math.max(1, Math.round(size.width * ratio));
    canvas.height = Math.max(1, Math.round(size.height * ratio));
    canvas.style.width = px(size.width);
    canvas.style.height = px(size.height);
    const context = canvas.getContext('2d');
    // jsdom has no 2D context; the overlay geometry is still exercised there.
    if (!context) return;
    const task = loadedPage.proxy.render({
      canvasContext: context,
      viewport: loadedPage.proxy.getViewport({ scale: scale * ratio }),
    });
    return () => task.cancel();
  }, [loadedPage, scale, size?.width, size?.height]);

  // --- the highlight ----------------------------------------------------------

  useEffect(() => {
    if (!targetHash || !targetNeedle) {
      setLocateResult(null);
      return;
    }
    let cancelled = false;
    locateCitation({
      part: targetPart,
      doc_hash: targetHash,
      page: targetPage,
      needle: targetNeedle,
    }).then(
      (result) => {
        if (!cancelled) setLocateResult(result);
      },
      (error: unknown) => {
        if (!cancelled) setLocateResult(missFromError(targetPage, targetNeedle, error));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [targetHash, targetPart, targetPage, targetNeedle]);

  /** Derived every render from the live zoom and rotation — never cached. */
  const highlights = useMemo(() => {
    if (!locateResult || !loadedPage) return [];
    if (locateResult.page !== loadedPage.page) return [];
    return highlightRects(locateResult, loadedPage.geometry, scale);
  }, [locateResult, loadedPage, scale]);

  const announcement = useMemo(() => {
    if (!locateResult) return '';
    if (!locateResult.found) {
      return `No highlight on page ${locateResult.page}: ${
        locateResult.reason || 'the cited text was not found on that page'
      }`;
    }
    if (locateResult.page !== loadedPage?.page) {
      return `Highlight is on page ${locateResult.page}, which is not the page shown.`;
    }
    const n = highlights.length;
    return `Highlighted ${n} ${n === 1 ? 'region' : 'regions'} on page ${locateResult.page}.`;
  }, [locateResult, highlights.length, loadedPage?.page]);

  // --- controls ---------------------------------------------------------------

  const numPages = doc?.numPages ?? 0;

  const goToPage = useCallback(
    (page: number) => {
      const upper = numPages > 0 ? numPages : page;
      setPageNumber(Math.min(Math.max(Math.round(page), 1), Math.max(upper, 1)));
    },
    [numPages],
  );

  const zoomBy = useCallback(
    (direction: number) => {
      setFitWidth(false);
      setFixedScale((current) => nextZoom(fitWidth ? scale : current, direction));
    },
    [fitWidth, scale],
  );

  const onKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLDivElement>) => {
      const focused = event.target as HTMLElement;
      if (focused.tagName === 'INPUT') return;
      switch (event.key) {
        case 'ArrowRight':
        case 'PageDown':
          goToPage(pageNumber + 1);
          break;
        case 'ArrowLeft':
        case 'PageUp':
          goToPage(pageNumber - 1);
          break;
        case 'Home':
          goToPage(1);
          break;
        case 'End':
          goToPage(numPages || 1);
          break;
        case '+':
        case '=':
          zoomBy(1);
          break;
        case '-':
          zoomBy(-1);
          break;
        case '0':
          setFitWidth(false);
          setFixedScale(1);
          break;
        default:
          return;
      }
      event.preventDefault();
    },
    [goToPage, numPages, pageNumber, zoomBy],
  );

  // --- render -----------------------------------------------------------------

  if (!target) {
    return (
      <section className="pdf-pane pdf-pane--empty" aria-label="PDF viewer">
        <p className="pdf-empty">
          No document open. Click a citation on an answer and its page opens here.
        </p>
      </section>
    );
  }

  const pageLabel = numPages > 0 ? `Page ${pageNumber} of ${numPages}` : `Page ${pageNumber}`;

  return (
    <section className="pdf-pane" aria-label="PDF viewer">
      <div className="pdf-toolbar" role="toolbar" aria-label="PDF controls">
        <button
          type="button"
          onClick={() => goToPage(pageNumber - 1)}
          disabled={pageNumber <= 1}
          aria-label="Previous page"
        >
          ‹
        </button>
        <input
          className="pdf-page-input"
          type="number"
          min={1}
          max={numPages || undefined}
          value={pageNumber}
          aria-label="Page number"
          onChange={(event) => {
            const value = Number.parseInt(event.target.value, 10);
            if (Number.isFinite(value)) goToPage(value);
          }}
        />
        <span className="pdf-page-count">{numPages > 0 ? `of ${numPages}` : 'of ?'}</span>
        <button
          type="button"
          onClick={() => goToPage(pageNumber + 1)}
          disabled={numPages > 0 && pageNumber >= numPages}
          aria-label="Next page"
        >
          ›
        </button>
        <span className="pdf-toolbar-gap" />
        <button type="button" onClick={() => zoomBy(-1)} aria-label="Zoom out">
          −
        </button>
        <span className="pdf-zoom" data-testid="pdf-zoom">
          {Math.round(scale * 100)}%
        </span>
        <button type="button" onClick={() => zoomBy(1)} aria-label="Zoom in">
          +
        </button>
        <button
          type="button"
          onClick={() => setFitWidth((on) => !on)}
          aria-pressed={fitWidth}
          aria-label="Fit width"
        >
          Fit width
        </button>
        <span className="pdf-doc-label" title={target.doc_hash}>
          {target.part || target.doc_hash.slice(0, 12)}
        </span>
      </div>

      <p className="pdf-highlight-status" role="status" aria-live="polite">
        {announcement}
      </p>

      {loadError ? (
        <p className="pdf-error" role="alert">
          {loadError}
        </p>
      ) : null}

      <div
        className="pdf-scroll"
        ref={containerRef}
        role="region"
        tabIndex={0}
        aria-label={`${pageLabel} of ${label}`}
        onKeyDown={onKeyDown}
        data-testid="pdf-scroll"
      >
        {loading && !loadError ? <p className="pdf-loading">Opening {label}…</p> : null}
        {!loadError && size ? (
          <div
            className="pdf-page"
            data-testid="pdf-page"
            style={{ width: px(size.width), height: px(size.height) }}
          >
            <canvas
              className="pdf-canvas"
              ref={canvasRef}
              role="img"
              aria-label={`${pageLabel}, rendered`}
              data-testid="pdf-canvas"
            />
            <div className="pdf-highlight-layer" aria-hidden="true" data-testid="pdf-highlight-layer">
              {highlights.map((rect, index) => (
                <div
                  key={`${rect.left}:${rect.top}:${index}`}
                  className="pdf-highlight"
                  data-testid="pdf-highlight"
                  style={{
                    left: px(rect.left),
                    top: px(rect.top),
                    width: px(rect.width),
                    height: px(rect.height),
                  }}
                />
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}

export default PdfPane;
