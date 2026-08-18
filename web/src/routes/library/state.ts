/**
 * The library screen's model: pure functions, no React, no fetch.
 *
 * Filtering, label editing and applicability validation all live here so the
 * rules can be tested without a DOM, and so the screen component stays a
 * rendering of state rather than a place where rules hide.
 *
 * One rule is load-bearing: `validateApplicability` is a **guard**, not an
 * editor. The editor is the shell's `ApplicabilityControl` (ticket 16), which
 * this screen imports rather than reimplements. The guard exists because the
 * screen is what calls `PATCH /api/library/{hash}`, and an applicability that
 * cannot mean anything — `kind: "parts"` with no parts — must be stopped here
 * rather than sent and rejected.
 */
import type { Applicability, LibraryDocumentOut } from '../../api/types';

/** The empty value of either filter: no filtering at all. */
export const NO_FILTER = '';

/** The two axes the list filters on, both optional and independent. */
export interface LibraryFilters {
  /** A label a document must carry. */
  label: string;
  /** A part a document must reach, built or not. */
  part: string;
}

/** No filters applied. */
export const NO_FILTERS: LibraryFilters = { label: NO_FILTER, part: NO_FILTER };

function unique(values: Iterable<string>): string[] {
  return [...new Set([...values].map((value) => value.trim()).filter(Boolean))];
}

/**
 * Every label in use across the documents, sorted.
 *
 * `LibraryOut.labels` is the server's own list and is the primary source for
 * autocomplete; this merges in anything a just-applied patch added, so a label
 * created a second ago is suggestable without a refetch.
 */
export function collectLabels(documents: LibraryDocumentOut[], seed: string[] = []): string[] {
  return unique([...seed, ...documents.flatMap((document) => document.labels)]).sort((a, b) =>
    a.localeCompare(b),
  );
}

/** Every part any document reaches, built or unbuilt, sorted. */
export function collectParts(documents: LibraryDocumentOut[]): string[] {
  return unique(documents.flatMap((document) => document.parts_reached)).sort((a, b) =>
    a.localeCompare(b),
  );
}

/** The documents matching both filters; an empty filter matches everything. */
export function filterDocuments(
  documents: LibraryDocumentOut[],
  filters: LibraryFilters,
): LibraryDocumentOut[] {
  const label = filters.label.trim();
  const part = filters.part.trim();
  return documents.filter((document) => {
    if (label && !document.labels.includes(label)) return false;
    if (part && !document.parts_reached.includes(part)) return false;
    return true;
  });
}

/**
 * Why this applicability may not be sent, or `''` when it may.
 *
 * The message is written to be rendered: it says what to do, not merely that
 * something is wrong.
 */
export function validateApplicability(applicability: Applicability): string {
  switch (applicability?.kind) {
    case 'all':
      return '';
    case 'parts': {
      const parts = unique(applicability.parts ?? []);
      if (parts.length === 0) {
        return 'Name at least one part, or choose a family or all parts.';
      }
      return '';
    }
    case 'family': {
      if (!(applicability.family ?? '').trim()) {
        return 'A family applicability needs a family prefix, for example AFE79xx.';
      }
      return '';
    }
    default:
      return 'Applicability must be parts, family or all.';
  }
}

/** The applicability as the row prints it, one line. */
export function describeApplicability(applicability: Applicability): string {
  switch (applicability?.kind) {
    case 'parts':
      return `Parts: ${unique(applicability.parts ?? []).join(', ') || '(none)'}`;
    case 'family':
      return `Family: ${applicability.family || '(none)'}`;
    case 'all':
      return 'All parts';
    default:
      return 'Unknown applicability';
  }
}

/** The applicability trimmed to exactly what its `kind` reads — what gets sent. */
export function normalizeApplicability(applicability: Applicability): Applicability {
  return {
    kind: applicability.kind,
    parts: applicability.kind === 'parts' ? unique(applicability.parts ?? []) : [],
    family: applicability.kind === 'family' ? (applicability.family ?? '').trim() : '',
    evidence: applicability.evidence ?? '',
  };
}

/** `labels` plus `label`, trimmed, with an existing label (any case) left alone. */
export function addLabel(labels: string[], label: string): string[] {
  const next = label.trim();
  if (!next) return labels;
  if (labels.some((held) => held.toLowerCase() === next.toLowerCase())) return labels;
  return [...labels, next];
}

