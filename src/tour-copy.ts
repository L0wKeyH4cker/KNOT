export const TOUR_COPY: Record<string, { title: string; description: string }> = {
  canvas: {
    title: 'Meet your team’s workflow',
    description:
      'This example turns campus research into a report. Each block has a job, and the canvas shows how the work moves from start to finish.',
  },
  blocks: {
    title: 'Start with small building blocks',
    description:
      'Drag blocks onto the canvas to add tasks, shared materials, parallel work, human review, or a final deliverable.',
  },
  connections: {
    title: 'Decide what happens next',
    description:
      'Solid lines set the order of work. Dashed data lines let a task read another block’s results. Independent branches can work in parallel.',
  },
  task: {
    title: 'Give every task a clear brief',
    description:
      'Click a block to set its instructions, expected result, AI agent, and human owner. This panel is where you make a task your own.',
  },
  agents: {
    title: 'Choose the right AI for each job',
    description:
      'Agents have their own role, instructions, and model connection. You can reuse an agent across tasks and choose different providers for different roles.',
  },
  project: {
    title: 'Bring your people and materials',
    description:
      'Project settings hold your goal, deliverables, teammates, and shared files. Keep the team’s context together here.',
  },
  planner: {
    title: 'Let a project brief be your starting point',
    description:
      'Upload requirements or describe your goal, then configure a planning model to draft a workflow. You review the proposed tasks before generating it.',
  },
  check: {
    title: 'Check your work before exporting',
    description:
      'Check looks for missing configuration and broken connections. It explains what needs attention before you download a runnable workflow.',
  },
  export: {
    title: 'Take the workflow with you',
    description:
      'Export runner downloads your workflow and its local Python runner. The example can run in mock mode; real tasks use the models you configure.',
  },
  complete: {
    title: 'Now make something of your own',
    description:
      'You know your way around. Head home, describe your project, and build a workflow for your team. You can replay this tour from the quick guide.',
  },
};
