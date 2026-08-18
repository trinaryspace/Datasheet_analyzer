/**
 * The Library screen: the shelf, read part-first, through a working set.
 *
 * Three things stack here, outermost first.
 *
 * **The working set.** A project narrows the shelf to the parts of one design.
 * It is a project and not a new concept because a project is already what a
 * question may be scoped to (ADR 0006) — so the set you assemble is the set
 * you can then ask.
 *
 * **The part.** One collapsed row per part, expanding to the documents that
 * reach it. Reach is derived from applicability, so a document can legally
 * reach a part that does not exist yet (ADR 0005); those parts read `unbuilt`
 * and the server's `rebuild_needed` becomes an offer naming them, never a
 * warning about a mistake the user did not make.
 *
 * **The document.** Applicability, labels and evidence stay per-document,
 * because that is what they belong to. A document reaching three parts is
 * listed under all three.
 *
 * Every server call goes through `api/client.ts`. The applicability editor is
 * the shell's `ApplicabilityControl`, discovered rather than duplicated.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ComponentType } from 'react';

import { useNavigate } from 'react-router-dom';

import {
  addProjectParts,
  createProject,
  getLibrary,
  getProjects,
  removeProjectPart,
  startAnalyze,
} from '../../api/client';
import type { DocProposal, LibraryDocumentOut, ProjectOut } from '../../api/types';
import { PartGroupRow } from './PartGroupRow';
import { useWorkingSet } from '../../shell/workingSet';
import { ALL_DOCUMENTS, ProjectBar } from './ProjectBar';
import { getApplicabilityControl } from './shellPrimitives';
import type { ApplicabilityControlProps } from './shellPrimitives';
import {
  NO_FILTER,
  NO_FILTERS,
  collectLabels,
  collectParts,
  errorMessage,
  filterDocuments,
  filterGroupsToProject,
  groupByPart,
  replaceDocument,
} from './state';
import type { LibraryFilters } from './state';
import './library.css';

/** Route metadata read by `App.tsx`'s filesystem route discovery. */
export const path = '/library';
export const label = 'Library';
export const order = 30;

type LoadState = 'loading' | 'ready' | 'error';

export interface LibraryScreenProps {
  /**
   * The applicability editor. Defaults to the shell's control; the tests pass
   * a stub so the screen's own behaviour is testable before ticket 16 lands.
   */
  applicabilityControl?: ComponentType<ApplicabilityControlProps> | null;
}

