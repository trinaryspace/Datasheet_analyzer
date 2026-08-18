/**
 * One part in the condensed library: a collapsed summary, expanding to the
 * documents that reach it.
 *
 * The shelf is read part-first because that is how the question gets asked —
 * "what do I know about the AFE7950" — while applicability, labels and
 * evidence remain per-document, because that is what they are attached to
 * (ADR 0005). So the part is the row and the document is what the row opens
 * onto; a document reaching three parts appears under all three, which is the
 * relation working rather than duplication.
 *
 * `<details>`/`<summary>` rather than a button and a state flag: it is
 * open/closed semantics the browser already has, keyboard-operable and
 * screen-reader-labelled for free, and it survives a re-render without the
 * screen having to remember which rows were open.
 */
import type { ComponentType } from 'react';

import type { LibraryDocumentOut } from '../../api/types';
import { DocumentRow } from './DocumentRow';
import type { ApplicabilityControlProps } from './shellPrimitives';
import type { PartGroup } from './state';

export interface PartGroupRowProps {
  group: PartGroup;
  knownLabels: string[];
  applicabilityControl: ComponentType<ApplicabilityControlProps> | null;
  onPatched: (next: LibraryDocumentOut) => void;
  /** Present only while a project is selected; absent hides the control. */
  onRemoveFromProject?: (partNumber: string) => void;
  /** Open on first render — used for a single search result. */
  defaultOpen?: boolean;
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

export function PartGroupRow({
  group,
  knownLabels,
  applicabilityControl,
  onPatched,
  onRemoveFromProject,
  defaultOpen = false,
}: PartGroupRowProps) {
  const { part_number: part, built, documents, labels } = group;

  return (
    <details className="library-part" data-part={part} data-built={built} open={defaultOpen}>
      <summary className="library-part-summary">
        <span className="library-part-name">{part}</span>
        <span className="library-part-meta">
          {plural(documents.length, 'document', 'documents')}
        </span>
        {built ? null : (
          <span className="library-part-unbuilt" title="No corpus has been built for this part yet">
            unbuilt
          </span>
        )}
        {labels.map((name) => (
          <span key={name} className="library-part-label">
            {name}
          </span>
        ))}
        {onRemoveFromProject ? (
          // Inside `<summary>`, so the click must not also toggle the row.
          <button
            type="button"
            className="library-part-remove"
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              onRemoveFromProject(part);
            }}
            aria-label={`Remove ${part} from this project`}
          >
            Remove
          </button>
        ) : null}
      </summary>

      <div className="library-part-body">
        {documents.map((document) => (
          <DocumentRow
            key={document.content_hash}
            document={document}
            knownLabels={knownLabels}
            applicabilityControl={applicabilityControl}
            onPatched={onPatched}
          />
        ))}
      </div>
    </details>
  );
}

export default PartGroupRow;
