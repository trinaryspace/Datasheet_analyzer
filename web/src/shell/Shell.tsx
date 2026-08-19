/**
 * The frame every screen renders inside.
 *
 * `App.tsx` discovers this file by glob and hands it the discovered route
 * list; nothing registers anything. The shell's job is the two-pane split,
 * the navigation across it, and the theme — and nothing else. It imports no
 * screen: the right pane is filled by whichever discovered route calls itself
 * `pdf` (ticket 19), found in the `routes` prop, so the shell and the PDF pane
 * are written concurrently without either importing the other.
 *
 * Cross-pane state travels in the URL exactly as `App.tsx` specifies. A
 * citation click writes `?doc=…&page=…&needle=…`; the shell watches only for
 * the presence of `doc`, which is what turns the right pane from its empty
 * state into the page.
 */
import { useCallback } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router-dom';

import type { RouteDescriptor, ShellProps } from '../App';
import { PDF_PARAM_DOC } from '../api/types';
import { ShelfRail } from './ShelfRail';
import { SplitPane } from './SplitPane';
import { ThemeToggle } from './ThemeToggle';
import { EmptyState } from './primitives';

import '../styles/tokens.css';
import '../styles/shell.css';

/**
 * The discovered route that lives in the right pane instead of the nav.
 *
 * Ticket 19 owns `src/routes/pdf/`; naming the directory is the whole
 * contract between it and the shell.
 */
export const RIGHT_PANE_ROUTE_ID = 'pdf';

/** The right pane before any citation has been clicked. */
export function PdfPaneEmptyState() {
  return (
    <EmptyState
      title="No page open yet"
      description={
        <>
          Click a citation in an answer and the source PDF opens here, at the cited page, with
          the quoted block highlighted. Nothing is fetched until you do.
        </>
      }
    />
  );
}

function Navigation({ routes }: { routes: RouteDescriptor[] }) {
  const { pathname } = useLocation();
  if (routes.length === 0) return null;
  return (
    <nav className="shell__nav" aria-label="Screens">
      <ul>
        {routes.map((route) => (
          <li key={route.id}>
            <Link to={route.path} aria-current={pathname === route.path ? 'page' : undefined}>
              {route.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function Shell({ routes, children }: ShellProps) {
  const [searchParams, setSearchParams] = useSearchParams();

  /**
   * Open a shelf document in the PDF pane.
   *
   * Writes the same `?doc=&part=&page=` a citation click writes, so the rail
   * reuses the pane handoff rather than inventing a second one. No needle:
   * opening a document is not a claim about where on the page anything is.
   */
  const openDocument = useCallback(
    (doc: { content_hash: string; part_number: string }) => {
      const next = new URLSearchParams(searchParams);
      next.set('doc', doc.content_hash);
      if (doc.part_number) next.set('part', doc.part_number);
      next.set('page', '1');
      next.delete('needle');
      setSearchParams(next, { replace: false });
    },
    [searchParams, setSearchParams],
  );

  const [params] = useSearchParams();
  const pdfRoute = routes.find((route) => route.id === RIGHT_PANE_ROUTE_ID);
  const navRoutes = routes.filter((route) => route.id !== RIGHT_PANE_ROUTE_ID);
  const target = params.get(PDF_PARAM_DOC);

  let right;
  if (!target) {
    right = <PdfPaneEmptyState />;
  } else if (pdfRoute) {
    const Pane = pdfRoute.Component;
    right = <Pane />;
  } else {
    right = (
      <EmptyState
        title="The PDF pane is not installed"
        description="A citation was opened, but no screen is registered at src/routes/pdf/."
      />
    );
  }

  return (
    <div className="shell">
      <header className="shell__bar">
        <p className="shell__brand">Datasheet Workbench</p>
        <Navigation routes={navRoutes} />
        <span className="shell__spacer" />
        <ThemeToggle />
      </header>
      <div className="shell__body">
        <SplitPane
          left={
            // The rail sits inside the left pane rather than beside the split,
            // so resizing the PDF pane never squeezes it and it stays put
            // while you move between screens.
            <div className="shell__work">
              <ShelfRail onOpen={openDocument} />
              <main id="main">{children}</main>
            </div>
          }
          right={right}
          leftLabel="Workbench"
          rightLabel="Source page"
        />
      </div>
    </div>
  );
}

export default Shell;
