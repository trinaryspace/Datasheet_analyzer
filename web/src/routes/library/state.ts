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
import type {
  Applicability,
  LibraryDocumentOut,
  RevisionState,
  Staleness,
} from '../../api/types';

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
    category:
      applicability.kind === 'category' ? (applicability.category ?? '').trim() : '',
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


// --- the bookshelf, seen through the open project (round 3) ----------------------

/**
 * Which documents the Library shows by default.
 *
 * The Library is the whole bookshelf — every *processed* document, from every
 * folder — and that is its job: it is where you go to find something that is
 * not in your project yet. But most of the time you want the shelf you are
 * working on, so the project scopes it and one toggle opens the rest.
 *
 * Scoped by *file location*, not by the project's part list: a project's
 * documents are the PDFs sitting in its folder, and its part list is a
 * different thing that may lag behind or be deliberately narrower.
 */
export function inProjectFolder(document: LibraryDocumentOut, directory: string): boolean {
  if (!directory) return false;
  return underDirectory(document.path, directory);
}

/** Path containment, tolerant of separator and case differences. */
export function underDirectory(path: string, directory: string): boolean {
  const norm = (value: string) =>
    value.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();
  const file = norm(path);
  const root = norm(directory);
  if (!root) return false;
  return file === root || file.startsWith(`${root}/`);
}

/** Split the bookshelf into what is already on this shelf and what is not. */
export function partitionByProject(
  documents: LibraryDocumentOut[],
  directory: string,
): { inProject: LibraryDocumentOut[]; elsewhere: LibraryDocumentOut[] } {
  const inProject: LibraryDocumentOut[] = [];
  const elsewhere: LibraryDocumentOut[] = [];
  for (const document of documents) {
    (inProjectFolder(document, directory) ? inProject : elsewhere).push(document);
  }
  return { inProject, elsewhere };
}

// --- the structured bookshelf (round 4) ------------------------------------------

/** Which category a document's *applicability* names, or `''` if it names none. */
export function supportingCategory(document: LibraryDocumentOut): string {
  return document.applicability.kind === 'category'
    ? (document.applicability.category ?? '').trim()
    : '';
}

/**
 * Split a category's contents into its parts and its supporting documents.
 *
 * Two different claims, and the Library must not blur them: a datasheet is a
 * document *of* a part, while a layout note is about the whole category and
 * belongs to no part at all. A supporting document therefore appears once,
 * under the category — not repeated under every part it reaches, which is
 * what the part-first grouping would otherwise do to it.
 */
export function categoryContents(
  documents: LibraryDocumentOut[],
  partCategory: ReadonlyMap<string, string>,
  categoryId: string,
  builtParts: ReadonlySet<string>,
): { parts: { part_number: string; built: boolean; documents: LibraryDocumentOut[] }[];
     supporting: LibraryDocumentOut[] } {
  const supporting: LibraryDocumentOut[] = [];
  const byPart = new Map<string, LibraryDocumentOut[]>();

  for (const document of documents) {
    if (supportingCategory(document) === categoryId) {
      supporting.push(document);
      continue;
    }
    for (const part of document.parts_reached) {
      // A part with no record reads `uncategorized`, which is a real slot.
      if ((partCategory.get(part) ?? 'uncategorized') !== categoryId) continue;
      const bucket = byPart.get(part);
      if (bucket) bucket.push(document);
      else byPart.set(part, [document]);
    }
  }

  const parts = [...byPart.entries()]
    .map(([part_number, docs]) => ({
      part_number,
      built: builtParts.has(part_number),
      documents: docs,
    }))
    .sort((a, b) => a.part_number.localeCompare(b.part_number));

  return { parts, supporting };
}

// --- upstream freshness (phase 7, ticket 02) -------------------------------------

/**
 * One document's freshness reading, ready to render.
 *
 * The words are mirrored by hand from `staleness.banner_text` in the Python
 * package, which is the one place this sentence is written and which the CLI,
 * the `INDEX.md` banner, the `dsa audit` metric and the answer-pack footer all
 * call. This is a fifth surface, and the rule it inherits is the rule that
 * matters: **`unknown` is the default and it is not `current`.** A corpus that
 * has never been checked reads "not checked" and says which command clears it.
 * Reading "nobody checked" as "still current" is the inversion the whole
 * ticket exists to prevent — it is the difference between a designer knowing
 * they are on their own and believing they were told.
 *
 * The second rule, equally load-bearing: **a hash difference is never
 * staleness.** A vendor that regenerates a PDF with today's date on every
 * download moves the bytes of an unchanged revision daily, so `content_drift`
 * is worded as "regenerated", never as "revised", and never implies a new
 * revision exists.
 */
