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
  addToShelf,
  createCategory,
  createProject,
  getCategories,
  getLibrary,
  getParts,
  getProjects,
  removeCategory,
  removeProjectPart,
  renameCategory,
  setPartCategory,
  startAnalyze,
} from '../../api/client';
import type {
  CategoryOut,
  DocProposal,
  LibraryDocumentOut,
  PartOut,
  ProjectOut,
} from '../../api/types';
import { CategoryContents } from './CategoryContents';
import { CategoryTree } from './CategoryTree';
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
  categoryContents,
  filterGroupsToProject,
  groupByPart,
  partitionByProject,
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
  // The Library is the whole bookshelf; the project is the default lens on it.
  // `false` opens the rest, which is what the screen exists for when you are
  // looking for something you have *not* got yet.
  const [scopeToProject, setScopeToProject] = useState(true);
  const navigate = useNavigate();
  const [projectError, setProjectError] = useState('');
  const [projectNote, setProjectNote] = useState('');
  const [categories, setCategories] = useState<CategoryOut[]>([]);
  /** Part number to category id, straight from the taxonomy response. */
  const [filed, setFiled] = useState<Record<string, string>>({});
  const [catalog, setCatalog] = useState<PartOut[]>([]);
  const [selectedCategory, setSelectedCategory] = useState('');
  const [editing, setEditing] = useState<LibraryDocumentOut | null>(null);

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
    // The taxonomy and the catalog are what make this a bookshelf rather than
    // a list. Neither failing should cost the user the documents themselves.
    try {
      const [taxonomy, parts] = await Promise.all([getCategories(), getParts()]);
      setCategories(taxonomy.categories);
      setFiled(taxonomy.parts);
      setCatalog(parts.parts);
      setSelectedCategory((current) => current || taxonomy.categories[0]?.id || '');
    } catch (caught) {
      setProjectError(errorMessage(caught, 'the taxonomy could not be read'));
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
  // Split by where the file lives, not by the project's part list: a
  // project's documents are the PDFs in its folder, and its part list is a
  // different thing that lags behind.
  const split = useMemo(
    () => partitionByProject(visible, project?.directory ?? ''),
    [visible, project],
  );
  // Folder-scoped when the project has a folder; otherwise fall back to its
  // part list. A project made by hand — before the open-a-folder flow existed,
  // or created from the Library — has no directory, and scoping it by one
  // would show nothing at all.
  const shown = useMemo(() => {
    if (!scopeToProject || !project) return visible;
    if (project.directory) return split.inProject;
    return filterDocuments(
      visible.filter((doc) => doc.parts_reached.some((p) => projectParts.includes(p))),
      NO_FILTERS,
    );
  }, [scopeToProject, project, visible, split, projectParts]);
  const groups = useMemo(() => groupByPart(shown), [shown]);
  const inProjectHashes = useMemo(
    () => new Set(split.inProject.map((d) => d.content_hash)),
    [split],
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

  /** Copy a document's PDF onto the open project's shelf. */
  const addToProject = useCallback(
    async (contentHash: string) => {
      if (!project) return;
      setProjectError('');
      try {
        const added = await addToShelf(project.name, { content_hash: contentHash });
        // Say what happened: "already there" and "copied under a new name"
        // are both outcomes the user needs to know about.
        setProjectNote(
          added.copied
            ? added.renamed
              ? added.reason
              : `Copied ${added.document.filename} into ${project.name}.`
            : added.reason || 'Already on this shelf.',
        );
        await load();
      } catch (caught) {
        setProjectError(errorMessage(caught, 'that document could not be added'));
      }
    },
    [project, load],
  );

  // Which category each part is filed in, and which parts are actually built.
  // The filing comes from the taxonomy response — the same part records the
  // counts beside each category are computed from — and not from the parts
  // catalog, which knows only what is *built*. Reading it from the catalog
  // made a category read "3" and then open empty.
  const partCategory = useMemo(() => new Map(Object.entries(filed)), [filed]);
  const builtParts = useMemo(
    () => new Set(catalog.filter((part) => part.built).map((part) => part.part_number)),
    [catalog],
  );
  const contents = useMemo(
    () => categoryContents(shown, partCategory, selectedCategory, builtParts),
    [shown, partCategory, selectedCategory, builtParts],
  );

  /** Open a document in the PDF pane — the same handoff a citation uses. */
  const openDocument = useCallback(
    (document: LibraryDocumentOut) => {
      const query = new URLSearchParams({
        doc: document.content_hash,
        part: document.part_number || '',
        page: '1',
      });
      navigate(`/library?${query.toString()}`, { replace: false });
    },
    [navigate],
  );

  /** Run one taxonomy write and refresh the tree. */
  const runTaxonomy = useCallback(
    async (write: () => Promise<unknown>) => {
      setProjectBusy(true);
      setProjectError('');
      try {
        await write();
        const refreshed = await getCategories();
        setCategories(refreshed.categories);
        setFiled(refreshed.parts);
      } catch (caught) {
        setProjectError(errorMessage(caught, 'the taxonomy could not be changed'));
      } finally {
        setProjectBusy(false);
      }
    },
    [],
  );

  /** Re-file a part, as a person. This is the answer a rebuild must not undo. */
  const movePart = useCallback(
    async (partNumber: string) => {
      const target = globalThis.prompt?.(
        `Move ${partNumber} to which category?

${categories.map((c) => c.id).join(', ')}`,
        selectedCategory,
      );
      if (!target) return;
      setProjectError('');
      try {
        await setPartCategory(partNumber, { category: target.trim() });
        const [taxonomy, parts] = await Promise.all([getCategories(), getParts()]);
        setCategories(taxonomy.categories);
        setFiled(taxonomy.parts);
        setCatalog(parts.parts);
      } catch (caught) {
        setProjectError(errorMessage(caught, `${partNumber} could not be moved`));
      }
    },
    [categories, selectedCategory],
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
        relative_dir: '',
        // The user chose this part explicitly; it is not a heuristic's guess.
        is_datasheet: true,
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

      {/* The panes below render on an empty shelf too: the taxonomy is the
          user's to arrange *before* there is anything to file into it. Only
          the filters, the scope switch and the count need documents to mean
          anything, so only those are gated. */}
      {documents.length > 0 ? (
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

          {project ? (
            <div className="library-scope" role="group" aria-label="What to show">
              <button
                type="button"
                aria-pressed={scopeToProject}
                onClick={() => setScopeToProject(true)}
              >
                {`In ${project.name}`}
              </button>
              <button
                type="button"
                aria-pressed={!scopeToProject}
                onClick={() => setScopeToProject(false)}
              >
                All documents
              </button>
              <span className="library-scope-note">
                {scopeToProject
                  ? `${split.inProject.length} here, ${split.elsewhere.length} elsewhere`
                  : 'the whole bookshelf — add anything to your project'}
              </span>
            </div>
          ) : null}

          {projectNote ? (
            <p className="library-note" role="status">
              {projectNote}
            </p>
          ) : null}

          <p className="library-count" role="status">
            {`${shownDocuments} of ${documents.length} documents`}
          </p>
        </>
      ) : (
        <p className="library-empty">
          The library is empty — arrange your categories here, and every document you
          build lands in one.
        </p>
      )}

      {/* Two panes, not a three-level tree: category on the left, its
          parts and supporting documents on the right. Three levels of
          indentation is what made the previous screen sprawl. */}
      <div className="library-panes">
        <CategoryTree
          categories={categories}
          selected={selectedCategory}
          busy={projectBusy}
          onSelect={setSelectedCategory}
          onCreate={(name) => void runTaxonomy(() => createCategory({ name }))}
          onRename={(id, name) => void runTaxonomy(() => renameCategory(id, { name }))}
          onRemove={(id) => void runTaxonomy(() => removeCategory(id))}
        />

        <CategoryContents
          category={categories.find((c) => c.id === selectedCategory) ?? null}
          parts={contents.parts}
          supporting={contents.supporting}
          inProject={inProjectHashes}
          onOpen={openDocument}
          onAddToProject={project ? (hash) => void addToProject(hash) : undefined}
          onEditDocument={(document) => setEditing(document)}
          onMovePart={(partNumber) => void movePart(partNumber)}
          onBuild={(group) => void buildPart(group)}
          projectParts={new Set(projectParts)}
          onRemoveFromProject={
            project
              ? (partNumber) =>
                  void runProjectWrite(() => removeProjectPart(project.name, partNumber))
              : undefined
          }
        />
      </div>

      {/* Applicability and labels are edited one document at a time, in a
          panel, rather than inline on every row — inline is what made a
          shelf of twelve not fit on a screen. */}
      {editing ? (
        <section className="library-editor" aria-label={`Edit ${editing.filename}`}>
          <div className="library-editor-head">
            <h3>{editing.filename}</h3>
            <button type="button" onClick={() => setEditing(null)}>
              Close
            </button>
          </div>
          <PartGroupRow
            group={{
              part_number: editing.part_number || editing.filename,
              built: true,
              documents: [editing],
              labels: editing.labels,
            }}
            knownLabels={knownLabels}
            applicabilityControl={applicabilityControl}
            onPatched={(next) => {
              onPatched(next);
              setEditing(next);
            }}
            defaultOpen
          />
        </section>
      ) : null}
    </main>
  );
}

export default function LibraryRoute() {
  return <LibraryScreen applicabilityControl={getApplicabilityControl()} />;
}
