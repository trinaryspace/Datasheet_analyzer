/**
 * The analyze screen: pick a directory, review what was inferred, watch it
 * build.
 *
 * Three steps in one route rather than three routes, because the sequence is
 * one task and the middle step's edits must survive a back-and-forth without
 * a round trip. The route is discovered by `App.tsx`'s `import.meta.glob`;
 * nothing registers it.
 */
import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { getProjects, patchProject } from '../../api/client';
import type { ScanOut } from '../../api/types';
import { useWorkingSet } from '../../shell/workingSet';
import { nothingToBuild } from './proposals';
import PickStep from './PickStep';
import ProgressStep from './ProgressStep';
import ReviewStep from './ReviewStep';
import UpToDateStep from './UpToDateStep';
import './analyze.css';

/** Discovered route metadata (see `App.tsx`). */
export const path = '/analyze';
export const label = 'Analyze';
export const order = 10;

type Step =
  | { name: 'pick'; directory: string }
  | { name: 'review'; scan: ScanOut }
  // A rescan where every document is current: there is no review to do, so
  // the middle step is skipped rather than shown with nothing in it.
  | { name: 'uptodate'; scan: ScanOut }
  | { name: 'run'; runId: string; directory: string };

function afterScan(scan: ScanOut): Step {
  return nothingToBuild(scan) ? { name: 'uptodate', scan } : { name: 'review', scan };
}

/** A run started elsewhere (the Library's "Build this part") lands here. */
export const ANALYZE_PARAM_RUN = 'run';

export default function AnalyzeScreen() {
  const [searchParams] = useSearchParams();
  const handedOffRun = searchParams.get(ANALYZE_PARAM_RUN) ?? '';
  const { project } = useWorkingSet();

  const [step, setStep] = useState<Step>(() =>
    handedOffRun
      ? { name: 'run', runId: handedOffRun, directory: '' }
      : { name: 'pick', directory: '' },
  );

  // A second hand-off while this screen is already open — the user built one
  // part, went back to the Library and built another — must move the view.
  useEffect(() => {
    if (handedOffRun) setStep({ name: 'run', runId: handedOffRun, directory: '' });
  }, [handedOffRun]);

  // The active project's recorded directory, so re-opening a shelf is a click
  // rather than a retyped path. Read from the server, not from browser
  // storage: the association belongs to the project, and outlives this browser.
  const [projectDirectory, setProjectDirectory] = useState('');
  useEffect(() => {
    let live = true;
    if (!project) {
      setProjectDirectory('');
      return;
    }
    void (async () => {
      try {
        const { projects } = await getProjects();
        if (!live) return;
        setProjectDirectory(projects.find((p) => p.name === project)?.directory ?? '');
      } catch {
        // A prefill is a convenience; failing to read it must not block the
        // screen, and the user can always type the path.
        if (live) setProjectDirectory('');
      }
    })();
    return () => {
      live = false;
    };
  }, [project]);

  return (
    <div className="analyze-screen">
      <h1>Analyze</h1>
      <ol className="analyze-breadcrumb" aria-label="Progress">
        <li aria-current={step.name === 'pick' ? 'step' : undefined}>Pick</li>
        <li aria-current={step.name === 'review' ? 'step' : undefined}>Review</li>
        <li aria-current={step.name === 'run' ? 'step' : undefined}>Build</li>
      </ol>

      {step.name === 'pick' ? (
        <PickStep
          // `PickStep` seeds its input from `initialDirectory` on mount, and
          // the project's recorded directory arrives from a later fetch — so
          // the key includes it, or the prefill would always lose the race.
          key={`${project}:${projectDirectory}`}
          initialDirectory={step.directory || projectDirectory}
          onScanned={(scan) => {
            // Scanning a directory while a project is active is what tells
            // the project where it lives. Recorded server-side, so reopening
            // the shelf survives this browser — and fire-and-forget, because
            // a failed bookkeeping write must never block the scan result.
            if (project && scan.directory && scan.directory !== projectDirectory) {
              void patchProject(project, { directory: scan.directory })
                .then(() => setProjectDirectory(scan.directory))
                .catch(() => undefined);
            }
            setStep(afterScan(scan));
          }}
        />
      ) : null}

      {step.name === 'review' ? (
        <ReviewStep
          scan={step.scan}
          onStarted={(runId, directory) => setStep({ name: 'run', runId, directory })}
          onBack={() => setStep({ name: 'pick', directory: step.scan.directory })}
        />
      ) : null}

      {step.name === 'uptodate' ? (
        <UpToDateStep
          scan={step.scan}
          onStarted={(runId, directory) => setStep({ name: 'run', runId, directory })}
          onBack={() => setStep({ name: 'pick', directory: step.scan.directory })}
        />
      ) : null}

      {step.name === 'run' ? (
        <ProgressStep
          runId={step.runId}
          directory={step.directory}
          onRestart={() => setStep({ name: 'pick', directory: step.directory })}
        />
      ) : null}
    </div>
  );
}
