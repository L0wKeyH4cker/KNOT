import assert from 'node:assert/strict';
import test from 'node:test';
import { emptyWorkflow, parseWorkflow } from '../src/model.ts';
import { withRequirements } from '../src/requirements.ts';

const document = {
  filename: '项目需求.pdf', source_type: 'pdf', sha256: '12345678' + 'a'.repeat(56), page_count: 2,
  text: '[Page 1]\n整理项目背景。\n\n[Page 2]\n最后一页：输出建议 CSV，不得编造调查数据。',
  pages: [{ number: 1, text: '整理项目背景。' }, { number: 2, text: '输出建议 CSV，不得编造调查数据。' }],
  warnings: [],
};
const analysis = {
  project_name: '校园通勤研究', goal: '研究校园通勤体验。', deliverables: ['研究报告', '建议 CSV'],
  tasks: [{ title: '整理需求', description: '检查原始材料并标记缺失信息。', acceptance: '说明所有来源与未知项。', source_pages: [1, 2] }],
  constraints: ['不得编造调查数据'], missing_information: ['尚未提供调查数据'],
};

test('using requirements preserves members and unrelated materials without mutating the workspace', () => {
  const original = emptyWorkflow();
  original.project.name = '用户选择的名称';
  original.project.members[0].name = '陈同学';
  original.project.members[0].skills = '数据分析';
  original.resources = [{ id: 'existing', name: 'Existing material', path: 'inputs/existing.md', description: 'Keep this', example: false, content: 'User notes' }];
  const snapshot = structuredClone(original);
  const next = withRequirements(original, document, analysis);
  assert.deepEqual(original, snapshot);
  assert.equal(next.project.name, '用户选择的名称');
  assert.deepEqual(next.project.members, snapshot.project.members);
  assert.deepEqual(next.resources[0], snapshot.resources[0]);
  assert.equal(next.resources.length, 3);
});

test('source text and user-reviewed tasks survive JSON save and import in normal resources', () => {
  const edited = structuredClone(analysis);
  edited.tasks[0].acceptance = '用户确认：说明所有来源，并检查最后一页要求。';
  const next = withRequirements(emptyWorkflow(), document, edited);
  const restored = parseWorkflow(JSON.parse(JSON.stringify(next)));
  assert.equal(restored.project.name, analysis.project_name);
  assert.equal(restored.resources[0].content, document.text);
  assert.equal(restored.resources[0].example, false);
  assert.deepEqual(JSON.parse(restored.resources[1].content), edited);
  assert.match(restored.project.goal, /用户确认/);
  assert.match(restored.project.goal, /不得编造调查数据/);
  assert.match(restored.project.goal, /尚未提供调查数据/);
  assert.match(restored.project.goal, /Source pages: 1, 2/);
  assert.equal(restored.project.deliverable, '研究报告; 建议 CSV');
});

test('re-analyzing the same uploaded source replaces its pair instead of duplicating resources', () => {
  const first = withRequirements(emptyWorkflow(), document, analysis);
  const editedDocument = { ...document, text: document.text + '\n用户补充：检查可访问性。' };
  const editedAnalysis = { ...analysis, constraints: [...analysis.constraints, '检查可访问性'] };
  const next = withRequirements(first, editedDocument, editedAnalysis);
  assert.equal(next.resources.length, 2);
  assert.equal(new Set(next.resources.map(resource => resource.id)).size, 2);
  assert.equal(next.resources[0].content, editedDocument.text);
  assert.deepEqual(JSON.parse(next.resources[1].content), editedAnalysis);
  assert.equal(first.resources[0].content, document.text);
});

test('empty work and incomplete reviewed tasks are rejected before workflow generation', () => {
  for (const edited of [
    { ...analysis, goal: ' ' },
    { ...analysis, deliverables: ['', ' '] },
    { ...analysis, tasks: [] },
    { ...analysis, tasks: [{ ...analysis.tasks[0], title: ' ' }] },
    { ...analysis, tasks: [{ ...analysis.tasks[0], description: '' }] },
    { ...analysis, tasks: [{ ...analysis.tasks[0], acceptance: '' }] },
  ]) assert.throws(() => withRequirements(emptyWorkflow(), document, edited));
});

test('requirements source cannot persist secret-shaped content', () => {
  const unsafe = { ...document, text: 'A fixture token: sk-proj-TESTONLY00000000000000000000' };
  assert.throws(() => withRequirements(emptyWorkflow(), unsafe, analysis), /API key/);
});
