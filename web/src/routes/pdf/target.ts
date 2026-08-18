/**
 * The PDF pane's target, read from — and written to — the URL query.
 *
 * Cross-pane state travels in the URL (see `App.tsx` and the `PDF_PARAM_*`
 * constants in `api/types.ts`), so the pane that answers a question and the
 * pane that verifies it never import each other. A citation click writes
 * `?doc=&part=&page=&needle=`; this module is the only place that decodes it.
 */
import {
  PDF_PARAM_DOC,
  PDF_PARAM_NEEDLE,
  PDF_PARAM_PAGE,
  PDF_PARAM_PART,
  type CitationOut,
  type PdfTarget,
} from '../../api/types';

type ParamSource = URLSearchParams | string;

function asParams(source: ParamSource): URLSearchParams {
  return typeof source === 'string' ? new URLSearchParams(source) : source;
}

function readPage(raw: string | null): number {
  const page = Number.parseInt(raw ?? '', 10);
  return Number.isFinite(page) && page >= 1 ? page : 0;
}

/**
 * Decode a target, or `null` when no document is named.
 *
 * A missing or unparseable page yields `0`, which the pane reads as "no jump
 * requested" — it holds the page the user is on rather than snapping to 1.
 */
export function readPdfTarget(source: ParamSource): PdfTarget | null {
  const params = asParams(source);
  const docHash = (params.get(PDF_PARAM_DOC) ?? '').trim();
  if (!docHash) return null;
  return {
    doc_hash: docHash,
    part: (params.get(PDF_PARAM_PART) ?? '').trim(),
    page: readPage(params.get(PDF_PARAM_PAGE)),
    needle: params.get(PDF_PARAM_NEEDLE) ?? '',
  };
}

/** Encode a target back into a query string, for a link or a test. */
export function pdfTargetSearch(target: PdfTarget): string {
  const params = new URLSearchParams();
  params.set(PDF_PARAM_DOC, target.doc_hash);
  if (target.part) params.set(PDF_PARAM_PART, target.part);
  if (target.page >= 1) params.set(PDF_PARAM_PAGE, String(target.page));
  if (target.needle) params.set(PDF_PARAM_NEEDLE, target.needle);
  return params.toString();
}

/**
 * The target a citation points at.
 *
 * `page_start` is the cited page; a citation spanning pages opens at its
 * first, which is where the cited block begins.
 */
export function targetFromCitation(citation: CitationOut, needle = ''): PdfTarget {
  return {
    doc_hash: citation.doc_hash,
    part: citation.part,
    page: citation.page_start ?? 0,
    needle: needle || citation.section,
  };
}

/** Two targets naming the same document — the document need not be reloaded. */
export function sameDocument(a: PdfTarget | null, b: PdfTarget | null): boolean {
  return Boolean(a && b && a.doc_hash === b.doc_hash);
}

/** How to name this document to a human when something goes wrong. */
export function documentLabel(target: PdfTarget | null): string {
  if (!target) return 'no document';
  return target.part ? `${target.part} · ${target.doc_hash}` : target.doc_hash;
}
