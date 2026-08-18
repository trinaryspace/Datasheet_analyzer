/**
 * The PDF screen, discovered by `App.tsx`'s route glob.
 *
 * Its whole job is to turn the URL into a `PdfTarget` and hand it to the pane.
 * Cross-pane state travels in the query string precisely so this file can stay
 * this short and so the pane never imports the chat pane.
 */
import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import PdfPane from './PdfPane';
import { readPdfTarget } from './target';

export const path = '/pdf';
export const label = 'PDF';
export const order = 40;

export default function PdfRoute() {
  const [params] = useSearchParams();
  const search = params.toString();
  const target = useMemo(() => readPdfTarget(search), [search]);
  return <PdfPane target={target} />;
}
