/**
 * Hand a string to the browser as a file.
 *
 * The export endpoints return text, not a redirect, so the download is built
 * here from an object URL and a synthetic anchor click. It is a seam as well
 * as a helper: the sessions screen takes the function as a prop, so a test can
 * assert what would have been downloaded without jsdom needing to implement
 * one.
 */
export type DownloadText = (filename: string, text: string, mimeType?: string) => void;

export const downloadText: DownloadText = (filename, text, mimeType = 'text/plain') => {
  const blob = new Blob([text], { type: `${mimeType};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = 'noopener';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
};

export default downloadText;
