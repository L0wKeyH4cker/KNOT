import test from 'node:test';
import assert from 'node:assert/strict';
import { ONBOARDING_KEY, readOnboardingStatus, rememberOnboarding } from '../src/onboarding.ts';

function storage(initial = []) {
  const values = new Map(initial);
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    values,
  };
}

test('new visits and malformed or obsolete records still offer the introduction', () => {
  for (const value of [
    null,
    'invalid json',
    '{}',
    '{"version":0,"status":"completed"}',
    '{"version":1,"status":"unknown"}',
  ]) {
    assert.equal(
      readOnboardingStatus(storage(value === null ? [] : [[ONBOARDING_KEY, value]])),
      null,
    );
  }
});

test('completion and skipping are remembered without touching saved projects or connections', () => {
  const store = storage([
    ['knot.current.v1', 'original-project'],
    ['knot.projects.v1', 'original-library'],
    ['knot.planner.v1', 'original-connection'],
  ]);
  for (const status of ['completed', 'skipped']) {
    rememberOnboarding(status, store);
    assert.equal(readOnboardingStatus(store), status);
  }
  assert.equal(store.getItem('knot.current.v1'), 'original-project');
  assert.equal(store.getItem('knot.projects.v1'), 'original-library');
  assert.equal(store.getItem('knot.planner.v1'), 'original-connection');
  assert.equal(store.values.size, 4);
});

test('privacy or storage failures do not prevent using or leaving the tour', () => {
  const denied = {
    getItem() {
      throw Error('Storage denied');
    },
    setItem() {
      throw Error('Storage denied');
    },
  };
  assert.equal(readOnboardingStatus(denied), null);
  assert.doesNotThrow(() => rememberOnboarding('completed', denied));
});
