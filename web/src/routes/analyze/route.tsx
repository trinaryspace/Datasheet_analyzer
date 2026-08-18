/**
 * Analyze: open a project folder, choose what to build, watch it build.
 *
 * The flow the screen is shaped around is "open a folder", not "type a path".
 * A folder is a Batch; opening one seeds a Project named after it, and that
 * project becomes the app-wide working set (`shell/workingSet`), so Library
 * and Chat inherit the same context.
 *
 * Five states, and which one you land in is the whole design:
 *
 * | state | when |
 * |---|---|
 * | `welcome` | nothing open — recent folders, and a way to open one |
 * | `review` | the scan found work to do |
 * | `uptodate` | the scan found nothing to do; say so and stop |
 * | `run` | a build is in flight, here or handed over from the Library |
 *
 * Reopening a project **scans in the background and does not interrupt**. If
 * nothing is new you land in a working app and are told nothing; if something
 * is new you get a dismissible banner. A modal that announces one new PDF is
 * charming once and irritating thereafter.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import {
  getProjects,
  patchProject,
  scanDirectory,
  setProjectExclusions,
} from '../../api/client';
import type { ProjectOut, ScanOut } from '../../api/types';
import { useWorkingSet } from '../../shell/workingSet';
import ProgressStep from './ProgressStep';
import ReviewStep from './ReviewStep';
import UpToDateStep from './UpToDateStep';
import WelcomeStep from './WelcomeStep';
import { nothingToBuild } from './proposals';
import './analyze.css';

/** Discovered route metadata (see `App.tsx`). */
export const path = '/analyze';
export const label = 'Analyze';
export const order = 10;

/** A run started elsewhere (the Library's "Build this part") lands here. */
export const ANALYZE_PARAM_RUN = 'run';

type Step =
  | { name: 'welcome' }
  | { name: 'review'; scan: ScanOut }
  | { name: 'uptodate'; scan: ScanOut }
  | { name: 'run'; runId: string; directory: string };

function afterScan(scan: ScanOut): Step {
  return nothingToBuild(scan) ? { name: 'uptodate', scan } : { name: 'review', scan };
}

export default function AnalyzeScreen() {
  const [searchParams] = useSearchParams();
  const handedOffRun = searchParams.get(ANALYZE_PARAM_RUN) ?? '';
  const { project, setProject } = useWorkingSet();

  const [step, setStep] = useState<Step>(() =>
    handedOffRun ? { name: 'run', runId: handedOffRun, directory: '' } : { name: 'welcome' },
  );
  const [open, setOpen] = useState<ProjectOut | null>(null);
  const [banner, setBanner] = useState('');
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState('');

  // A second hand-off while this screen is already open — built one part, went
  // back to the Library, built another — must move the view.
  useEffect(() => {
    if (handedOffRun) setStep({ name: 'run', runId: handedOffRun, directory: '' });
  }, [handedOffRun]);

  // Resolve the working set to its project record, so a project chosen on the
  // Library screen is the one this screen is about.
  useEffect(() => {
    let live = true;
    if (!project) {
      setOpen(null);
      return;
    }
    // Already holding this project — opening a folder hands the record over
    // directly. Re-fetching would be redundant, and worse: a listing that has
    // not caught up yet would blank the project the user just opened.
    if (open?.name === project) return;
    void (async () => {
      try {
        const { projects } = await getProjects();
        if (live) setOpen(projects.find((p) => p.name === project) ?? null);
      } catch {
        if (live) setOpen(null);
      }
    })();
    return () => {
      live = false;
    };
  }, [project, open]);

  const scan = useCallback(
    async (directory: string, { notify }: { notify: boolean }) => {
      if (!directory) return;
      setScanning(true);
      setScanError('');
      try {
        const result = await scanDirectory({ directory });
        // The banner is for *returning* to a project and finding something
        // new. Opening a folder puts the review on screen already, so an
        // announcement there would only restate what the user is looking at.
        if (notify && !nothingToBuild(result)) {
          const todo = result.proposals.filter((p) => p.build_state !== 'current').length;
          setBanner(
            `${todo} document${todo === 1 ? '' : 's'} in this folder ${
              todo === 1 ? 'is' : 'are'
            } not built yet.`,
          );
        }
        setStep(afterScan(result));
      } catch (caught) {
        setScanError(
          caught instanceof Error ? caught.message : 'that folder could not be scanned',
        );
      } finally {
        setScanning(false);
      }
    },
    [],
  );

  // Auto-scan a project when it is opened or switched to — once per directory,
  // so navigating back to this screen does not re-walk the tree.
  const scannedRef = useRef('');
  // True for the scan that immediately follows an explicit "open this folder",
  // so that one does not also announce what the review is about to show.
  const justOpenedRef = useRef(false);
  useEffect(() => {
    const directory = open?.directory ?? '';
    if (!directory || handedOffRun) return;
    if (scannedRef.current === directory) return;
    scannedRef.current = directory;
    const notify = !justOpenedRef.current;
    justOpenedRef.current = false;
    void scan(directory, { notify });
  }, [open, handedOffRun, scan]);

  const onOpened = useCallback(
    (opened: ProjectOut) => {
      setProject(opened.name);
      setOpen(opened);
      setBanner('');
      scannedRef.current = '';
      justOpenedRef.current = true;
    },
    [setProject],
  );

  const rememberExclusions = useCallback(
    (hashes: string[]) => {
      if (!open) return;
      // Fire and forget: failing to remember a rejection must not cost the
      // user the build they just started.
      void setProjectExclusions(open.name, { excluded: hashes })
        .then((next) => setOpen(next))
        .catch(() => undefined);
    },
    [open],
  );

  function closeProject() {
    setProject('');
    setOpen(null);
    setBanner('');
    scannedRef.current = '';
    setStep({ name: 'welcome' });
  }

  const directory = open?.directory ?? '';

  return (
    <div className="analyze-screen">
      <header className="analyze-head">
        <h1>{open ? open.name : 'Analyze'}</h1>
        {open ? (
          <>
            <span className="analyze-open-path" title={directory}>
              {directory}
            </span>
            <button type="button" onClick={() => void scan(directory, { notify: false })}>
              Rescan
            </button>
            <button type="button" onClick={closeProject}>
              Close project
            </button>
          </>
        ) : null}
      </header>

      {scanning ? (
        <p role="status" className="analyze-loading">
          Looking through {directory || 'the folder'}…
        </p>
      ) : null}

      {scanError ? (
        <p role="alert" className="analyze-error">
          {scanError}
        </p>
      ) : null}

      {banner ? (
        <p className="analyze-banner" role="status">
          {banner}
          <button type="button" onClick={() => setBanner('')} aria-label="Dismiss">
            Dismiss
          </button>
        </p>
      ) : null}

      {step.name === 'welcome' ? <WelcomeStep onOpened={onOpened} /> : null}

      {step.name === 'review' ? (
        <ReviewStep
          scan={step.scan}
          excluded={open?.excluded ?? []}
          onExclude={rememberExclusions}
          onStarted={(runId, dir) => setStep({ name: 'run', runId, directory: dir })}
          onBack={closeProject}
        />
      ) : null}

      {step.name === 'uptodate' ? (
        <UpToDateStep
          scan={step.scan}
          onStarted={(runId, dir) => setStep({ name: 'run', runId, directory: dir })}
          onBack={closeProject}
        />
      ) : null}

      {step.name === 'run' ? (
        <ProgressStep
          runId={step.runId}
          directory={step.directory || directory}
          onRestart={() => void scan(directory, { notify: false })}
        />
      ) : null}
    </div>
  );
}
