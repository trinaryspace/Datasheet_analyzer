/**
 * Pure helpers over a scan's proposals: attention ranking and row ordering.
 *
 * Kept out of the components so the sort — the thing that makes forty rows
 * take one glance — is testable without a DOM.
 */
import type { Applicability, DocProposal } from '../../api/types';

/** Why a row floated. Rendered as the row's badge, in this order. */
export type AttentionReason = 'unresolved' | 'multi-part' | 'confident';

/** Rank 0 sorts first. The three ranks are the three reasons, in order. */
export const ATTENTION_RANK: Record<AttentionReason, number> = {
  unresolved: 0,
  'multi-part': 1,
  confident: 2,
};

/** Human sentence for a row's attention state. */
export const ATTENTION_LABEL: Record<AttentionReason, string> = {
  unresolved: 'Needs attention',
  'multi-part': 'Applies to several parts',
  confident: 'Confident',
};

/**
 * Why one proposal does or does not need a second look.
 *
 * `kind: "all"` is inference's honest fallback — it means "could not be
 * determined", which is precisely what a human should see first. A blank
 * part number is the same case from the other side: nothing was inferred.
 */
export function attentionReason(proposal: DocProposal): AttentionReason {
  const applicability = proposal.applicability;
  if (!proposal.part_number.trim()) return 'unresolved';
  if (applicability.kind === 'all') return 'unresolved';
  if (applicability.kind === 'family') return 'multi-part';
  if (applicability.kind === 'parts') {
    if (applicability.parts.length === 0) return 'unresolved';
    if (applicability.parts.length > 1) return 'multi-part';
  }
  return 'confident';
}

/**
 * Rows needing attention first, then multi-part documents, then the
 * confident singles; alphabetical by filename inside each band so the order
 * is stable across re-renders and re-scans.
 */
export function sortProposals(proposals: DocProposal[]): DocProposal[] {
  return [...proposals].sort((a, b) => {
    // What will actually rebuild comes first: on a rescan of a mostly-current
    // shelf, the two rows that matter must not be buried under thirty-eight
    // that do not.
    const work = Number(isCurrent(a)) - Number(isCurrent(b));
    if (work !== 0) return work;
    const rank = ATTENTION_RANK[attentionReason(a)] - ATTENTION_RANK[attentionReason(b)];
    if (rank !== 0) return rank;
    return displayName(a).localeCompare(displayName(b));
  });
}

/** `current` is the only state that costs nothing. */
export function isCurrent(proposal: DocProposal): boolean {
  return proposal.build_state === 'current';
}

/** Every document is already built and current — there is nothing to do. */
export function nothingToBuild(scan: { proposals: DocProposal[] }): boolean {
  return scan.proposals.length > 0 && scan.proposals.every(isCurrent);
}

/**
 * "38 current, 2 will rebuild — 1 stale, 1 changed".
 *
 * Built from the rows rather than `ScanOut.states` so it stays correct after
 * an edit on this screen, and so it works for any subset a caller hands it.
 */
export function summarise(proposals: DocProposal[]): string {
  const tally = new Map<string, number>();
  for (const p of proposals) tally.set(p.build_state, (tally.get(p.build_state) ?? 0) + 1);

  const current = tally.get('current') ?? 0;
  const rebuild = proposals.length - current;
  if (rebuild === 0) return `${current} already built and current`;

  const detail = (['new', 'stale', 'changed'] as const)
    .filter((state) => tally.get(state))
    .map((state) => `${tally.get(state)} ${state}`)
    .join(', ');
  const head = current > 0 ? `${current} current, ${rebuild} will rebuild` : `${rebuild} will build`;
  return detail ? `${head} — ${detail}` : head;
}

/** A one-line description of what an applicability covers. */
export function describeApplicability(applicability: Applicability): string {
  if (applicability.kind === 'parts') {
    return applicability.parts.length > 0 ? applicability.parts.join(', ') : 'no parts named';
  }
  if (applicability.kind === 'family') {
    return applicability.family ? `family ${applicability.family}` : 'family not named';
  }
  return 'all parts';
}

/** The last path segment, for either separator; the server sends both. */
export function basename(path: string): string {
  const segments = path.split(/[\\/]/);
  return segments[segments.length - 1] ?? path;
}

/** What a row is called: the scan's filename, falling back to its path. */
export function displayName(proposal: DocProposal): string {
  return proposal.filename || basename(proposal.pdf_path);
}

/** A stable React key: the content hash when the scan computed one. */
export function proposalKey(proposal: DocProposal): string {
  return proposal.content_hash || proposal.pdf_path;
}

// --- selection (tickets 26-30) ---------------------------------------------------

/** The identity a selection and an exclusion are both keyed on. */
export function selectionKey(proposal: DocProposal): string {
  return proposal.content_hash || proposal.pdf_path;
}

/**
 * Which rows start ticked.
 *
 * The default click should build exactly the work that needs doing, so the
 * three states that end in a build start on and everything else starts off:
 *
 * - `current` — already built and current; ticking it costs time for nothing.
 * - previously excluded — the user already said no to this document in this
 *   project, and a recursive walk re-proposes it on every single scan.
 * - not a source document — a purchase order that happens to live beside the
 *   datasheets. Unticked rather than hidden, so a wrong guess costs one click.
 */
export function defaultSelection(
  proposals: DocProposal[],
  excluded: readonly string[],
): Set<string> {
  const rejected = new Set(excluded);
  const chosen = new Set<string>();
  for (const proposal of proposals) {
    const key = selectionKey(proposal);
    if (rejected.has(proposal.content_hash)) continue;
    if (isCurrent(proposal)) continue;
    if (!proposal.is_datasheet) continue;
    chosen.add(key);
  }
  return chosen;
}

/** One group of the review: the documents found in one subdirectory. */
export interface FolderGroup {
  /** Relative to the folder opened; `''` is the top level. */
  directory: string;
  proposals: DocProposal[];
}

/**
 * Group by the subdirectory a document was found in.
 *
 * A recursive walk makes folder structure carry the user's intent —
 * `reference/` and `competitors/` are junk wholesale — so excluding a folder
 * of twelve should be one click, not twelve. Top level first, then
 * alphabetical; within a group, whatever will rebuild comes first.
 */
export function groupByFolder(proposals: DocProposal[]): FolderGroup[] {
  const groups = new Map<string, DocProposal[]>();
  for (const proposal of proposals) {
    const key = proposal.relative_dir ?? '';
    const bucket = groups.get(key);
    if (bucket) bucket.push(proposal);
    else groups.set(key, [proposal]);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => {
      if (a === b) return 0;
      if (a === '') return -1;
      if (b === '') return 1;
      return a.localeCompare(b);
    })
    .map(([directory, rows]) => ({ directory, proposals: sortProposals(rows) }));
}
