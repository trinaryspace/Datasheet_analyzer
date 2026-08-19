/**
 * The shelf rail: what is in this project, and what the model can read.
 *
 * A narrow column at the left of the working pane, present on every screen,
 * because the question it answers — "does the corpus actually have that
 * datasheet?" — is one you ask *while chatting*, not one you navigate away to
 * check.
 *
 * The distinction it exists to draw is `processed`. A PDF on the shelf that
 * has never been built is a file, not a corpus: the model cannot see it, and
 * showing it identically to a built one would make the rail actively
 * misleading. Unprocessed rows are dimmed, labelled, and carry the build
 * offer.
 *
 * Collapsed state persists, because a rail you re-collapse every morning is
 * an annoyance rather than a tool.
 */
import { useCallback, useEffect, useState } from 'react';

import { getShelf } from '../api/client';
import type { ShelfDocument } from '../api/types';
import { useWorkingSet } from './workingSet';

const COLLAPSED_KEY = 'dsa.shelfRail.collapsed';

function readCollapsed(): boolean {
  try {
    return globalThis.localStorage?.getItem(COLLAPSED_KEY) === '1';
  } catch {
    return false;
  }
}

export interface ShelfRailProps {
  /** Open a document — the PDF pane handoff. */
  onOpen?: (doc: ShelfDocument) => void;
  /** Build an unprocessed document. Absent hides the offer. */
  onBuild?: (doc: ShelfDocument) => void;
}

export function ShelfRail({ onOpen, onBuild }: ShelfRailProps) {
  const { project } = useWorkingSet();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [documents, setDocuments] = useState<ShelfDocument[]>([]);
  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');

  const load = useCallback(async (name: string) => {
    if (!name) {
      setDocuments([]);
      setStatus('idle');
      return;
    }
    setStatus('loading');
    try {
      const shelf = await getShelf(name);
      setDocuments(shelf.documents);
      setStatus('ready');
    } catch {
      // The rail is context, never the content. Failing to read the shelf
      // must not take a screen down with it.
      setDocuments([]);
      setStatus('error');
    }
  }, []);

  useEffect(() => {
    void load(project);
  }, [project, load]);

  function toggle() {
    setCollapsed((was) => {
      const next = !was;
      try {
        globalThis.localStorage?.setItem(COLLAPSED_KEY, next ? '1' : '0');
      } catch {
        /* a rail that will not remember is still a rail */
      }
      return next;
    });
  }

  if (!project) return null;

  const processed = documents.filter((d) => d.processed).length;

  return (
    <aside
      className="shelf-rail"
      data-collapsed={collapsed}
      aria-label={`Documents in ${project}`}
    >
      <div className="shelf-rail-head">
        <button
          type="button"
          className="shelf-rail-toggle"
          onClick={toggle}
          aria-expanded={!collapsed}
          title={collapsed ? 'Show the project shelf' : 'Hide the project shelf'}
        >
          {collapsed ? '›' : '‹'}
        </button>
        {collapsed ? null : (
          <span className="shelf-rail-title">
            {project}
            <span className="shelf-rail-count">
              {status === 'ready' ? `${processed}/${documents.length} built` : ''}
            </span>
          </span>
        )}
      </div>

      {collapsed ? null : (
        <div className="shelf-rail-body">
          {status === 'loading' ? <p className="shelf-rail-note">Reading the shelf…</p> : null}
          {status === 'error' ? (
            <p className="shelf-rail-note">The shelf could not be read.</p>
          ) : null}
          {status === 'ready' && documents.length === 0 ? (
            <p className="shelf-rail-note">No PDFs in this folder yet.</p>
          ) : null}

          <ul className="shelf-rail-list">
            {documents.map((doc) => (
              <li
                key={doc.content_hash || doc.path}
                className="shelf-rail-item"
                data-processed={doc.processed}
                data-excluded={doc.excluded}
              >
                <button
                  type="button"
                  className="shelf-rail-open"
                  disabled={!doc.processed || !onOpen}
                  onClick={() => onOpen?.(doc)}
                  title={
                    doc.processed
                      ? `${doc.filename} — open`
                      : `${doc.filename} — not built, so the model cannot read it`
                  }
                >
                  <span className="shelf-rail-name">{doc.filename}</span>
                  {doc.relative_dir ? (
                    <span className="shelf-rail-where">{doc.relative_dir}</span>
                  ) : null}
                  {doc.processed ? null : <span className="shelf-rail-unbuilt">not built</span>}
                  {doc.labels.map((label) => (
                    <span key={label} className="shelf-rail-label">
                      {label}
                    </span>
                  ))}
                </button>
                {!doc.processed && onBuild ? (
                  <button
                    type="button"
                    className="shelf-rail-build"
                    onClick={() => onBuild(doc)}
                    aria-label={`Build ${doc.filename}`}
                  >
                    Build
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      )}
    </aside>
  );
}

export default ShelfRail;