export function LibraryScreen({ applicabilityControl = null }: LibraryScreenProps) {
  const [status, setStatus] = useState<LoadState>('loading');
  const [error, setError] = useState('');
  const [documents, setDocuments] = useState<LibraryDocumentOut[]>([]);
  const [serverLabels, setServerLabels] = useState<string[]>([]);
  const [filters, setFilters] = useState<LibraryFilters>(NO_FILTERS);
  const [projects, setProjects] = useState<ProjectOut[]>([]);
  // The working set is app-wide (shell/workingSet), not this screen's state:
  // a project chosen here is the context Chat and Analyze inherit too.
  const { project: selectedProject, setProject: setSelectedProject } = useWorkingSet();
  const [projectBusy, setProjectBusy] = useState(false);
  const navigate = useNavigate();
  const [projectError, setProjectError] = useState('');

  const load = useCallback(async () => {
    setStatus('loading');
    setError('');
    try {
      const library = await getLibrary();
      setDocuments(library.documents);
      setServerLabels(library.labels);
      setStatus('ready');
    } catch (caught) {
      setError(errorMessage(caught, 'the library could not be read'));
      setStatus('error');
    }
    // Projects are a lens, not the content: failing to read them leaves the
    // library fully usable, so this never turns the screen into an error.
    try {
      setProjects((await getProjects()).projects);
    } catch (caught) {
      setProjectError(errorMessage(caught, 'projects could not be read'));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const knownLabels = useMemo(
    () => collectLabels(documents, serverLabels),
    [documents, serverLabels],
  );
  const knownParts = useMemo(() => collectParts(documents), [documents]);
  const visible = useMemo(() => filterDocuments(documents, filters), [documents, filters]);

  const project = useMemo(
    () => projects.find((candidate) => candidate.name === selectedProject) ?? null,
    [projects, selectedProject],
  );
  const projectParts = useMemo(
    () => (project ? project.parts.map((member) => member.part_number) : []),
    [project],
  );
  const groups = useMemo(
    () => filterGroupsToProject(groupByPart(visible), projectParts),
    [visible, projectParts],
  );
  // Only built parts are offered: `add_parts` requires a real part directory,
  // so listing an unbuilt one would be an option that always fails. It is not
  // hidden from the shelf — it is listed there, badged `unbuilt`, with the
  // rebuild offer that makes it joinable.
  const addableParts = useMemo(() => {
    const built = new Set(
      groupByPart(documents)
        .filter((group) => group.built)
        .map((group) => group.part_number),
    );
    return knownParts.filter((part) => built.has(part) && !projectParts.includes(part));
  }, [documents, knownParts, projectParts]);

  // Counted across the groups actually on screen, and deduplicated: one
  // document reaching three parts is listed three times but is still one
  // document, and the working set narrows which of those rows survive.
  const shownDocuments = useMemo(
    () => new Set(groups.flatMap((group) => group.documents.map((d) => d.content_hash))).size,
    [groups],
  );

  const onPatched = useCallback((next: LibraryDocumentOut) => {
    setDocuments((current) => replaceDocument(current, next));
  }, []);

  /**
   * Build an unbuilt part from the documents that already reach it.
   *
   * A library document carries `path`, `part_number` and `applicability` —
   * which is a `DocProposal` — so this is an ordinary run through the existing
   * endpoint rather than a new one. Progress is handed to the Analyze screen's
   * run view; a second progress UI here would be the same thing twice.
   */
  const buildPart = useCallback(
    async (group: { part_number: string; documents: LibraryDocumentOut[] }) => {
      setProjectError('');
      const proposals: DocProposal[] = group.documents.map((doc) => ({
        pdf_path: doc.path,
        filename: doc.filename,
        part_number: group.part_number,
        applicability: doc.applicability,
        evidence: doc.applicability.evidence,
        page_count: doc.page_count,
        doc_type: doc.doc_type,
        content_hash: doc.content_hash,
        build_state: 'new',
        build_reason: `${group.part_number} has no corpus yet`,
      }));
      // The run view shows the directory; use the one the documents actually
      // live in rather than a blank, which would read as "nowhere".
      const first = group.documents[0]?.path ?? '';
      const directory = first.replace(/[/\\][^/\\]*$/, '');
      try {
        const started = await startAnalyze({ directory, proposals });
        navigate(`/analyze?run=${encodeURIComponent(started.run_id)}`);
      } catch (caught) {
        setProjectError(errorMessage(caught, `${group.part_number} could not be built`));
      }
    },
    [navigate],
  );

  /** Run one project write, then replace the row it returned. */
  const runProjectWrite = useCallback(
    async (write: () => Promise<ProjectOut>, onDone?: (project: ProjectOut) => void) => {
      setProjectBusy(true);
      setProjectError('');
      try {
        const next = await write();
        setProjects((current) => {
          const without = current.filter((candidate) => candidate.name !== next.name);
          return [...without, next].sort((a, b) => a.name.localeCompare(b.name));
        });
        onDone?.(next);
      } catch (caught) {
        setProjectError(errorMessage(caught, 'the project could not be changed'));
      } finally {
        setProjectBusy(false);
      }
    },
    [],
  );

  if (status === 'loading') {
    return (
      <main aria-labelledby="library-heading">
        <h2 id="library-heading">Library</h2>
        <p role="status">Loading the library…</p>
      </main>
    );
  }

  if (status === 'error') {
    return (
      <main aria-labelledby="library-heading">
        <h2 id="library-heading">Library</h2>
        <p role="alert">{error}</p>
        <button type="button" onClick={() => void load()}>
          Retry
        </button>
      </main>
    );
  }

  return (
    <main aria-labelledby="library-heading">
      <h2 id="library-heading">Library</h2>

      <ProjectBar
        projects={projects}
        selected={selectedProject}
        addableParts={addableParts}
        busy={projectBusy}
        error={projectError}
        onSelect={setSelectedProject}
        onCreate={(name) =>
          void runProjectWrite(
            () => createProject({ name }),
            (created) => setSelectedProject(created.name),
          )
        }
        onAddPart={(partNumber) => {
          if (!project) return;
          void runProjectWrite(() => addProjectParts(project.name, { parts: [partNumber] }));
        }}
      />

      {documents.length === 0 ? (
        <p className="library-empty">
          The library is empty. Analyze a directory of PDFs and every document lands here.
        </p>
      ) : (
        <>
          <form className="library-filters" aria-label="Filter the library">
            <label htmlFor="library-filter-label">Filter by label</label>
            <select
              id="library-filter-label"
              value={filters.label}
              onChange={(event) =>
                setFilters((current) => ({ ...current, label: event.target.value }))
              }
            >
              <option value={NO_FILTER}>All labels</option>
              {knownLabels.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>

            <label htmlFor="library-filter-part">Filter by part</label>
            <select
              id="library-filter-part"
              value={filters.part}
              onChange={(event) =>
                setFilters((current) => ({ ...current, part: event.target.value }))
              }
            >
              <option value={NO_FILTER}>All parts</option>
              {knownParts.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>

            <button type="button" onClick={() => setFilters(NO_FILTERS)}>
              Clear filters
            </button>
          </form>

          <p className="library-count" role="status">
            {`${groups.length === 1 ? '1 part' : `${groups.length} parts`}, ` +
              `${shownDocuments} of ${documents.length} documents`}
          </p>

          {groups.length === 0 ? (
            <p className="library-empty">
              {projectParts.length > 0
                ? `Nothing in ${selectedProject} matches these filters.`
                : 'No document matches these filters.'}
            </p>
          ) : (
            <div className="library-list">
              {groups.map((group) => (
                <PartGroupRow
                  key={group.part_number}
                  group={group}
                  knownLabels={knownLabels}
                  applicabilityControl={applicabilityControl}
                  onPatched={onPatched}
                  defaultOpen={groups.length === 1}
                  onBuild={group.built ? undefined : (g) => void buildPart(g)}
                  onRemoveFromProject={
                    project && projectParts.includes(group.part_number)
                      ? (partNumber) =>
                          void runProjectWrite(() =>
                            removeProjectPart(project.name, partNumber),
                          )
                      : undefined
                  }
                />
              ))}
            </div>
          )}
        </>
      )}
    </main>
  );
}

export default function LibraryRoute() {
  return <LibraryScreen applicabilityControl={getApplicabilityControl()} />;
}
