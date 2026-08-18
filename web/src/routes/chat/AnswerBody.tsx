/**
 * The assistant's answer: markdown, with each citation clickable where it is
 * written rather than in a pile at the end.
 *
 * Two rules shape this file.
 *
 * **A citation chip is matched, never parsed.** `app/chat.py` collects
 * citations structurally from the tool results, precisely so a citation the
 * model invented in prose cannot reach the reader as if a tool had returned
 * it. This component keeps that guarantee: it finds `[§4.1, p.4]`-shaped
 * markers in the text and looks each one up in the citations the stream
 * already delivered. A marker that matches becomes a button; a marker that
 * matches nothing stays literal text. Prose can therefore never manufacture a
 * clickable citation — the worst a fabricated marker can do is look like
 * plain characters.
 *
 * **Markdown is rendered, not shown.** The model answers with bold values and
 * comparison tables; printed as raw text those read as asterisks and pipes.
 * `react-markdown` + `remark-gfm` (bundled by Vite — nothing is fetched at
 * runtime) render them, and the component overrides below reach into the text
 * nodes of paragraphs, list items, table cells and headings to swap markers
 * for chips. Overriding the *containers* rather than the text node itself is
 * what lets a citation inside a table cell work.
 */
import type { ReactNode } from 'react';
import { Children, isValidElement } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { CitationLink } from './CitationLink';
import type { CitedItem } from './transcript';

/**
 * `[§4.1, p.4]`, `(§4.1, p.4)` or a bare `§4.1, p.4`.
 *
 * The bracket is optional because the model does not reliably add it, and the
 * page part is optional because a section citation of an unpinned page is
 * honestly `p.?`. Kept deliberately loose on the *shape* and strict on the
 * *match*: anything this finds still has to correspond to a real citation.
 */
const MARKER = /[[(]?\s*(§[^\][()\n]{1,60}?,\s*pp?\.[0-9?][0-9-]*)\s*[\])]?/g;

/** Compare citation labels ignoring the noise that varies between renderings. */
function normalizeLabel(label: string): string {
  return label.replace(/\s+/g, ' ').replace(/–|—/g, '-').trim().toLowerCase();
}

/**
 * Does the prose already cite this item in place?
 *
 * Shares `MARKER` and `normalizeLabel` with the renderer on purpose: if the
 * two disagreed, a citation could be both drawn inline and repeated in the
 * "Also read" row, or be dropped from both.
 */
export function citedInText(text: string, item: CitedItem): boolean {
  const wanted = normalizeLabel(item.citation.label);
  MARKER.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = MARKER.exec(text)) !== null) {
    if (normalizeLabel(match[1]) === wanted) return true;
  }
  return false;
}

export interface AnswerBodyProps {
  text: string;
  citations: CitedItem[];
  onCitation: (item: CitedItem) => void;
}

/**
 * Split one string on citation markers, returning text and chips.
 *
 * Returns the original string unchanged when it holds no marker, so the
 * overwhelmingly common case allocates nothing.
 */
function splitOnMarkers(
  value: string,
  byLabel: Map<string, CitedItem>,
  onCitation: (item: CitedItem) => void,
  keyPrefix: string,
): ReactNode {
  MARKER.lastIndex = 0;
  if (!MARKER.test(value)) return value;
  MARKER.lastIndex = 0;

  const out: ReactNode[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;
  let n = 0;
  while ((match = MARKER.exec(value)) !== null) {
    const item = byLabel.get(normalizeLabel(match[1]));
    if (!item) continue; // unmatched marker: leave it in the prose, untouched
    if (match.index > cursor) out.push(value.slice(cursor, match.index));
    n += 1;
    out.push(
      <CitationLink key={`${keyPrefix}-cite-${n}`} item={item} onOpen={onCitation} />,
    );
    cursor = match.index + match[0].length;
  }
  if (cursor === 0) return value;
  if (cursor < value.length) out.push(value.slice(cursor));
  return out;
}

/** Apply `splitOnMarkers` to every string among a node's children. */
function withChips(
  children: ReactNode,
  byLabel: Map<string, CitedItem>,
  onCitation: (item: CitedItem) => void,
  keyPrefix: string,
): ReactNode {
  return Children.map(children, (child, index) => {
    if (typeof child === 'string') {
      return splitOnMarkers(child, byLabel, onCitation, `${keyPrefix}-${index}`);
    }
    // Bold, italic and code wrap their own text — recurse so `**150 °C
    // [§4.1, p.4]**` still yields a chip.
    if (isValidElement(child)) {
      const element = child as React.ReactElement<{ children?: ReactNode }>;
      const inner = element.props?.children;
      if (inner !== undefined && typeof element.type === 'string') {
        return {
          ...element,
          props: {
            ...element.props,
            children: withChips(inner, byLabel, onCitation, `${keyPrefix}-${index}`),
          },
        };
      }
    }
    return child;
  });
}

export function AnswerBody({ text, citations, onCitation }: AnswerBodyProps) {
  const byLabel = new Map<string, CitedItem>();
  for (const item of citations) {
    const key = normalizeLabel(item.citation.label);
    if (!byLabel.has(key)) byLabel.set(key, item);
  }

  const wrap =
    (tag: 'p' | 'li' | 'td' | 'th' | 'h1' | 'h2' | 'h3' | 'h4' | 'strong' | 'em') =>
    ({ children, ...rest }: { children?: ReactNode }) => {
      const Tag = tag;
      return <Tag {...rest}>{withChips(children, byLabel, onCitation, tag)}</Tag>;
    };

  return (
    <div className="chat-answer-body" data-testid="chat-answer-body">
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: wrap('p'),
          li: wrap('li'),
          td: wrap('td'),
          th: wrap('th'),
          h1: wrap('h3'),
          h2: wrap('h3'),
          h3: wrap('h3'),
          h4: wrap('h4'),
          // The answer is a fragment of a page, not a document: a table needs
          // its own scroll container so a wide comparison cannot push the
          // chat column sideways.
          table: ({ children, ...rest }) => (
            <div className="chat-table-scroll">
              <table {...rest}>{children}</table>
            </div>
          ),
          // The corpus is local and the model has no URLs worth following;
          // rendering a link as text keeps a hallucinated href unclickable.
          a: ({ children }) => <>{children}</>,
        }}
      >
        {text}
      </Markdown>
    </div>
  );
}

export default AnswerBody;
