/**
 * The right half of the bookshelf: what is in the selected category.
 *
 * Two groups, and they are different claims about the world:
 *
 * - **Parts**, each with the documents that describe it. A part may hold
 *   several — datasheet, register map, errata — which is ADR 0005's relation
 *   working.
 * - **Supporting documents**, which apply to the *category* and to no part at
 *   all. "High frequency amplifier layout" is about every amplifier and is
 *   not a document *of* any one of them.
 *
 * Compact by construction: one line per document, detail on demand. The
 * previous screen put an applicability fieldset and two evidence paragraphs on
 * every row, which is why a shelf of twelve did not fit on a screen.
 *
 * Clicking any document opens it in the PDF pane, the same handoff a citation
 * click and the shelf rail already use.
 */
import type { CategoryOut, LibraryDocumentOut } from '../../api/types';

export interface PartGroup {
  part_number: string;
  built: boolean;
  documents: LibraryDocumentOut[];
}

export interface CategoryContentsProps {
  category: CategoryOut | null;
  parts: PartGroup[];
  /** Documents whose applicability is this category rather than any part. */
  supporting: LibraryDocumentOut[];
  /** Content hashes already on the open project's shelf. */
  inProject?: ReadonlySet<string>;
  onOpen: (document: LibraryDocumentOut) => void;
  onAddToProject?: (contentHash: string) => void;
  onEditDocument?: (document: LibraryDocumentOut) => void;
  onMovePart?: (partNumber: string) => void;
  /** Build an unbuilt part from the documents that reach it. */
  onBuild?: (group: PartGroup) => void;
  /** Drop a part from the open project. Absent hides the control. */
  onRemoveFromProject?: (partNumber: string) => void;
  /** Part numbers the open project holds. */
  projectParts?: ReadonlySet<string>;
}

function DocumentLine({
  document,
  inProject,
  onOpen,
  onAddToProject,
  onEditDocument,
}: {
  document: LibraryDocumentOut;
  inProject?: ReadonlySet<string>;
  onOpen: (d: LibraryDocumentOut) => void;
  onAddToProject?: (hash: string) => void;
  onEditDocument?: (d: LibraryDocumentOut) => void;
}) {
  const here = inProject?.has(document.content_hash);
  return (
    <li className="cat-doc" data-in-project={Boolean(here)}>
      <button
        type="button"
        className="cat-doc-open"
        onClick={() => onOpen(document)}
        // An explicit name: the button's content is filename plus type, page
        // count and labels, which makes for an accessible name nobody can
        // predict — including a screen-reader user.
        aria-label={`Open ${document.filename}`}
        title={`Open ${document.filename}`}
      >
        <span className="cat-doc-name">{document.filename}</span>
        <span className="cat-doc-meta">{document.doc_type || 'document'}</span>
        <span className="cat-doc-meta">{document.page_count}p</span>
        {document.labels.map((label) => (
          <span key={label} className="cat-doc-label">
            {label}
          </span>
        ))}
      </button>
      {onEditDocument ? (
        <button
          type="button"
          className="cat-doc-action"
          onClick={() => onEditDocument(document)}
          aria-label={`Edit ${document.filename}`}
        >
          Edit
        </button>
      ) : null}
      {onAddToProject ? (
        here ? (
          <span className="cat-doc-here">in project</span>
        ) : (
          <button
            type="button"
            className="cat-doc-action"
            onClick={() => onAddToProject(document.content_hash)}
            aria-label={`Add ${document.filename} to this project`}
          >
            + project
          </button>
        )
      ) : null}
    </li>
  );
}

export function CategoryContents({
  category,
  parts,
  supporting,
  inProject,
  onOpen,
  onAddToProject,
  onEditDocument,
  onMovePart,
  onBuild,
  onRemoveFromProject,
  projectParts,
}: CategoryContentsProps) {
  if (category === null) {
    return <p className="cat-empty">Pick a category on the left.</p>;
  }

  const empty = parts.length === 0 && supporting.length === 0;

  return (
    <section className="cat-contents" aria-label={`Contents of ${category.name}`}>
      <h3 className="cat-heading">{category.name}</h3>

      {empty ? (
        <p className="cat-empty">
          Nothing filed here yet. Build a part and confirm its category, or move one in.
        </p>
      ) : null}

      {parts.map((group) => (
        <details key={group.part_number} className="cat-part" open data-built={group.built}>
          <summary className="cat-part-summary">
            <span className="cat-part-name">{group.part_number}</span>
            <span className="cat-doc-meta">
              {group.documents.length === 1 ? '1 document' : `${group.documents.length} documents`}
            </span>
            {group.built ? null : <span className="cat-unbuilt">unbuilt</span>}
            {!group.built && onBuild ? (
              // The Library already knows which documents reach this part and
              // where they are; making the user go to Analyze and retype a
              // path it is holding would be the trip this button removes.
              <button
                type="button"
                className="cat-doc-action"
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  onBuild(group);
                }}
                aria-label={`Build ${group.part_number} from its documents`}
              >
                Build
              </button>
            ) : null}
            {onRemoveFromProject && projectParts?.has(group.part_number) ? (
              <button
                type="button"
                className="cat-doc-action"
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  onRemoveFromProject(group.part_number);
                }}
                aria-label={`Remove ${group.part_number} from this project`}
              >
                Remove
              </button>
            ) : null}
            {onMovePart ? (
              <button
                type="button"
                className="cat-doc-action"
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  onMovePart(group.part_number);
                }}
                aria-label={`Move ${group.part_number} to another category`}
              >
                Move
              </button>
            ) : null}
          </summary>
          <ul className="cat-docs">
            {group.documents.map((document) => (
              <DocumentLine
                key={document.content_hash}
                document={document}
                inProject={inProject}
                onOpen={onOpen}
                onAddToProject={onAddToProject}
                onEditDocument={onEditDocument}
              />
            ))}
          </ul>
        </details>
      ))}

      {supporting.length > 0 ? (
        <section className="cat-supporting" aria-label={`Supporting documents for ${category.name}`}>
          <h4>Supporting documents</h4>
          <p className="cat-supporting-note">
            Apply to every part in this category, and to no part on their own.
          </p>
          <ul className="cat-docs">
            {supporting.map((document) => (
              <DocumentLine
                key={document.content_hash}
                document={document}
                inProject={inProject}
                onOpen={onOpen}
                onAddToProject={onAddToProject}
                onEditDocument={onEditDocument}
              />
            ))}
          </ul>
        </section>
      ) : null}
    </section>
  );
}

export default CategoryContents;
