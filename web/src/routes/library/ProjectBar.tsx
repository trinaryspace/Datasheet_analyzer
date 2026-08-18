/**
 * The working-set control: which project the library is being read through.
 *
 * A project is the shelf for *this* design. Selecting one narrows the library
 * to its parts; "All documents" is always available, because the working set
 * is a lens over the shelf and never the only way to reach a file.
 *
 * It is a project rather than a new "collection" concept for one decisive
 * reason: a project is already one of the two things a question may be scoped
 * to (ADR 0006). A separate collection would let a user assemble one set and
 * then ask a question of a different one.
 *
 * Parts are added here rather than documents: under ADR 0005 a project that
 * names its parts already names their documents, and putting a *document*
 * into a project means widening its applicability — which is the document's
 * own applicability editor, one row below.
 */
import { useState } from 'react';

import type { ProjectOut } from '../../api/types';

/** The sentinel for "no project": the whole library, unnarrowed. */
export const ALL_DOCUMENTS = '';

export interface ProjectBarProps {
  projects: ProjectOut[];
  selected: string;
  /** Parts present in the library but not yet in the selected project. */
  addableParts: string[];
  busy?: boolean;
  error?: string;
  onSelect: (name: string) => void;
  onCreate: (name: string) => void;
  onAddPart: (partNumber: string) => void;
}

export function ProjectBar({
  projects,
  selected,
  addableParts,
  busy = false,
  error = '',
  onSelect,
  onCreate,
  onAddPart,
}: ProjectBarProps) {
  const [newName, setNewName] = useState('');
  const [partToAdd, setPartToAdd] = useState('');

  const submitNew = () => {
    const name = newName.trim();
    if (!name) return;
    onCreate(name);
    setNewName('');
  };

  return (
    // Not "Working set": that is the select's own label, and two elements
    // answering to one accessible name is ambiguous to a screen reader and to
    // `getByLabelText` alike.
    <section className="library-projects" aria-label="Working set controls">
      <div className="library-projects-row">
        <label htmlFor="library-project">Working set</label>
        <select
          id="library-project"
          value={selected}
          disabled={busy}
          onChange={(event) => onSelect(event.target.value)}
        >
          <option value={ALL_DOCUMENTS}>All documents</option>
          {projects.map((project) => (
            <option key={project.name} value={project.name}>
              {project.name}
              {project.parts.length ? ` (${project.parts.length})` : ''}
            </option>
          ))}
        </select>

        <input
          type="text"
          aria-label="New project name"
          placeholder="new project…"
          value={newName}
          disabled={busy}
          onChange={(event) => setNewName(event.target.value)}
          onKeyDown={(event) => {
            if (event.key !== 'Enter') return;
            event.preventDefault();
            submitNew();
          }}
        />
        <button type="button" onClick={submitNew} disabled={busy || !newName.trim()}>
          Create
        </button>
      </div>

      {selected === ALL_DOCUMENTS ? null : (
        <div className="library-projects-row">
          <label htmlFor="library-project-add">{`Add a part to ${selected}`}</label>
          <select
            id="library-project-add"
            value={partToAdd}
            disabled={busy || addableParts.length === 0}
            onChange={(event) => setPartToAdd(event.target.value)}
          >
            <option value="">
              {addableParts.length === 0 ? 'every part is already in' : 'choose a part…'}
            </option>
            {addableParts.map((part) => (
              <option key={part} value={part}>
                {part}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={busy || !partToAdd}
            onClick={() => {
              onAddPart(partToAdd);
              setPartToAdd('');
            }}
          >
            Add
          </button>
        </div>
      )}

      {error ? (
        <p className="library-projects-error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}

export default ProjectBar;
