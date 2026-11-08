import assert from 'node:assert/strict';
import test from 'node:test';
import { emptyWorkflow, newBlock, parseWorkflow } from '../src/model.ts';
import { withRequirements } from '../src/requirements.ts';
import { assignOwner } from '../src/ownership.ts';

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

test('named requirements replace the three placeholders and preserve all four assignments', () => {
  const original = emptyWorkflow();
  original.project.members = ['A', 'B', 'C'].map((letter, i) => ({ id: `member_${i + 1}`, name: `Member ${letter}`, skills: '' }));
  const named = { ...analysis, tasks: [
    ['汇总', 'Maya Chen'], ['场地', 'Leo Patel'], ['清单', 'Leo Patel'],
    ['预算', 'Nina Brooks'], ['排班', 'Nina Brooks'], ['宣传', 'Sam Rivera'],
  ].map(([title, owner]) => ({ ...analysis.tasks[0], title, owner })) };
  const before = structuredClone(original);
  const next = withRequirements(original, document, named);
  assert.deepEqual(next.project.members.map(member => member.name), ['Maya Chen', 'Leo Patel', 'Nina Brooks', 'Sam Rivera']);
  assert.deepEqual(JSON.parse(next.resources[1].content).tasks.map(task => [task.title, task.owner]), named.tasks.map(task => [task.title, task.owner]));
  assert.match(next.project.goal, /Owner: Sam Rivera/);
  assert.deepEqual(original, before);
  assert.deepEqual(withRequirements(next, document, named).project.members, next.project.members);
});

test('requirements reuse real people and keep their IDs and skills', () => {
  const original = emptyWorkflow();
  original.project.members = [{ id: 'maya-existing', name: 'Maya Chen', skills: 'Writing' }];
  const named = { ...analysis, tasks: [{ ...analysis.tasks[0], owner: '  maya chen  ' }, { ...analysis.tasks[0], owner: 'Sam Rivera' }] };
  const next = withRequirements(original, document, named);
  assert.deepEqual(next.project.members[0], original.project.members[0]);
  assert.equal(next.project.members.length, 2);
});

test('direct assignment changes one task, reuses names, and survives save/import', () => {
  const original = emptyWorkflow();
  original.nodes = [newBlock('agent_task', { x: 0, y: 0 }, original), newBlock('human_review', { x: 300, y: 0 }, original)];
  const before = structuredClone(original);
  const taskId = original.nodes[0].id;
  const reviewId = original.nodes[1].id;
  const first = assignOwner(original, taskId, '  Maya Chen  ');
  assert.equal(first.project.members.find(member => member.id === first.nodes[0].config.owner_id).name, 'Maya Chen');
  assert.equal(first.nodes[1].config.owner_id, original.nodes[1].config.owner_id);
  const next = assignOwner(first, reviewId, 'maya chen');
  assert.equal(next.project.members.length, first.project.members.length);
  assert.equal(next.nodes[1].config.owner_id, next.nodes[0].config.owner_id);
  assert.deepEqual(parseWorkflow(JSON.parse(JSON.stringify(next))), next);
  assert.deepEqual(original, before);
  for (const name of ['', '   ', 'x'.repeat(301), 'sk-proj-TESTONLY00000000000000000000']) {
    assert.throws(() => assignOwner(original, taskId, name));
  }
});

test('repeated name edits can reclaim unused entries without changing other task owners', () => {
  let workflow = emptyWorkflow();
  workflow.nodes = [newBlock('agent_task', { x: 0, y: 0 }, workflow), newBlock('human_review', { x: 300, y: 0 }, workflow)];
  const reviewOwner = workflow.nodes[1].config.owner_id;
  for (let index = 0; index < 60; index++) {
    workflow = assignOwner(workflow, workflow.nodes[0].id, `Owner ${index}`);
    assert.equal(workflow.nodes[1].config.owner_id, reviewOwner);
    assert.ok(workflow.project.members.some(member => member.id === reviewOwner));
    assert.ok(workflow.project.members.length <= 50);
  }
  assert.equal(workflow.project.members.find(member => member.id === workflow.nodes[0].config.owner_id).name, 'Owner 59');
});
