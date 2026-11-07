import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import {
  PROJECT_DELETED_PREFIX,
  deleteLibraryProject,
  findProject,
  isProjectDeleted,
  prepareProjectForTab,
  projectDraftKey,
  projectHref,
  readProjectLibrary,
  saveLibraryProject,
  writeCurrentProject,
} from '../src/project-storage.ts';
import { KNOT_LIBRARY, KNOT_STORAGE, migrateLegacyStorage } from '../src/storage.ts';

const template = JSON.parse(
  readFileSync(new URL('../examples/team-research.json', import.meta.url), 'utf8'),
);
function project(id) {
  const workflow = structuredClone(template);
  workflow.project.id = id;
  workflow.project.name = `Project ${id}`;
  return workflow;
}
function memoryStorage(entries = {}) {
  const values = new Map(Object.entries(entries));
  return {
    values,
    getItem(key) {
      return values.get(key) ?? null;
    },
    setItem(key, value) {
      values.set(key, value);
    },
    removeItem(key) {
      values.delete(key);
    },
  };
}

test('opening and saving a different project keeps the original tab current project untouched', () => {
  const a = project('a');
  const b = project('b');
  const storage = memoryStorage({ [KNOT_STORAGE]: JSON.stringify(a) });
  saveLibraryProject(storage, b);
  b.project.goal = 'Edited only in the new tab';
  writeCurrentProject(storage, b, false);
  saveLibraryProject(storage, b);
  assert.deepEqual(JSON.parse(storage.getItem(KNOT_STORAGE)), a);
  assert.deepEqual(findProject(storage, 'b'), b);
  assert.deepEqual(findProject(storage, 'a'), a);
});

test('each project restores its latest draft instead of an older library snapshot', () => {
  const a = project('a');
  const b = project('b');
  const storage = memoryStorage();
  saveLibraryProject(storage, a);
  saveLibraryProject(storage, b);
  b.nodes[0].label = 'Latest work in B';
  writeCurrentProject(storage, b, false);
  a.nodes[0].label = 'Latest work in A';
  writeCurrentProject(storage, a, true);
  assert.deepEqual(findProject(storage, 'a'), a);
  assert.deepEqual(findProject(storage, 'b'), b);
  assert.deepEqual(
    readProjectLibrary(storage).find((w) => w.project.id === 'b'),
    b,
  );
});

test('reopening an unchanged old tab preserves edits already made in another tab', () => {
  const old = project('a');
  const edited = structuredClone(old);
  edited.project.name = 'Updated in the other tab';
  const storage = memoryStorage();
  writeCurrentProject(storage, old, true);
  saveLibraryProject(storage, old);
  writeCurrentProject(storage, edited, false);
  prepareProjectForTab(storage, old, false);
  assert.deepEqual(findProject(storage, 'a'), edited);
  assert.deepEqual(JSON.parse(storage.getItem(KNOT_STORAGE)), old);
});

test('opening a project immediately includes current local edits that have not autosaved yet', () => {
  const workflow = project('a');
  const storage = memoryStorage();
  writeCurrentProject(storage, workflow, true);
  const unsaved = structuredClone(workflow);
  unsaved.project.goal = 'Just typed before opening the new tab';
  prepareProjectForTab(storage, unsaved, true);
  assert.deepEqual(findProject(storage, 'a'), unsaved);
  assert.deepEqual(JSON.parse(storage.getItem(KNOT_STORAGE)), workflow);
});

test('an unknown link never falls back to a different current project', () => {
  const a = project('a');
  const storage = memoryStorage({ [KNOT_STORAGE]: JSON.stringify(a) });
  assert.equal(findProject(storage, 'missing'), null);
  assert.equal(findProject(storage, ''), null);
  assert.deepEqual(findProject(storage, 'a'), a);
});

test('delete removes only the selected project and its draft', () => {
  const a = project('a');
  const b = project('b');
  const storage = memoryStorage();
  writeCurrentProject(storage, a, true);
  saveLibraryProject(storage, a);
  saveLibraryProject(storage, b);
  const remaining = deleteLibraryProject(storage, 'b');
  assert.deepEqual(remaining, [a]);
  assert.equal(findProject(storage, 'b'), null);
  assert.equal(storage.getItem(projectDraftKey('b')), null);
  assert.deepEqual(JSON.parse(storage.getItem(KNOT_STORAGE)), a);
  assert.deepEqual(findProject(storage, 'a'), a);
});

