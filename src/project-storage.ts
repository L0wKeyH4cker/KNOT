import { assertSafeWorkflow, parseWorkflow } from './model.ts';
import type { Workflow } from './model.ts';
import { KNOT_LIBRARY, KNOT_STORAGE } from './storage.ts';

export const PROJECT_QUERY = 'project';
export const PROJECT_DRAFT_PREFIX = 'knot.project.v1.';
export const PROJECT_DELETED_PREFIX = 'knot.deleted-project.v1.';
export const projectBillingKey = (id: string) => 'knot.billing.v1.' + encodeURIComponent(id);
type ReadStorage = Pick<Storage, 'getItem'>;
type ProjectStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

export const projectDraftKey = (id: string) => PROJECT_DRAFT_PREFIX + encodeURIComponent(id);
const deletedKey = (id: string) => PROJECT_DELETED_PREFIX + encodeURIComponent(id);

export function isProjectDeleted(storage: ReadStorage, id: string) {
  return storage.getItem(deletedKey(id)) !== null;
}

function parseStored(raw: string | null): Workflow | null {
  try {
    return raw ? parseWorkflow(JSON.parse(raw)) : null;
  } catch {
    return null;
  }
}

function snapshots(storage: ReadStorage): Workflow[] {
  const value: unknown = JSON.parse(storage.getItem(KNOT_LIBRARY) || '[]');
  if (!Array.isArray(value)) throw new Error('Invalid project library');
  return value.map(parseWorkflow);
}

function draft(storage: ReadStorage, id: string) {
  const value = parseStored(storage.getItem(projectDraftKey(id)));
  return value?.project.id === id ? value : null;
}

export function readProjectLibrary(storage: ReadStorage) {
  return snapshots(storage)
    .filter((project) => !isProjectDeleted(storage, project.project.id))
    .map((project) => draft(storage, project.project.id) || project);
}

export function findProject(storage: ReadStorage, id: string): Workflow | null {
  if (!id || isProjectDeleted(storage, id)) return null;
  const latest = draft(storage, id);
  if (latest) return latest;
  try {
    const saved = snapshots(storage).find((project) => project.project.id === id);
    if (saved) return saved;
  } catch {
    // A damaged library must not hide a valid pre-upgrade current project.
    // Mutating library operations still reject it instead of replacing its data.
  }
  const current = parseStored(storage.getItem(KNOT_STORAGE));
  return current?.project.id === id ? current : null;
}

export function writeCurrentProject(
  storage: ProjectStorage,
  workflow: Workflow,
  updateDefaultCurrent: boolean,
) {
  assertSafeWorkflow(workflow);
  if (isProjectDeleted(storage, workflow.project.id)) throw new Error('This project was deleted');
  const value = JSON.stringify(workflow);
  storage.setItem(projectDraftKey(workflow.project.id), value);
  if (updateDefaultCurrent) storage.setItem(KNOT_STORAGE, value);
}

export function saveLibraryProject(storage: ProjectStorage, workflow: Workflow) {
  const saved = snapshots(storage).filter(
    (project) =>
      project.project.id !== workflow.project.id && !isProjectDeleted(storage, project.project.id),
  );
  writeCurrentProject(storage, workflow, false);
  storage.setItem(KNOT_LIBRARY, JSON.stringify([workflow, ...saved]));
  return readProjectLibrary(storage);
}

export function prepareProjectForTab(
  storage: ProjectStorage,
  workflow: Workflow,
  hasLocalChanges: boolean,
) {
  const latest = hasLocalChanges ? workflow : findProject(storage, workflow.project.id) || workflow;
  return saveLibraryProject(storage, latest);
}

export function deleteLibraryProject(storage: ProjectStorage, id: string) {
  const remaining = snapshots(storage).filter((project) => project.project.id !== id);
  const current = storage.getItem(KNOT_STORAGE);
  const previous = [
    deletedKey(id),
    KNOT_LIBRARY,
    projectDraftKey(id),
    projectBillingKey(id),
    KNOT_STORAGE,
  ].map((key) => [key, storage.getItem(key)] as const);
  try {
    // Stop other tabs from recreating a deleted project through a pending autosave.
    storage.setItem(deletedKey(id), 'deleted');
    storage.setItem(KNOT_LIBRARY, JSON.stringify(remaining));
    storage.removeItem(projectDraftKey(id));
    storage.removeItem(projectBillingKey(id));
    if (parseStored(current)?.project.id === id) storage.removeItem(KNOT_STORAGE);
  } catch (error) {
    for (const [key, value] of previous) {
      try {
        if (value === null) storage.removeItem(key);
        else storage.setItem(key, value);
      } catch {
        // Keep trying to restore the remaining entries if storage becomes unavailable.
      }
    }
    throw error;
  }
  return readProjectLibrary(storage);
}

export function projectHref(pathname: string, search: string, id: string, hash = '#/workspace') {
  const query = new URLSearchParams(search);
  query.set(PROJECT_QUERY, id);
  return `${pathname}?${query.toString()}${hash}`;
}
