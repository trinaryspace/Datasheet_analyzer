/**
 * The category tree: the left half of the bookshelf.
 *
 * A flat Library is a fine record and a poor place to *find* anything. Filing
 * by function — amplifiers, mixers, passives — is what makes "pull the part I
 * used two years ago into this project" a scan rather than a search.
 *
 * Deliberately one level, not a nested tree. Category → parts → documents is
 * three levels of indentation, and three levels is what made the previous
 * screen sprawl; the parts live in the right pane instead, where they have
 * room. `uncategorized` is always last and always shown, because a part with
 * nowhere to go must still be reachable.
 */
import { useState } from 'react';

import type { CategoryOut } from '../../api/types';
import { UNCATEGORIZED } from '../../api/types';

export interface CategoryTreeProps {
  categories: CategoryOut[];
  selected: string;
  onSelect: (categoryId: string) => void;
  onCreate?: (name: string) => void;
  onRename?: (categoryId: string, name: string) => void;
  onRemove?: (categoryId: string) => void;
  busy?: boolean;
}

export function CategoryTree({
  categories,
  selected,
  onSelect,
  onCreate,
  onRename,
  onRemove,
  busy = false,
}: CategoryTreeProps) {
  const [adding, setAdding] = useState('');

  function submit() {
    const name = adding.trim();
    if (!name) return;
    onCreate?.(name);
    setAdding('');
  }

  return (
    <nav className="category-tree" aria-label="Categories">
      <ul className="category-tree-list">
        {categories.map((category) => {
          const active = category.id === selected;
          return (
            <li key={category.id} className="category-tree-item" data-active={active}>
              <button
                type="button"
                className="category-tree-button"
                aria-current={active ? 'true' : undefined}
                onClick={() => onSelect(category.id)}
              >
                <span className="category-tree-name">{category.name}</span>
                <span className="category-tree-count">{category.count}</span>
              </button>
              {/* Renaming keeps the id, so every part filed here stays filed.
                  Removing is offered only for empty categories that are not
                  `uncategorized` — deleting a full one would silently
                  reshelve parts the user is not looking at. */}
              {onRename && category.id !== UNCATEGORIZED ? (
                <button
                  type="button"
                  className="category-tree-edit"
                  disabled={busy}
                  aria-label={`Rename ${category.name}`}
                  onClick={() => {
                    const next = globalThis.prompt?.(`Rename ${category.name} to:`, category.name);
                    if (next && next.trim()) onRename(category.id, next.trim());
                  }}
                >
                  ✎
                </button>
              ) : null}
              {onRemove && category.id !== UNCATEGORIZED && category.count === 0 ? (
                <button
                  type="button"
                  className="category-tree-edit"
                  disabled={busy}
                  aria-label={`Remove ${category.name}`}
                  onClick={() => onRemove(category.id)}
                >
                  ×
                </button>
              ) : null}
            </li>
          );
        })}
      </ul>

      {onCreate ? (
        <div className="category-tree-add">
          <input
            type="text"
            value={adding}
            placeholder="new category…"
            aria-label="New category name"
            disabled={busy}
            onChange={(event) => setAdding(event.target.value)}
            onKeyDown={(event) => {
              if (event.key !== 'Enter') return;
              event.preventDefault();
              submit();
            }}
          />
          <button type="button" onClick={submit} disabled={busy || !adding.trim()}>
            Add category
          </button>
        </div>
      ) : null}
    </nav>
  );
}

export default CategoryTree;