/** `labels` without `label`, compared case-insensitively. */
export function removeLabel(labels: string[], label: string): string[] {
  return labels.filter((held) => held.toLowerCase() !== label.toLowerCase());
}

/**
 * Autocomplete: labels already in use, minus the ones this document carries,
 * matching `query` as a substring. An empty query offers everything available.
 */
export function labelSuggestions(
  known: string[],
  current: string[],
  query: string,
  limit = 8,
): string[] {
  const needle = query.trim().toLowerCase();
  const held = new Set(current.map((label) => label.toLowerCase()));
  return known
    .filter((label) => !held.has(label.toLowerCase()))
    .filter((label) => !needle || label.toLowerCase().includes(needle))
    .slice(0, limit);
}

/** The list with `next` in place of the document sharing its `content_hash`. */
export function replaceDocument(
  documents: LibraryDocumentOut[],
  next: LibraryDocumentOut,
): LibraryDocumentOut[] {
  return documents.map((document) =>
    document.content_hash === next.content_hash ? next : document,
  );
}

/**
 * The rebuild offer's sentence, or `''` when there is nothing to offer.
 *
 * Deliberately an offer and not a warning: widening applicability to a part
 * that does not exist yet is legal (ADR 0005), and the parts are named because
 * "a rebuild is needed" without saying of what is not actionable.
 */
export function rebuildOffer(parts: string[]): string {
  if (parts.length === 0) return '';
  const named = parts.join(', ');
  return parts.length === 1
    ? `Build ${named} to make this document part of its corpus.`
    : `Build ${named} to make this document part of their corpora.`;
}

/** The message an unknown thrown value should be rendered as. */
export function errorMessage(error: unknown, fallback = 'the request failed'): string {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === 'string' && error) return error;
  return fallback;
}

// --- grouping by part (condensed library) -------------------------------------

/** One collapsed row: a part, and every document that reaches it. */
export interface PartGroup {
  part_number: string;
  /** False when nothing under `parts/` has been built for it yet (ADR 0005). */
  built: boolean;
  documents: LibraryDocumentOut[];
  labels: string[];
}

/**
 * Turn the flat document list into one row per part.
 *
 * A part is the *view* of the documents that apply to it (ADR 0005), so a
 * document reaching three parts appears under all three — that is the model
 * working, not duplication to be removed. A document that reaches nothing yet
 * would otherwise vanish from a part-first list, so it is collected under
 * `orphanLabel` rather than dropped: the library must never hide a file it
 * holds.
 *
 * `built` is false when every document that reaches the part says so, which
 * is what `unbuilt_parts` records. Sorted by part number, orphans last.
 */
export function groupByPart(
  documents: LibraryDocumentOut[],
  orphanLabel = 'Not yet assigned to a part',
): PartGroup[] {
  const groups = new Map<string, PartGroup>();

  const push = (part: string, document: LibraryDocumentOut, built: boolean) => {
    let group = groups.get(part);
    if (!group) {
      group = { part_number: part, built, documents: [], labels: [] };
      groups.set(part, group);
    }
    // One document calling the part built is enough; `unbuilt_parts` is
    // per-document and a part with a real corpus is built for all of them.
    group.built = group.built || built;
    group.documents.push(document);
    for (const label of document.labels) {
      if (!group.labels.includes(label)) group.labels.push(label);
    }
  };

  for (const document of documents) {
    if (document.parts_reached.length === 0) {
      push(orphanLabel, document, false);
      continue;
    }
    for (const part of document.parts_reached) {
      push(part, document, !document.unbuilt_parts.includes(part));
    }
  }

  return [...groups.values()].sort((a, b) => {
    if (a.part_number === orphanLabel) return 1;
    if (b.part_number === orphanLabel) return -1;
    return a.part_number.localeCompare(b.part_number);
  });
}

/**
 * Keep only the groups whose part the project holds.
 *
 * An empty `partNumbers` means "no project selected" and everything is shown —
 * the working set narrows the shelf, it never becomes the only way to see it.
 */
export function filterGroupsToProject(
  groups: PartGroup[],
  partNumbers: string[],
): PartGroup[] {
  if (partNumbers.length === 0) return groups;
  const wanted = new Set(partNumbers);
  return groups.filter((group) => wanted.has(group.part_number));
}
