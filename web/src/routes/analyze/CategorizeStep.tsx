/**
 * After the build: file what was just built, one line per part.
 *
 * This is the second confirmation moment, and it exists because a classifier
 * reading the *built corpus* — section titles, body text, spec symbols —
 * guesses far better than one reading page 1. Part number and applicability
 * are settled before the build because the part number decides which
 * directory gets written; the category can wait, and is better for waiting.
 *
 * **Every row is shown, doubtful first.** Hiding the confident ones would
 * save a glance and cost the ability to notice a *confidently wrong* answer —
 * which is exactly the failure that filed a splitter under amplifiers on a
 * single stray keyword. With one line per part, showing forty costs nothing.
 *
 * Nothing here is mandatory. The proposals are already stored as proposals; a
 * user who closes this screen has a categorised shelf they can correct later
 * from the Library. Confirming is what makes an answer stick against the next
 * rebuild.
 */
import { useCallback, useEffect, useState } from 'react';

import { categorizeParts, getCategories, setPartCategory } from '../../api/client';
import type { CategoryOut, PartCategoryOut } from '../../api/types';

export interface CategorizeStepProps {
  /** The parts the finished run produced. */
  parts: string[];
  onDone: () => void;
}

export default function CategorizeStep({ parts, onDone }: CategorizeStepProps) {
  const [rows, setRows] = useState<PartCategoryOut[]>([]);
  const [categories, setCategories] = useState<CategoryOut[]>([]);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [error, setError] = useState('');
  const [saved, setSaved] = useState<Set<string>>(new Set());

  useEffect(() => {
    let live = true;
    if (parts.length === 0) {
      setStatus('ready');
      return;
    }
    void (async () => {
      try {
        const [taxonomy, proposals] = await Promise.all([
          getCategories(),
          categorizeParts({ parts }),
        ]);
        if (!live) return;
        setCategories(taxonomy.categories);
        setRows(proposals.parts);
        setStatus('ready');
      } catch (caught) {
        if (!live) return;
        setError(caught instanceof Error ? caught.message : 'the parts could not be categorised');
        setStatus('error');
      }
    })();
    return () => {
      live = false;
    };
  }, [parts]);

  const choose = useCallback((partNumber: string, category: string) => {
    setRows((current) =>
      current.map((row) =>
        row.part_number === partNumber ? { ...row, category, confirmed: false } : row,
      ),
    );
  }, []);

  const confirm = useCallback(
    async (row: PartCategoryOut) => {
      try {
        await setPartCategory(row.part_number, { category: row.category });
        setSaved((current) => new Set(current).add(row.part_number));
        setRows((current) =>
          current.map((r) => (r.part_number === row.part_number ? { ...r, confirmed: true } : r)),
        );
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : 'that part could not be filed');
      }
    },
    [],
  );

  const confirmAll = useCallback(async () => {
    // Accepting the whole batch is the common case on a clean run, and doing
    // it one row at a time is the thing that makes a 40-PDF batch tedious.
    for (const row of rows) {
      if (!row.confirmed) await confirm(row);
    }
  }, [rows, confirm]);

  if (parts.length === 0) return null;

  const unconfirmed = rows.filter((row) => !row.confirmed).length;

  return (
    <section className="categorize" aria-labelledby="categorize-heading">
      <h2 id="categorize-heading">File what was built</h2>
      <p className="analyze-hint">
        A category is how the Library is navigated. Each guess below reads the built
        corpus; correct any that are wrong, then confirm — a confirmed answer survives
        every future rebuild.
      </p>

      {status === 'loading' ? (
        <p role="status" className="analyze-loading">
          Reading {parts.length} corpus{parts.length === 1 ? '' : 'es'}…
        </p>
      ) : null}

      {error ? (
        <p role="alert" className="analyze-error">
          {error}
        </p>
      ) : null}

      {status === 'ready' && rows.length > 0 ? (
        <>
          <p className="analyze-summary" data-testid="categorize-summary">
            {`${rows.length - unconfirmed} of ${rows.length} confirmed`}
          </p>

          <ul className="categorize-rows">
            {rows.map((row) => (
              <li
                key={row.part_number}
                className="categorize-row"
                data-confident={row.confident}
                data-confirmed={row.confirmed}
              >
                <span className="categorize-part">{row.part_number}</span>

                <select
                  aria-label={`Category for ${row.part_number}`}
                  value={row.category}
                  onChange={(event) => choose(row.part_number, event.target.value)}
                >
                  {categories.map((category) => (
                    <option key={category.id} value={category.id}>
                      {category.name}
                    </option>
                  ))}
                </select>

                {/* The reason, not a score. A guess that cannot say why it
                    guessed is not correctable by a human. */}
                <span className="categorize-why" title={row.evidence}>
                  {row.evidence}
                </span>

                {row.confirmed || saved.has(row.part_number) ? (
                  <span className="categorize-ok">filed</span>
                ) : (
                  <button
                    type="button"
                    onClick={() => void confirm(row)}
                    aria-label={`Confirm ${row.part_number} as ${row.category}`}
                  >
                    Confirm
                  </button>
                )}
              </li>
            ))}
          </ul>
        </>
      ) : null}

      <div className="analyze-actions">
        <button type="button" onClick={() => void confirmAll()} disabled={unconfirmed === 0}>
          {`Confirm all (${unconfirmed})`}
        </button>
        <button type="button" onClick={onDone}>
          Done
        </button>
      </div>
    </section>
  );
}