test('deleting the current project clears it without deleting other projects', () => {
  const a = project('a');
  const b = project('b');
  const storage = memoryStorage();
  writeCurrentProject(storage, a, true);
  saveLibraryProject(storage, a);
  saveLibraryProject(storage, b);
  deleteLibraryProject(storage, 'a');
  assert.equal(storage.getItem(KNOT_STORAGE), null);
  assert.equal(storage.getItem(projectDraftKey('a')), null);
  assert.equal(findProject(storage, 'a'), null);
  assert.deepEqual(readProjectLibrary(storage), [b]);
});

test('a pending autosave or explicit save in an old tab cannot resurrect a deleted project', () => {
  const a = project('a');
  const storage = memoryStorage();
  saveLibraryProject(storage, a);
  deleteLibraryProject(storage, 'a');
  assert.throws(() => writeCurrentProject(storage, a, true), /deleted/);
  assert.throws(() => saveLibraryProject(storage, a), /deleted/);
  assert.deepEqual(readProjectLibrary(storage), []);
  assert.equal(storage.getItem(projectDraftKey('a')), null);
});

test('legacy backups cannot make a deleted project reappear after reload', () => {
  const a = project('a');
  const storage = memoryStorage({
    'teamblocks.current.v1': JSON.stringify(a),
    'teamblocks.projects.v1': JSON.stringify([a]),
  });
  migrateLegacyStorage(storage);
  deleteLibraryProject(storage, 'a');
  migrateLegacyStorage(storage);
  assert.equal(findProject(storage, 'a'), null);
  assert.deepEqual(readProjectLibrary(storage), []);
  assert.equal(isProjectDeleted(storage, 'a'), true);
});

test('a failed deletion restores the original library, draft, and current project', () => {
  const a = project('a');
  const storage = memoryStorage();
  writeCurrentProject(storage, a, true);
  saveLibraryProject(storage, a);
  const before = new Map(storage.values);
  const write = storage.setItem;
  let failOnce = true;
  storage.setItem = (key, value) => {
    if (key === KNOT_LIBRARY && failOnce) {
      failOnce = false;
      throw new Error('Storage is full');
    }
    write(key, value);
  };
  assert.throws(() => deleteLibraryProject(storage, 'a'), /Storage is full/);
  assert.deepEqual(storage.values, before);
  assert.equal(storage.getItem(PROJECT_DELETED_PREFIX + 'a'), null);
});

test('malformed libraries are never silently replaced by an open or delete action', () => {
  const storage = memoryStorage({ [KNOT_LIBRARY]: '{damaged library' });
  const before = new Map(storage.values);
  assert.throws(() => saveLibraryProject(storage, project('a')));
  assert.throws(() => deleteLibraryProject(storage, 'a'));
  assert.deepEqual(storage.values, before);
});

test('corrupt or mismatched drafts fall back to the correct saved project', () => {
  const a = project('a');
  const storage = memoryStorage({
    [KNOT_LIBRARY]: JSON.stringify([a]),
    [projectDraftKey('a')]: JSON.stringify(project('b')),
  });
  assert.deepEqual(findProject(storage, 'a'), a);
  storage.setItem(projectDraftKey('a'), '{broken draft');
  assert.deepEqual(findProject(storage, 'a'), a);
});

test('project links safely encode IDs and preserve the application path and other query parameters', () => {
  const id = 'project / ? # & spaces';
  const href = projectHref('/KNOT/', '?view=compact&project=old', id);
  const parsed = new URL(href, 'https://fixture.invalid');
  assert.equal(parsed.pathname, '/KNOT/');
  assert.equal(parsed.searchParams.get('project'), id);
  assert.equal(parsed.searchParams.get('view'), 'compact');
  assert.equal(parsed.hash, '#/workspace');
  assert.equal(projectHref('/', '?project=old', 'new', '#/projects'), '/?project=new#/projects');
});
