/**
 * The application: routes discovered from the filesystem, never registered.
 *
 * `import.meta.glob('./routes/(star)/route.tsx', { eager: true })` picks up
 * every screen, so a ticket adding one adds a directory and edits nothing
 * shared. Written once by ticket 00 and **not modified by any later
 * ticket** — a route registry with five concurrent authors is a merge
 * conflict, and the glob costs nothing at runtime (Vite resolves it at build
 * time).
 *
 * A route module (`src/routes/<name>/route.tsx`) exports:
 *
 * | export | required | meaning |
 * |---|---|---|
 * | `default` | yes | the screen component |
 * | `path` | no | URL path; defaults to `/<name>` |
 * | `label` | no | nav label; defaults to `<name>` |
 * | `order` | no | nav sort key; defaults to 100 |
 *
 * The shell is discovered the same way: if `src/shell/Shell.tsx` exists
 * (ticket 16) it wraps the routes and receives the discovered route list for
 * its navigation. Until it does, a plain frame renders instead, so the app
 * runs at every point in the build-out.
 *
 * **Cross-pane state travels in the URL**, not through imports: the chat
 * pane and the PDF pane must stay independently testable, so a citation
 * click writes `?doc=<content_hash>&page=<n>&needle=<text>` (see
 * `PDF_PARAM_*` in `api/types.ts`) and the PDF pane reads it. Neither pane
 * imports the other.
 */
import type { ComponentType, ReactNode } from 'react';
import { Link, Route, Routes, useLocation } from 'react-router-dom';

/** What a `src/routes/<name>/route.tsx` module may export. */
export interface RouteModule {
  default: ComponentType;
  path?: string;
  label?: string;
  order?: number;
}

/** One discovered screen, as the shell's navigation sees it. */
export interface RouteDescriptor {
  id: string;
  path: string;
  label: string;
  order: number;
  Component: ComponentType;
}

/** Props `src/shell/Shell.tsx` receives when it exists (ticket 16). */
export interface ShellProps {
  routes: RouteDescriptor[];
  children?: ReactNode;
}

interface ShellModule {
  default: ComponentType<ShellProps>;
}

const routeModules = import.meta.glob<RouteModule>('./routes/*/route.tsx', { eager: true });
const shellModules = import.meta.glob<ShellModule>('./shell/Shell.tsx', { eager: true });

function directoryName(file: string): string {
  const parts = file.split('/');
  return parts[parts.length - 2] ?? 'route';
}

/** Every discovered screen, sorted by `order` then path — stable, not directory order. */
export const routes: RouteDescriptor[] = Object.entries(routeModules)
  .map(([file, module]) => {
    const id = directoryName(file);
    return {
      id,
      path: module.path ?? `/${id}`,
      label: module.label ?? id,
      order: module.order ?? 100,
      Component: module.default,
    };
  })
  .sort((a, b) => a.order - b.order || a.path.localeCompare(b.path));

const shellEntry = Object.values(shellModules)[0];
const Shell: ComponentType<ShellProps> | undefined = shellEntry?.default;

function FallbackShell({ routes: discovered, children }: ShellProps) {
  const { pathname } = useLocation();
  return (
    <div className="app-fallback-shell">
      <nav aria-label="Screens">
        <ul>
          {discovered.map((route) => (
            <li key={route.id}>
              <Link to={route.path} aria-current={pathname === route.path ? 'page' : undefined}>
                {route.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      <main>{children}</main>
    </div>
  );
}

function NoRoutes() {
  return (
    <main>
      <h1>Datasheet Workbench</h1>
      <p>No screens are installed yet. A screen is a directory under <code>src/routes/</code> holding a <code>route.tsx</code>.</p>
    </main>
  );
}

export function App() {
  const Frame = Shell ?? FallbackShell;
  if (routes.length === 0) {
    return (
      <Frame routes={routes}>
        <NoRoutes />
      </Frame>
    );
  }
  return (
    <Frame routes={routes}>
      <Routes>
        {routes.map((route) => (
          <Route key={route.id} path={route.path} element={<route.Component />} />
        ))}
      </Routes>
    </Frame>
  );
}

export default App;
