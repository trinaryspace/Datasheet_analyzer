/**
 * A citation, rendered inline as the retrieval core labelled it.
 *
 * The visible text is `citation.label` verbatim (`§4.5, p.7`). Nothing here
 * assembles `p.N`: the citation format is what `dsa verify` measures, and it
 * must not drift between the CLI, the MCP server and this application.
 *
 * It is a `<button>` rather than a styled `<span>` so Enter and Space activate
 * it for free — verification must not be mouse-only.
 *
 * Clicking calls `onOpen`, which writes the URL query. This component knows
 * nothing about the PDF pane and does not import it.
 */
import type { CitedItem } from './transcript';

export interface CitationLinkProps {
  item: CitedItem;
  onOpen: (item: CitedItem) => void;
}

/** `low` is the case the badge exists for: check the page before trusting it. */
function isLowConfidence(confidence: string): boolean {
  return confidence.trim().toLowerCase() === 'low';
}

export function CitationLink({ item, onOpen }: CitationLinkProps) {
  const { citation, confidence } = item;
  const low = isLowConfidence(confidence);
  return (
    <span className="chat-citation">
      <button
        type="button"
        className="chat-citation-link"
        data-part={citation.part}
        data-doc-hash={citation.doc_hash}
        data-page={citation.page_start ?? ''}
        title={`Open ${citation.doc} at ${citation.pages}`}
        aria-label={`Open citation ${citation.label} in ${citation.doc}`}
        onClick={() => onOpen(item)}
      >
        {citation.label}
      </button>
      {low ? (
        <span className="chat-confidence chat-confidence-low" data-confidence="low">
          low confidence
        </span>
      ) : null}
    </span>
  );
}

export default CitationLink;
