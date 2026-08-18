/**
 * Highlight geometry: PDF points in, canvas pixels out.
 *
 * `/api/locate` returns rectangles in **PDF points** — PyMuPDF's space, origin
 * at the page's top-left, x right, y down, unrotated, at zoom 1.0 (see
 * `RectOut` in `api/types.ts`). The canvas shows the page at the current zoom
 * and with the page's own rotation applied, so a rectangle has to be
 * transformed before it can be drawn.
 *
 * Every function here is pure and derives from the current zoom and rotation.
 * Nothing caches a pixel position: a cached box survives a zoom change looking
 * entirely plausible and pointing at the wrong row, and a box around the wrong
 * row turns verification into a lie. Re-derive instead.
 */
import type { LocateOut, RectOut } from '../../api/types';

/** The four rotations a PDF page may declare. There is no fifth. */
export type Rotation = 0 | 90 | 180 | 270;

/** A page as the overlay needs it: unrotated point size, plus its rotation. */
export interface PageGeometry {
  /** Unrotated page width in PDF points. */
  width: number;
  /** Unrotated page height in PDF points. */
  height: number;
  rotation: Rotation;
}

/** A rectangle in CSS pixels, relative to the page canvas's top-left. */
export interface PixelRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** The zoom levels the toolbar steps through. */
export const ZOOM_STEPS: readonly number[] = [0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4];

export const MIN_ZOOM = ZOOM_STEPS[0];
export const MAX_ZOOM = ZOOM_STEPS[ZOOM_STEPS.length - 1];

/** Snap any angle to the nearest legal rotation. A page may report -90 or 450. */
export function normalizeRotation(degrees: number): Rotation {
  if (!Number.isFinite(degrees)) return 0;
  const snapped = ((Math.round(degrees / 90) * 90) % 360 + 360) % 360;
  return snapped as Rotation;
}

/** True when the rotation swaps the page's width and height. */
export function isQuarterTurn(rotation: Rotation): boolean {
  return rotation === 90 || rotation === 270;
}

/** The canvas size, in CSS pixels, for a page at this zoom. */
export function displaySize(page: PageGeometry, scale: number): { width: number; height: number } {
  const swapped = isQuarterTurn(page.rotation);
  return {
    width: (swapped ? page.height : page.width) * scale,
    height: (swapped ? page.width : page.height) * scale,
  };
}

/**
 * One rectangle, converted.
 *
 * The rotation maps the unrotated top-left origin onto the displayed page:
 *
 * | rotation | unrotated (x, y) becomes |
 * |---|---|
 * | 0   | (x, y) |
 * | 90  | (H - y, x) |
 * | 180 | (W - x, H - y) |
 * | 270 | (y, W - x) |
 */
export function rectToPixels(rect: RectOut, page: PageGeometry, scale: number): PixelRect {
  const x0 = Math.min(rect.x0, rect.x1);
  const x1 = Math.max(rect.x0, rect.x1);
  const y0 = Math.min(rect.y0, rect.y1);
  const y1 = Math.max(rect.y0, rect.y1);
  const w = page.width;
  const h = page.height;

  let left: number;
  let top: number;
  let width: number;
  let height: number;

  switch (page.rotation) {
    case 90:
      left = h - y1;
      top = x0;
      width = y1 - y0;
      height = x1 - x0;
      break;
    case 180:
      left = w - x1;
      top = h - y1;
      width = x1 - x0;
      height = y1 - y0;
      break;
    case 270:
      left = y0;
      top = w - x1;
      width = y1 - y0;
      height = x1 - x0;
      break;
    default:
      left = x0;
      top = y0;
      width = x1 - x0;
      height = y1 - y0;
      break;
  }

  return {
    left: left * scale,
    top: top * scale,
    width: width * scale,
    height: height * scale,
  };
}

/**
 * Every rectangle to draw for a locate response — and none at all for a miss.
 *
 * `found: false` yields `[]`. There is deliberately no approximate fallback:
 * the honest miss is the whole point of the field.
 */
export function highlightRects(
  result: LocateOut | null,
  page: PageGeometry | null,
  scale: number,
): PixelRect[] {
  if (!result || !page || !result.found) return [];
  return result.rects.map((rect) => rectToPixels(rect, page, scale));
}

/** The zoom that makes the displayed page exactly fill `containerWidth`. */
export function fitWidthScale(containerWidth: number, page: PageGeometry): number {
  const displayedPoints = isQuarterTurn(page.rotation) ? page.height : page.width;
  if (containerWidth <= 0 || displayedPoints <= 0) return 1;
  return containerWidth / displayedPoints;
}

/** Keep a zoom inside the toolbar's range. */
export function clampZoom(scale: number): number {
  if (!Number.isFinite(scale)) return 1;
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, scale));
}

/** The next zoom step up (`direction > 0`) or down, saturating at the ends. */
export function nextZoom(scale: number, direction: number): number {
  const epsilon = 1e-6;
  if (direction > 0) {
    return ZOOM_STEPS.find((step) => step > scale + epsilon) ?? MAX_ZOOM;
  }
  const lower = ZOOM_STEPS.filter((step) => step < scale - epsilon);
  return lower.length > 0 ? lower[lower.length - 1] : MIN_ZOOM;
}

/** Round a pixel value for inline styling — sub-hundredth precision is noise. */
export function px(value: number): string {
  return `${Number(value.toFixed(2))}px`;
}
