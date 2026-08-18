/**
 * The analyze screen: pick a directory, review what was inferred, watch it
 * build.
 *
 * Three steps in one route rather than three routes, because the sequence is
 * one task and the middle step's edits must survive a back-and-forth without
 * a round trip. The route is discovered by `App.tsx`'s `import.meta.glob`;
 * nothing registers it.
 */
import { useState } from 'react';

import type { ScanOut } from '../../api/types';
import PickStep from './PickStep';
import ProgressStep from './ProgressStep';
import ReviewStep from './ReviewStep';
import './analyze.css';

/** Discovered route metadata (see `App.tsx`). */
export const path = '/analyze';
export const label = 'Analyze';
export const order = 10;

type Step =
  | { name: 'pick'; directory: string }
  | { name: 'review'; scan: ScanOut }
  | { name: 'run'; runId: string; directory: string };

export default function AnalyzeScreen() {
  const [step, setStep] = useState<Step>({ name: 'pick', directory: '' });

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
          initialDirectory={step.directory}
          onScanned={(scan) => setStep({ name: 'review', scan })}
        />
      ) : null}

      {step.name === 'review' ? (
        <ReviewStep
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
