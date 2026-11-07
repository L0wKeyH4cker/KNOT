import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { KNOT_LIBRARY, KNOT_STORAGE, migrateLegacyStorage } from '../src/storage.ts';

const legacyCurrent = 'teamblocks.current.v1';
const legacyLibrary = 'teamblocks.projects.v1';
const template = JSON.parse(
  readFileSync(new URL('../examples/team-research.json', import.meta.url), 'utf8'),
);
function memoryStorage(entries = {}) {
  const values = new Map(Object.entries(entries));
  const writes = [];
  return {
    values,
    writes,
    getItem(key) {
      return values.has(key) ? values.get(key) : null;
    },
    setItem(key, value) {
      writes.push(key);
      values.set(key, value);
    },
  };
}

test('migrates complete projects and library once without removing legacy backups', () => {
  const saved = JSON.stringify(template);
  const library = JSON.stringify([template]);
  const storage = memoryStorage({ [legacyCurrent]: saved, [legacyLibrary]: library });
  assert.deepEqual(migrateLegacyStorage(storage), { current: true, projects: true });
  assert.deepEqual(JSON.parse(storage.getItem(KNOT_STORAGE)), template);
  assert.deepEqual(JSON.parse(storage.getItem(KNOT_LIBRARY)), [template]);
  assert.equal(storage.getItem(legacyCurrent), saved);
  assert.equal(storage.getItem(legacyLibrary), library);
  assert.deepEqual(migrateLegacyStorage(storage), { current: false, projects: false });
  assert.equal(storage.writes.length, 2);
});

test('never overwrites existing new storage, including an empty value', () => {
  const storage = memoryStorage({
    [legacyCurrent]: JSON.stringify(template),
    [legacyLibrary]: JSON.stringify([template]),
    [KNOT_STORAGE]: '',
    [KNOT_LIBRARY]: '[]',
  });
  assert.deepEqual(migrateLegacyStorage(storage), { current: false, projects: false });
  assert.equal(storage.getItem(KNOT_STORAGE), '');
  assert.equal(storage.getItem(KNOT_LIBRARY), '[]');
  assert.equal(storage.writes.length, 0);
});

test('a damaged current project does not prevent migration of a valid library', () => {
  const storage = memoryStorage({
    [legacyCurrent]: '{broken JSON',
    [legacyLibrary]: JSON.stringify([template]),
  });
  assert.deepEqual(migrateLegacyStorage(storage), { current: false, projects: true });
  assert.equal(storage.getItem(KNOT_STORAGE), null);
  assert.equal(storage.getItem(legacyCurrent), '{broken JSON');
});

test('invalid or unsafe projects are not copied and libraries are never partly migrated', () => {
  const unsafe = structuredClone(template);
  unsafe.nodes[0].config.api_key = 'not-a-real-key';
  for (const library of [{ project: template }, [template, null], [template, unsafe]]) {
    const saved = JSON.stringify(library);
    const storage = memoryStorage({
      [legacyCurrent]: JSON.stringify(unsafe),
      [legacyLibrary]: saved,
    });
    assert.deepEqual(migrateLegacyStorage(storage), { current: false, projects: false });
    assert.equal(storage.writes.length, 0);
    assert.equal(storage.getItem(legacyLibrary), saved);
  }
});

test('quota failures retain legacy data and allow a later migration retry', () => {
  const saved = JSON.stringify(template);
  const storage = memoryStorage({ [legacyCurrent]: saved });
  const write = storage.setItem;
  storage.setItem = () => {
    throw Error('Quota exceeded');
  };
  assert.deepEqual(migrateLegacyStorage(storage), { current: false, projects: false });
  assert.equal(storage.getItem(legacyCurrent), saved);
  assert.equal(storage.getItem(KNOT_STORAGE), null);
  storage.setItem = write;
  assert.deepEqual(migrateLegacyStorage(storage), { current: true, projects: false });
  assert.equal(storage.getItem(legacyCurrent), saved);
});

test('unavailable storage does not break startup', () => {
  const unavailable = {
    getItem() {
      throw Error('Storage blocked');
    },
    setItem() {
      assert.fail('Should not write inaccessible storage');
    },
  };
  assert.deepEqual(migrateLegacyStorage(unavailable), { current: false, projects: false });
});