export interface RevisionReading {
  staleness: Staleness;
  /** The badge's word: `not checked`, `superseded`, `current`. */
  label: string;
  /** The whole sentence — the badge's tooltip and its accessible name. */
  detail: string;
  /**
   * True when this is something a designer must be shown. Mirrors
   * `CorpusStaleness.warns`: anything but `current`, plus a `current` reading
   * whose bytes drifted.
   */
  warns: boolean;
}

/** The command that clears an `unknown`, named in every message that has one. */
export const CHECK_COMMAND = 'dsa check-revisions';

/** `2026-08-01` from an ISO timestamp; `''` when there is none to print. */
function checkedOn(checkedAt: string | null): string {
  const text = (checkedAt ?? '').trim();
  return text ? text.slice(0, 10) : '';
}

/**
 * The drift sentence — worded so it can never read as a new revision.
 *
 * Mirrors `staleness._drift_sentence`: bytes moved, the printed revision did
 * not, so the document was regenerated rather than revised.
 */
function driftSentence(): string {
  return (
    'Upstream’s bytes differ but its revision identifier has not moved: the document was ' +
    'regenerated, not revised — this is not evidence of a new revision.'
  );
}

/** What one document's `revision_state` says, in words a person can act on. */
export function describeRevision(state: RevisionState | null | undefined): RevisionReading {
  const staleness: Staleness =
    state?.staleness === 'current' || state?.staleness === 'stale' ? state.staleness : 'unknown';
  const note = (state?.note ?? '').trim();
  const checked = checkedOn(state?.checked_at ?? null);
  const drift = Boolean(state?.content_drift);

  if (staleness === 'stale') {
    const upstream = (state?.upstream_revision ?? '').trim() || 'a different revision';
    return {
      staleness,
      label: 'superseded',
      detail:
        `Superseded: ${upstream} is available upstream` +
        (checked ? ` (checked ${checked})` : '') +
        '. Verify before committing to silicon.' +
        (note ? ` ${note}` : ''),
      warns: true,
    };
  }

  if (staleness === 'current') {
    // "Current" is never an unqualified reassurance: it carries the date the
    // claim was made, because a check from six months ago is a different fact
    // from a check this morning.
    const detail =
      `Revision current: confirmed against upstream${checked ? ` (checked ${checked})` : ''}.` +
      (drift ? ` ${driftSentence()}` : '') +
      (note ? ` ${note}` : '');
    return { staleness, label: 'current', detail, warns: drift };
  }

  return {
    staleness,
    // Not the word `unknown`, which reads as a shrug. "Not checked" names who
    // did not do what, and the sentence names the command that fixes it.
    label: 'not checked',
    detail:
      'Revision not checked: this document has never been confirmed against upstream' +
      (note ? ` — ${note}` : '') +
      `. Run \`${CHECK_COMMAND}\` before relying on it for a design decision.`,
    warns: true,
  };
}

/** Worst first: `stale`, then `unknown`, then `current`. */
const SEVERITY: Record<Staleness, number> = { stale: 0, unknown: 1, current: 2 };

/**
 * The reading for a set of documents: the least fresh one, datasheet first.
 *
 * Mirrors `staleness.corpus_staleness`. A part is only as fresh as its least
 * fresh document — a current datasheet beside an unchecked register map is not
 * a current part, because the register map is what a bring-up question is
 * answered from. Ties go to the datasheet, which is the document that speaks
 * for the part. An empty set reads `unknown`, because "there is nothing here"
 * and "nobody has checked" are both un-checked and neither is `current`.
 */
export function worstRevision(documents: LibraryDocumentOut[]): RevisionReading {
  const ranked = [...documents].sort((a, b) => {
    const bySeverity =
      SEVERITY[describeRevision(a.revision_state).staleness] -
      SEVERITY[describeRevision(b.revision_state).staleness];
    if (bySeverity !== 0) return bySeverity;
    const rank = (document: LibraryDocumentOut) => (document.doc_type === 'datasheet' ? 0 : 1);
    return rank(a) - rank(b);
  });
  return describeRevision(ranked[0]?.revision_state ?? null);
}
