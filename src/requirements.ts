import { assertSafeWorkflow } from './model.ts';
import type { Workflow, Resource } from './model.ts';

export type RequirementDocument = {
  filename: string;
  source_type: 'pdf' | 'text';
  sha256: string;
  page_count: number;
  text: string;
  pages: { number: number; text: string }[];
  warnings: string[];
};
export type RequirementAnalysis = {
  project_name: string;
  goal: string;
  deliverables: string[];
  tasks: { title: string; description: string; acceptance: string; source_pages: number[] }[];
  constraints: string[];
  missing_information: string[];
};

export function withRequirements(
  wf: Workflow,
  document: RequirementDocument,
  analysis: RequirementAnalysis,
): Workflow {
  analysis = {
    ...analysis,
    deliverables: analysis.deliverables.map((x) => x.trim()).filter(Boolean),
    constraints: analysis.constraints.map((x) => x.trim()).filter(Boolean),
    missing_information: analysis.missing_information.map((x) => x.trim()).filter(Boolean),
  };
  if (
    (!wf.project.name.trim() || /^untitled project$/i.test(wf.project.name)) &&
    !analysis.project_name.trim()
  )
    throw Error('Add a project name before generating.');
  if (!analysis.goal.trim() || !analysis.deliverables.some((x) => x.trim()))
    throw Error('Add a project goal and at least one deliverable before generating.');
  if (
    !analysis.tasks.length ||
    analysis.tasks.some((t) => !t.title.trim() || !t.description.trim() || !t.acceptance.trim())
  )
    throw Error('Each task needs a title, description, and acceptance criteria.');
  const hash = document.sha256.slice(0, 8);
  const sourceId = `requirements-source-${hash}`;
  const analysisId = `requirements-analysis-${hash}`;
  const resources: Resource[] = [
    {
      id: sourceId,
      name: `Requirements: ${document.filename}`,
      path: `inputs/requirements-${hash}.txt`,
      description: `Extracted requirement text from ${document.filename}; ${document.page_count} page(s). [Page N] markers identify source pages when present. May include user corrections.`,
      example: false,
      content: document.text,
    },
    {
      id: analysisId,
      name: `Reviewed tasks: ${document.filename}`,
      path: `inputs/requirements-analysis-${hash}.json`,
      description: `AI analysis reviewed by the user. Source: ${sourceId}. Missing information remains unresolved.`,
      example: false,
      content: JSON.stringify(analysis, null, 2),
    },
  ];
  const goal = [
    analysis.goal,
    'Tasks:\n' +
      analysis.tasks
        .map(
          (t, i) =>
            `${i + 1}. ${t.title}: ${t.description}\nAcceptance: ${t.acceptance}${t.source_pages.length ? `\nSource pages: ${t.source_pages.join(', ')}` : ''}`,
        )
        .join('\n'),
    analysis.constraints.length ? 'Constraints:\n' + analysis.constraints.join('\n') : '',
    analysis.missing_information.length
      ? 'Missing information (do not invent):\n' + analysis.missing_information.join('\n')
      : '',
  ]
    .filter(Boolean)
    .join('\n\n');
  const next: Workflow = {
    ...wf,
    project: {
      ...wf.project,
      name:
        !wf.project.name.trim() || /^untitled project$/i.test(wf.project.name)
          ? analysis.project_name
          : wf.project.name,
      goal,
      deliverable: analysis.deliverables.filter((x) => x.trim()).join('; '),
    },
    resources: [
      ...wf.resources.filter((r) => r.id !== sourceId && r.id !== analysisId),
      ...resources,
    ],
  };
  assertSafeWorkflow(next);
  return next;
}
