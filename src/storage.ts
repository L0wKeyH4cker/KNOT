import { parseWorkflow } from './model.ts';

export const KNOT_STORAGE = 'knot.current.v1';
export const KNOT_LIBRARY = 'knot.projects.v1';

// Read-only compatibility keys for projects saved before the rename.
const LEGACY_STORAGE = 'teamblocks.current.v1';
const LEGACY_LIBRARY = 'teamblocks.projects.v1';

type ProjectStorage = Pick<Storage, 'getItem' | 'setItem'>;

/** Copy validated legacy projects once, retaining the original data as a backup. */
export function migrateLegacyStorage(storage: ProjectStorage) {
  const migrated = { current: false, projects: false };
  const entries = [
    { source: LEGACY_STORAGE, target: KNOT_STORAGE, kind: 'current' },
    { source: LEGACY_LIBRARY, target: KNOT_LIBRARY, kind: 'projects' },
  ] as const;
  for (const entry of entries) {
    try {
      // Even an empty/invalid existing new value belongs to the current app.
      if (storage.getItem(entry.target) !== null) continue;
      const source = storage.getItem(entry.source);
      if (source === null) continue;
      const value: unknown = JSON.parse(source);
      let validated;
      if (entry.kind === 'projects') {
        if (!Array.isArray(value)) continue;
        // Validate the whole library; never silently discard individual projects.
        validated = value.map(parseWorkflow);
      } else {
        validated = parseWorkflow(value);
      }
      storage.setItem(entry.target, JSON.stringify(validated));
      migrated[entry.kind] = true;
    } catch {
      // Invalid content, denied storage, or quota failure leaves the source intact.
      // A failed write has no marker, allowing a later startup to retry.
    }
  }
  return migrated;
}
