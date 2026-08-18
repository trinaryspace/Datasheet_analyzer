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
    const rank = ATTENTION_RANK[attentionReason(a)] - ATTENTION_RANK[attentionReason(b)];
    if (rank !== 0) return rank;
    return displayName(a).localeCompare(displayName(b));
  });
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
