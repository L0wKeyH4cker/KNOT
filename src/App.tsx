import { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  applyNodeChanges,
  useReactFlow,
  MarkerType,
  BackgroundVariant,
} from '@xyflow/react';
import type { Connection, NodeChange, Node as FlowNode, Edge as FlowEdge } from '@xyflow/react';
import {
  Blocks,
  LayoutGrid,
  Bot,
  Settings2,
  HelpCircle,
  Plus,
  ChevronDown,
  ChevronRight,
  Undo2,
  Redo2,
  Download,
  Upload,
  Check,
  CheckCircle2,
  CircleAlert,
  X,
  Sparkles,
  ArrowUpRight,
  FileJson,
  Save,
  FolderOpen,
  MousePointer2,
  GripVertical,
  ArrowRight,
  ArrowLeft,
  Trash2,
  Cable,
  LoaderCircle,
} from 'lucide-react';
import Home from './Home';
import { TOUR_STEPS, readOnboardingStatus, rememberOnboarding } from './onboarding';
import type { OnboardingStatus } from './onboarding';
import { usePage } from './navigation';
import BlockNode, { icons } from './BlockNode';
import Inspector, { Field } from './Inspector';
import { AgentsSettings, ProjectSettings } from './Settings';
import RequirementIntake from './RequirementIntake';
import { KNOT_STORAGE, KNOT_LIBRARY, migrateLegacyStorage } from './storage';
import type { Planner } from './Settings';
import {
  KINDS,
  uid,
  emptyWorkflow,
  newBlock,
  hasCycle,
  parseWorkflow,
  assertSafeWorkflow,
  localIssues,
  api,
  download,
} from './model';
import type { Workflow, Block, NodeKind, Link, Issue } from './model';
const nodeTypes = { block: BlockNode };
const GuidedTour = lazy(() => import('./GuidedTour'));
const QuickGuide = lazy(() => import('./QuickGuide'));
const STORAGE = KNOT_STORAGE,
  LIBRARY = KNOT_LIBRARY,
  PLANNER = 'knot.planner.v1';
function readPlanner(): Planner | null {
  try {
    // Keep an existing KNOT setting authoritative, including an empty value.
    // A validated older UI setting is copied by the normal persistence effect.
    const stored = localStorage.getItem(PLANNER);
    const value = JSON.parse(
      (stored === null ? localStorage.getItem('teamblocks.planner.v1') : stored) || 'null',
    );
    if (
      !value ||
      !['openai', 'anthropic'].includes(value.provider) ||
      !['model', 'credential_ref', 'base_url'].every((key) => typeof value[key] === 'string') ||
      !/^[A-Z_][A-Z0-9_]*$/.test(value.credential_ref)
    )
      return null;
    assertSafeWorkflow(value);
    return {
      provider: value.provider,
      model: value.model,
      credential_ref: value.credential_ref,
      base_url: value.base_url,
    };
  } catch {
    return null;
  }
}
function restore() {
  try {
    migrateLegacyStorage(localStorage);
    const raw = localStorage.getItem(STORAGE);
    return raw ? parseWorkflow(JSON.parse(raw)) : null;
  } catch {
    return null;
  }
}
const restored = restore();
type Modal = 'agents' | 'project' | 'planner' | 'check' | 'saved' | 'help' | 'exported' | null;
const secondaryPages = new Set([
  'agents',
  'project',
  'planner',
  'check',
  'saved',
  'help',
  'exported',
]);
function readProjects(): Workflow[] {
  try {
    return (JSON.parse(localStorage.getItem(LIBRARY) || '[]') as unknown[]).map(parseWorkflow);
  } catch {
    return [];
  }
}
function hasProject(workflow: Workflow) {
  return (
    workflow.nodes.length > 0 ||
    !!workflow.project.goal.trim() ||
    workflow.project.name !== 'Untitled project'
  );
}
export default function App() {
  const [page, navigate] = usePage();
  const modalOrigin = useRef<'home' | 'canvas'>(
    page === 'saved' || page === 'help' ? 'home' : 'canvas',
  );
  const modal = secondaryPages.has(page) ? (page as Modal) : null;
  const [wizardStep, setWizardStep] = useState<1 | 2>(1);
  const wizard = page === 'new' ? wizardStep : 0;
  const setModal = useCallback(
    (next: Modal) => {
      if (next) {
        if (!secondaryPages.has(page)) modalOrigin.current = page === 'home' ? 'home' : 'canvas';
        navigate(next);
      } else {
        navigate(modalOrigin.current);
      }
    },
    [page, navigate],
  );
  const setWizard = (next: 0 | 1 | 2) => {
    if (next === 0) navigate('canvas');
    else {
      setWizardStep(next);
      navigate('new');
    }
  };
  const [wf, setWf] = useState<Workflow>(restored || emptyWorkflow),
    [selected, setSelected] = useState<string | null>(null),
    [edgeSelected, setEdgeSelected] = useState<string | null>(null),
    [issues, setIssues] = useState<Issue[]>([]),
    [toast, setToast] = useState(''),
    [busy, setBusy] = useState(''),
    [showData, setShowData] = useState(true),
    [search, setSearch] = useState(''),
    [online, setOnline] = useState(false),
    [credentials, setCredentials] = useState<Record<string, boolean>>({}),
    [savedStatus, setSavedStatus] = useState('Saved on this device'),
    [historyTick, setHistoryTick] = useState(0),
    [savedProjects, setSavedProjects] = useState<Workflow[]>(readProjects);
  const [planner, setPlanner] = useState<Planner>(
    () =>
      readPlanner() || {
        provider: 'openai',
        model: '',
        credential_ref: 'OPENAI_API_KEY',
        base_url: '',
      },
  );
  const [plannerReady, setPlannerReady] = useState(() => !!readPlanner());
  const plannerInitialized = useRef(plannerReady);
  const [draft, setDraft] = useState({ name: '', members: 3, goal: '', deliverable: '' });
  const [intakeProject, setIntakeProject] = useState<Workflow | null>(null);
  const [firstVisit, setFirstVisit] = useState(() => readOnboardingStatus() === null);
  const [tourStep, setTourStep] = useState<number | null>(null);
  const [focusHomeComposer, setFocusHomeComposer] = useState(false);
  const tourSnapshot = useRef<{ workflow: Workflow; search: string; showData: boolean } | null>(
    null,
  );
  const templateRequest = useRef(0);
  const validationRequest = useRef(0);
  const planningRequest = useRef(0);
  const activePage = useRef(page);
  activePage.current = page;
  useEffect(() => {
    // Native browser navigation must discard the same temporary project as Back.
    // Starting intake batches the candidate with navigation to planner, so it stays.
    if (page !== 'planner') {
      planningRequest.current += 1;
      setIntakeProject(null);
      setBusy((value) => (value === 'plan' ? '' : value));
    }
  }, [page]);
  const past = useRef<Workflow[]>([]),
    future = useRef<Workflow[]>([]),
    current = useRef(wf),
    fileInput = useRef<HTMLInputElement>(null),
    toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null),
    flow = useReactFlow();
  current.current = wf;
  const notify = useCallback((message: string) => {
    setToast(message);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(''), 6500);
  }, []);
  const dismissWelcome = () => {
    templateRequest.current += 1;
    setBusy((value) => (value === 'template' ? '' : value));
    rememberOnboarding('skipped');
    setFirstVisit(false);
  };
  const endTour = useCallback(
    (status: OnboardingStatus) => {
      const snapshot = tourSnapshot.current;
      if (snapshot) {
        setWf(snapshot.workflow);
        setSearch(snapshot.search);
        setShowData(snapshot.showData);
        tourSnapshot.current = null;
      }
      validationRequest.current += 1;
      setTourStep(null);
      setSelected(null);
      setEdgeSelected(null);
      setToast('');
      setBusy((value) => (value === 'check' || value === 'template' ? '' : value));
      rememberOnboarding(status);
      setFirstVisit(false);
      setFocusHomeComposer(true);
      navigate('home', { replace: true });
    },
    [navigate],
  );
  useEffect(() => {
    // Native Back exits the tour rather than stranding a coachmark on another page.
    if (tourStep !== null && page !== TOUR_STEPS[tourStep].page) endTour('skipped');
  }, [page, tourStep, endTour]);
  const remember = useCallback(() => {
    past.current = [...past.current.slice(-49), structuredClone(current.current)];
    future.current = [];
    setHistoryTick((x) => x + 1);
  }, []);
  const change = useCallback(
    (next: Workflow, record = true) => {
      try {
        assertSafeWorkflow(next);
        if (record) remember();
        setWf(next);
      } catch (e) {
        notify((e as Error).message);
      }
    },
    [remember, notify],
  );
  const undo = useCallback(() => {
    const prev = past.current.pop();
    if (prev) {
      future.current.push(structuredClone(current.current));
      setWf(prev);
      setSelected(null);
      setHistoryTick((x) => x + 1);
    }
  }, []);
  const redo = useCallback(() => {
    const next = future.current.pop();
    if (next) {
      past.current.push(structuredClone(current.current));
      setWf(next);
      setSelected(null);
      setHistoryTick((x) => x + 1);
    }
  }, []);
  useEffect(() => {
    if (tourSnapshot.current) return;
    const timer = setTimeout(() => {
      if (tourSnapshot.current) return;
      try {
        assertSafeWorkflow(wf);
        localStorage.setItem(STORAGE, JSON.stringify(wf));
        setSavedStatus('Saved on this device');
      } catch {
        setSavedStatus('Not saved · storage unavailable');
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [wf, tourStep]);
  useEffect(() => {
    api<{
      ok: boolean;
      planner_credentials: Record<string, boolean>;
      default_planner?: Planner | null;
    }>('health')
      .then((x) => {
        setOnline(x.ok);
        setCredentials(x.planner_credentials || {});
        if (!plannerInitialized.current) {
          if (x.default_planner) setPlanner(x.default_planner);
          plannerInitialized.current = true;
          setPlannerReady(true);
        }
      })
      .catch(() => setOnline(false));
  }, [modal]);
  useEffect(() => {
    if (!plannerReady) return;
    try {
      assertSafeWorkflow(planner);
      localStorage.setItem(PLANNER, JSON.stringify(planner));
    } catch {
      /* The connection remains usable if browser storage is unavailable. */
    }
  }, [planner, plannerReady]);
  const fit = () =>
    requestAnimationFrame(() =>
      setTimeout(() => flow.fitView({ padding: 0.2, duration: 350, maxZoom: 1 }), 60),
    );
  const save = useCallback(() => {
    try {
      assertSafeWorkflow(current.current);
      const raw = JSON.parse(localStorage.getItem(LIBRARY) || '[]') as Workflow[];
      const next = [
        current.current,
        ...raw.filter((x) => x.project.id !== current.current.project.id),
      ].slice(0, 20);
      localStorage.setItem(LIBRARY, JSON.stringify(next));
      localStorage.setItem(STORAGE, JSON.stringify(current.current));
      setSavedProjects(next);
      notify('Project saved. Open it anytime from your project library.');
    } catch (e) {
      notify('Could not save: ' + (e as Error).message);
    }
  }, [notify]);
  const duplicate = useCallback(() => {
    const n = current.current.nodes.find((n) => n.id === selected);
    if (n) {
      const clone = {
        ...structuredClone(n),
        id: uid(n.type),
        label: n.label + ' copy',
        position: { x: n.position.x + 40, y: n.position.y + 40 },
      };
      change({ ...current.current, nodes: [...current.current.nodes, clone] });
      setSelected(clone.id);
    }
  }, [selected, change]);
  const remove = useCallback(() => {
    if (selected) {
      change({
        ...current.current,
        nodes: current.current.nodes.filter((n) => n.id !== selected),
        edges: current.current.edges.filter((e) => e.source !== selected && e.target !== selected),
      });
      setSelected(null);
    } else if (edgeSelected) {
      change({
        ...current.current,
        edges: current.current.edges.filter((e) => e.id !== edgeSelected),
      });
      setEdgeSelected(null);
    }
  }, [selected, edgeSelected, change]);
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (tourStep !== null) return;
      if (page === 'home') return;
      if (page === 'new') {
        if (e.key === 'Escape') navigate('home');
        return;
      }
      if ((e.target as HTMLElement).closest('input,textarea,select,[contenteditable="true"]'))
        return;
      if (e.ctrlKey || e.metaKey) {
        if (e.key === 'z') {
          e.preventDefault();
          e.shiftKey ? redo() : undo();
        }
        if (e.key === 'y') {
          e.preventDefault();
          redo();
        }
        if (e.key === 's') {
          e.preventDefault();
          save();
        }
        if (e.key === 'd') {
          e.preventDefault();
          duplicate();
        }
      }
      if ((e.key === 'Delete' || e.key === 'Backspace') && !modal && !wizard) {
        e.preventDefault();
        remove();
      }
      if (e.key === 'Escape' && busy !== 'plan') {
        if (modal) setModal(null);
        setIntakeProject(null);
        setSelected(null);
        setEdgeSelected(null);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [
    undo,
    redo,
    save,
    duplicate,
    remove,
    modal,
    wizard,
    busy,
    page,
    navigate,
    setModal,
    tourStep,
  ]);
  const add = (kind: NodeKind, position?: { x: number; y: number }) => {
    const n = newBlock(
      kind,
      position ||
        flow.screenToFlowPosition({ x: window.innerWidth * 0.53, y: window.innerHeight * 0.47 }),
      wf,
    );
    change({ ...wf, nodes: [...wf.nodes, n] });
    setSelected(n.id);
    setEdgeSelected(null);
    notify(`${KINDS[kind].name} added. Connect its ports to build your workflow.`);
  };
  const connect = (connection: Connection, replaced?: string) => {
    const { source, target, sourceHandle, targetHandle } = connection;
    if (!source || !target) return;
    const from = wf.nodes.find((n) => n.id === source),
      to = wf.nodes.find((n) => n.id === target);
    const kind = sourceHandle === 'data-out' ? 'data' : 'control';
    let error = '';
    if (source === target) error = 'A block cannot connect to itself.';
    else if (!from || !to) error = 'Connection block not found.';
    else if (to.type === 'start') error = 'Start cannot have incoming connections.';
    else if ((kind === 'data') !== (targetHandle === 'data-in'))
      error = 'Connect matching ports: side ports for execution, blue ports for data.';
    else if (kind === 'control' && from.type === 'output')
      error = 'Output is the end of an execution path.';
    const link: Link = {
      id: uid('edge'),
      source,
      target,
      source_port: sourceHandle || 'out',
      target_port: targetHandle || 'in',
      kind,
    };
    const edges = wf.edges.filter((e) => e.id !== replaced);
    if (
      edges.some(
        (e) =>
          e.source === source &&
          e.target === target &&
          e.source_port === link.source_port &&
          e.target_port === link.target_port,
      )
    )
      error = 'These ports are already connected.';
    if (hasCycle(wf.nodes, [...edges, link]))
      error = 'This would create a cycle. Workflows must move forward.';
    if (error) {
      notify(error);
      return;
    }
    change({ ...wf, edges: [...edges, link] });
    notify(
      kind === 'data'
        ? 'Data connected. The destination can now read this result.'
        : 'Execution connected. The destination waits for this branch.',
    );
  };
  const onNodesChange = (changes: NodeChange[]) => {
    if (!changes.some((c) => c.type === 'position')) return;
    const moved = applyNodeChanges(
      changes,
      wf.nodes.map((n) => ({ id: n.id, position: n.position, data: {} })),
    );
    setWf((w) => ({
      ...w,
      nodes: w.nodes.map((n) => ({
        ...n,
        position: moved.find((x) => x.id === n.id)?.position || n.position,
      })),
    }));
  };
  const fitTour = () =>
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        void flow.fitView({ padding: 0.2, duration: 0, maxZoom: 1 });
      }),
    );
  async function loadExample(guided: boolean) {
    const request = ++templateRequest.current;
    const source = activePage.current;
    const isCurrentRequest = () =>
      templateRequest.current === request && activePage.current === source;
    setBusy('template');
    try {
      const value = parseWorkflow(await api<Workflow>('template'));
      if (!isCurrentRequest()) return;
      if (guided) {
        // Keep the visitor's actual project and history untouched throughout the demo.
        tourSnapshot.current = { workflow: structuredClone(current.current), search, showData };
        setWf(value);
        setSearch('');
        setShowData(true);
        setTourStep(0);
        setToast('');
      } else change(value);
      navigate('canvas');
      setSelected(null);
      setEdgeSelected(null);
      if (guided) fitTour();
      else {
        notify('Example template loaded — all blocks are editable. Uses labeled sample data.');
        fit();
      }
    } catch (e) {
      if (isCurrentRequest()) notify((e as Error).message);
    } finally {
      if (request === templateRequest.current)
        setBusy((value) => (value === 'template' ? '' : value));
    }
  }
  const loadTemplate = () => loadExample(false);
  const startGuidedExample = () => loadExample(true);
  async function runCheck(candidate: Workflow) {
    const request = ++validationRequest.current;
    setBusy('check');
    try {
      const { issues } = await api<{ issues: Issue[] }>('validate', {
        workflow: candidate,
        mode: 'mock',
      });
      if (request !== validationRequest.current) return;
      setIssues(issues);
      setOnline(true);
    } catch (e) {
      if (request !== validationRequest.current) return;
      setIssues([
        ...localIssues(candidate),
        {
          severity: 'error',
          code: 'backend',
          message: 'Full check unavailable: ' + (e as Error).message,
        },
      ]);
    } finally {
      if (request === validationRequest.current)
        setBusy((value) => (value === 'check' ? '' : value));
    }
  }
  async function check() {
    setModal('check');
    await runCheck(wf);
  }
  const moveTour = (index: number) => {
    if (index < 0 || index >= TOUR_STEPS.length) return;
    const step = TOUR_STEPS[index];
    setTourStep(index);
    setSelected(
      step.id === 'task'
        ? current.current.nodes.find((node) => node.type === 'agent_task')?.id || null
        : null,
    );
    setEdgeSelected(null);
    modalOrigin.current = 'canvas';
    navigate(step.page, { replace: true });
    if (step.page === 'canvas') fitTour();
    if (step.id === 'check') void runCheck(current.current);
  };
  async function exportZip() {
    setBusy('export');
    try {
      assertSafeWorkflow(wf);
      const check = await api<{ issues: Issue[] }>('validate', { workflow: wf, mode: 'mock' });
      setIssues(check.issues);
      if (check.issues.some((i) => i.severity === 'error')) {
        setModal('check');
        return;
      }
      const res = await fetch('/api/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workflow: wf }),
      });
      if (!res.ok) {
        const x = await res.json();
        throw Error(x.error || 'Export failed');
      }
      download(
        await res.blob(),
        `${wf.project.name.replace(/[^a-z0-9\u4e00-\u9fff]+/gi, '-') || 'knot'}-runner.zip`,
      );
      setModal('exported');
    } catch (e) {
      notify((e as Error).message);
    } finally {
      setBusy('');
    }
  }
  async function generate(candidate: Workflow) {
    if (activePage.current !== 'planner') return;
    const request = ++planningRequest.current;
    const isCurrentRequest = () =>
      planningRequest.current === request && activePage.current === 'planner';
    setBusy('plan');
    try {
      const value = await api<{ workflow: Workflow }>('plan', {
        project: candidate.project,
        resources: candidate.resources,
        planner,
      });
      // A request can finish after native Back or a newer generation has begun.
      if (!isCurrentRequest()) return;
      change(parseWorkflow(value.workflow));
      setIntakeProject(null);
      navigate('canvas');
      setSelected(null);
      notify('AI draft created. Review the design notes and edit any block before export.');
      fit();
    } catch (e) {
      if (!isCurrentRequest()) return;
      notify((e as Error).message);
      throw e;
    } finally {
      if (isCurrentRequest()) setBusy((value) => (value === 'plan' ? '' : value));
    }
  }
  const jsonExport = () => {
    try {
      assertSafeWorkflow(wf);
      download(
        new Blob([JSON.stringify(wf, null, 2)], { type: 'application/json' }),
        'workflow.json',
      );
      notify('Workflow JSON exported.');
    } catch (e) {
      notify((e as Error).message);
    }
  };
  const importFile = async (file?: File) => {
    if (!file) return;
    try {
      if (file.size > 5_000_000) throw Error('Workflow must be smaller than 5 MB.');
      const next = parseWorkflow(JSON.parse(await file.text()));
      change(next);
      setSelected(null);
      navigate('canvas');
      notify('Workflow imported. Run Check before exporting a runner.');
      fit();
    } catch (e) {
      notify('Import rejected: ' + (e as Error).message);
    } finally {
      if (fileInput.current) fileInput.current.value = '';
    }
  };
  const openLibrary = () => {
    setSavedProjects(readProjects());
    setModal('saved');
  };
  const projects = [
    ...(hasProject(wf) ? [wf] : []),
    ...savedProjects.filter((project) => project.project.id !== wf.project.id),
  ];
  const openProject = (project: Workflow) => {
    change(project);
    setSelected(null);
    setEdgeSelected(null);
    navigate('canvas');
    requestAnimationFrame(() => flow.setViewport(project.viewport, { duration: 250 }));
  };
  const startProject = (idea: string) => {
    if (firstVisit) dismissWelcome();
    if (hasProject(wf)) save();
    setDraft({ name: '', members: 3, goal: idea, deliverable: '' });
    setWizard(1);
  };
  const startRequirements = (idea: string) => {
    if (firstVisit) dismissWelcome();
    if (hasProject(wf)) save();
    const next = emptyWorkflow();
    next.project.goal = idea;
    setIntakeProject(next);
    setModal('planner');
  };
  const node = wf.nodes.find((n) => n.id === selected);
  const nodes: FlowNode[] = wf.nodes.map((n) => ({
    id: n.id,
    type: 'block',
    position: n.position,
    data: { block: n, workflow: wf },
    selected: n.id === selected,
  }));
  const edges: FlowEdge[] = wf.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    sourceHandle: e.source_port,
    targetHandle: e.target_port,
    type: 'smoothstep',
    selected: e.id === edgeSelected,
    hidden: e.kind === 'data' && !showData,
    label: e.source_port === 'true' ? 'True' : e.source_port === 'false' ? 'False' : undefined,
    style: {
      stroke: e.kind === 'data' ? '#99aabf' : '#80917d',
      strokeWidth: e.id === edgeSelected ? 3 : 1.7,
      strokeDasharray: e.kind === 'data' ? '5 5' : undefined,
    },
    markerEnd: {
      type: MarkerType.ArrowClosed,
      color: e.kind === 'data' ? '#99aabf' : '#80917d',
      width: 14,
      height: 14,
    },
    interactionWidth: 22,
  }));
  void historyTick;
  return (
    <div className={page === 'home' ? 'home-shell' : 'app-shell studio-shell'}>
      {page === 'home' && (
        <Home
          projects={projects}
          idea={draft.goal}
          onIdeaChange={(goal) => setDraft((value) => ({ ...value, goal }))}
          busy={!!busy}
          onStart={startProject}
          onRequirements={startRequirements}
          onExample={firstVisit ? startGuidedExample : loadTemplate}
          onProjects={openLibrary}
          onOpen={openProject}
          onHelp={() => setModal('help')}
          firstVisit={firstVisit}
          onDismissWelcome={dismissWelcome}
          focusComposer={focusHomeComposer}
        />
      )}
      {page !== 'home' && page !== 'new' && (
        <div className="editor-layout" inert={!!modal || tourStep !== null}>
          <nav className="rail" aria-label="Main navigation">
            <button className="brand-mark" title="KNOT home" onClick={() => navigate('home')}>
              <Blocks size={24} />
            </button>
            <div className="rail-middle">
              <button
                className="rail-button active"
                title="Workflow canvas"
                onClick={() => navigate('canvas')}
              >
                <LayoutGrid size={21} />
              </button>
              <button className="rail-button" title="Agents" onClick={() => setModal('agents')}>
                <Bot size={21} />
              </button>
              <button
                className="rail-button"
                title="Project settings"
                onClick={() => setModal('project')}
              >
                <Settings2 size={21} />
              </button>
              <button className="rail-button" title="Saved projects" onClick={openLibrary}>
                <FolderOpen size={21} />
              </button>
            </div>
            <button
              className="rail-button"
              title="Help & shortcuts"
              onClick={() => setModal('help')}
            >
              <HelpCircle size={21} />
            </button>
            <span className="profile-avatar">Y</span>
          </nav>
          <div className="workspace">
            <header className="app-header">
              <div className="brand-word">
                <button className="workspace-home" onClick={() => navigate('home')}>
                  <ArrowLeft size={15} /> Home
                </button>
                KNOT
              </div>
              <div className="header-right">
                <span className={`backend-status ${online ? 'online' : ''}`}>
                  <i />
                  {online ? 'Local runner ready' : 'Backend offline'}
                </span>
                <span className="header-divider" />
                <button className="text-button" onClick={() => setModal('help')}>
                  Quick guide
                  <ArrowUpRight size={14} />
                </button>
              </div>
            </header>
            <section className="project-bar">
              <div>
                <div className="breadcrumb">
                  <button onClick={openLibrary}>My projects</button>
                  <ChevronRight size={12} />
                  <span>Workflow studio</span>
                </div>
                <div className="project-name">
                  <h1>{wf.project.name}</h1>
                  <button
                    className="icon-button"
                    title="Edit project"
                    onClick={() => setModal('project')}
                  >
                    <ChevronDown size={18} />
                  </button>
                  <span className="draft-badge">DRAFT</span>
                </div>
              </div>
              <div className="project-actions">
                <div
                  className="avatar-stack"
                  onClick={() => setModal('project')}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => e.key === 'Enter' && setModal('project')}
                  aria-label="Edit team"
                >
                  {wf.project.members.slice(0, 4).map((m, i) => (
                    <span key={m.id} title={m.name} className={`avatar avatar-${i % 4}`}>
                      {m.name
                        .split(' ')
                        .map((x) => x[0])
                        .slice(0, 2)
                        .join('')}
                    </span>
                  ))}
                  <span className="team-count">{wf.project.members.length} members</span>
                </div>
                <button className="secondary" onClick={save}>
                  <Save size={15} />
                  Save
                </button>
                <button
                  className="primary"
                  data-tour="export-runner"
                  disabled={!!busy}
                  onClick={exportZip}
                >
                  {busy === 'export' ? (
                    <LoaderCircle className="spin" size={16} />
                  ) : (
                    <Download size={16} />
                  )}
                  Export runner
                  <ChevronDown size={14} />
                </button>
              </div>
            </section>
            <div className="studio">
              <aside className="library" data-tour="block-library">
                <div className="panel-head">
                  <span>Building blocks</span>
                  <span className="count-badge">7</span>
                </div>
                <div className="library-body">
                  <input
                    className="block-search"
                    aria-label="Find a block"
                    placeholder="Find a block…"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                  <div className="section-label">YOUR TOOLKIT</div>
                  <div className="palette">
                    {(Object.keys(KINDS) as NodeKind[])
                      .filter((k) => KINDS[k].name.toLowerCase().includes(search.toLowerCase()))
                      .map((k) => {
                        const meta = KINDS[k],
                          Icon = icons[k];
                        return (
                          <button
                            className="palette-item"
                            aria-label={meta.name}
                            title={meta.description}
                            key={k}
                            draggable
                            onDragStart={(e) => {
                              e.dataTransfer.setData('application/knot', k);
                              e.dataTransfer.effectAllowed = 'move';
                            }}
                            onClick={() => add(k)}
                            data-testid={`palette-${k}`}
                          >
                            <span
                              className="palette-icon"
                              style={{ color: meta.color, background: `${meta.color}14` }}
                            >
                              <Icon size={19} />
                            </span>
                            <span>
                              <strong>{meta.name}</strong>
                              <small>{meta.description}</small>
                            </span>
                            <GripVertical size={15} className="grip" />
                          </button>
                        );
                      })}
                  </div>
                </div>
                <div className="library-footer">
                  <button onClick={() => fileInput.current?.click()}>
                    <Upload size={14} />
                    Import JSON
                  </button>
                  <button onClick={jsonExport}>
                    <FileJson size={14} />
                    Export JSON
                  </button>
                </div>
              </aside>
              <main className="canvas-section">
                <div className="canvas-toolbar">
                  <div className="canvas-tabs">
                    <button className="active">
                      <MousePointer2 size={15} />
                      Canvas
                    </button>
                    <button onClick={() => setModal('agents')}>
                      <Bot size={15} />
                      Agents<span>{wf.agents.length}</span>
                    </button>
                  </div>
                  <div className="canvas-tools">
                    <button
                      className="icon-button"
                      disabled={!past.current.length}
                      onClick={undo}
                      title="Undo (Ctrl+Z)"
                    >
                      <Undo2 size={16} />
                    </button>
                    <button
                      className="icon-button"
                      disabled={!future.current.length}
                      onClick={redo}
                      title="Redo (Ctrl+Shift+Z)"
                    >
                      <Redo2 size={16} />
                    </button>
                    <span className="toolbar-divider" />
                    <button className="toolbar-button" onClick={() => setModal('planner')}>
                      <Sparkles size={15} />
                      AI designer
                    </button>
                    <button className="toolbar-button check-button" onClick={check}>
                      <CheckCircle2 size={15} />
                      Check
                    </button>
                  </div>
                </div>
                <div
                  className="flow-wrap"
                  data-testid="workflow-canvas"
                  onDragOver={(e) => {
                    e.preventDefault();
                    e.dataTransfer.dropEffect = 'move';
                  }}
                  onDrop={(e) => {
                    e.preventDefault();
                    const kind = e.dataTransfer.getData('application/knot') as NodeKind;
                    if (KINDS[kind])
                      add(kind, flow.screenToFlowPosition({ x: e.clientX, y: e.clientY }));
                  }}
                >
                  <ReactFlow
                    nodes={nodes}
                    edges={edges}
                    nodeTypes={nodeTypes}
                    onNodesChange={onNodesChange}
                    onNodeDragStart={remember}
                    onNodeClick={(_, n) => {
                      setSelected(n.id);
                      setEdgeSelected(null);
                    }}
                    onPaneClick={() => {
                      setSelected(null);
                      setEdgeSelected(null);
                    }}
                    onEdgeClick={(_, e) => {
                      setEdgeSelected(e.id);
                      setSelected(null);
                    }}
                    onConnect={connect}
                    onReconnect={(old, next) => connect(next, old.id)}
                    onMoveEnd={(_, viewport) => {
                      if (!tourSnapshot.current) setWf((w) => ({ ...w, viewport }));
                    }}
                    defaultViewport={wf.viewport}
                    snapToGrid
                    snapGrid={[16, 16]}
                    minZoom={0.2}
                    maxZoom={1.75}
                    deleteKeyCode={null}
                    connectionRadius={28}
                    proOptions={{ hideAttribution: false }}
                  >
                    <Background
                      variant={BackgroundVariant.Dots}
                      color="#c4cbbd"
                      gap={22}
                      size={1}
                    />
                    <Controls showInteractive={false} />
                    <MiniMap
                      nodeColor={(n) => KINDS[(n.data.block as Block).type].color}
                      maskColor="#f4f6f0bb"
                      pannable
                      zoomable
                    />
                  </ReactFlow>
                  {!wf.nodes.length && (
                    <div className="canvas-empty">
                      <div className="empty-blocks">
                        <span>
                          <Blocks size={32} />
                        </span>
                        <span>
                          <Plus size={24} />
                        </span>
                      </div>
                      <h2>Make room for your next big idea.</h2>
                      <p>
                        Drag your first block here, or get a head start
                        <br />
                        with an example workflow.
                      </p>
                      <button className="secondary" onClick={() => add('start')}>
                        <Plus size={16} />
                        Add a Start block
                      </button>
                      <button className="text-button" onClick={loadTemplate}>
                        Explore the example
                        <ArrowRight size={14} />
                      </button>
                    </div>
                  )}
                  {edgeSelected && (
                    <div className="edge-popover">
                      <Cable size={16} />
                      <span>
                        {wf.edges.find((e) => e.id === edgeSelected)?.kind === 'data'
                          ? 'Data access'
                          : 'Execution dependency'}
                      </span>
                      <button
                        className="icon-button danger"
                        title="Delete connection"
                        onClick={remove}
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  )}
                </div>
                <div className="canvas-status">
                  <span>
                    <Check size={13} />
                    {savedStatus}
                  </span>
                  <div>
                    <span>{wf.nodes.length} blocks</span>
                    <span>{wf.edges.length} connections</span>
                    <button
                      className={showData ? 'data-toggle active' : 'data-toggle'}
                      onClick={() => setShowData(!showData)}
                    >
                      <i />
                      Data links
                    </button>
                    <span className="execution-legend">
                      <i />
                      Execution
                    </span>
                  </div>
                </div>
              </main>
              {node && (
                <Inspector
                  node={node}
                  wf={wf}
                  onChange={(next) =>
                    change({ ...wf, nodes: wf.nodes.map((n) => (n.id === next.id ? next : n)) })
                  }
                  onClose={() => setSelected(null)}
                  onDuplicate={duplicate}
                  onDelete={remove}
                  onAgents={() => setModal('agents')}
                />
              )}
            </div>
          </div>
        </div>
      )}
      <input
        ref={fileInput}
        type="file"
        accept=".json,application/json"
        className="hidden"
        onChange={(e) => importFile(e.target.files?.[0])}
      />
      {toast && (
        <div className="toast" role="status">
          <CircleAlert size={18} />
          <span>{toast}</span>
          <button title="Dismiss notification" onClick={() => setToast('')}>
            <X size={16} />
          </button>
        </div>
      )}
      {wizard > 0 && (
        <div className="modal-backdrop">
          <section className="onboarding" role="dialog" aria-modal="true" aria-label="New project">
            <div className="setup-header">
              <button className="text-button" onClick={() => navigate('home')}>
                <ArrowLeft size={16} /> Home
              </button>
              <span className="home-brand">
                <Blocks size={20} /> KNOT
              </span>
            </div>
            <div className="onboarding-form">
              {wizard === 1 ? (
                <>
                  <span className="eyebrow">NEW PROJECT</span>
                  <h2>A few details, then you’re off.</h2>
                  <p className="muted">Give your project a name and a direction.</p>
                  <button
                    className="start-choice ai requirement-start"
                    onClick={() => {
                      const next = emptyWorkflow();
                      next.project.name = draft.name.trim() || 'Untitled project';
                      next.project.goal = draft.goal;
                      next.project.members = Array.from(
                        { length: Math.min(50, Math.max(1, draft.members || 3)) },
                        (_, i) => ({
                          id: `member_${i + 1}`,
                          name: `Member ${i < 26 ? String.fromCharCode(65 + i) : i + 1}`,
                          skills: '',
                        }),
                      );
                      setIntakeProject(next);
                      setModal('planner');
                    }}
                  >
                    <span className="choice-icon">
                      <Upload size={22} />
                    </span>
                    <span>
                      <strong>Upload project requirements</strong>
                      <small>PDF → tasks & deliverables → workflow</small>
                    </span>
                    <ArrowUpRight size={19} />
                  </button>
                  <div className="onboarding-or">OR DESCRIBE YOUR PROJECT</div>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      if (!draft.name.trim()) {
                        notify('Enter a project name.');
                        return;
                      }
                      const next = emptyWorkflow();
                      next.project = {
                        ...next.project,
                        name: draft.name.trim(),
                        goal: draft.goal,
                        deliverable: draft.deliverable,
                        members: Array.from({ length: draft.members }, (_, i) => ({
                          id: `member_${i + 1}`,
                          name: `Member ${i < 26 ? String.fromCharCode(65 + i) : i + 1}`,
                          skills: '',
                        })),
                      };
                      change(next);
                      setWizard(2);
                    }}
                  >
                    <Field label="Project name">
                      <input
                        required
                        maxLength={100}
                        placeholder="e.g. Campus mobility study"
                        value={draft.name}
                        onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                      />
                    </Field>
                    <div className="form-grid">
                      <Field label="Team size">
                        <input
                          type="number"
                          min={1}
                          max={50}
                          required
                          value={draft.members}
                          onChange={(e) => setDraft({ ...draft, members: Number(e.target.value) })}
                        />
                      </Field>
                      <Field label="Final deliverable">
                        <input
                          required
                          placeholder="e.g. Research report + CSV"
                          value={draft.deliverable}
                          onChange={(e) => setDraft({ ...draft, deliverable: e.target.value })}
                        />
                      </Field>
                    </div>
                    <Field label="What are you working on?">
                      <textarea
                        required
                        rows={3}
                        placeholder="Describe your goal, what you need to research, and what a useful result looks like…"
                        value={draft.goal}
                        onChange={(e) => setDraft({ ...draft, goal: e.target.value })}
                      />
                    </Field>
                    <p className="muted small">
                      We’ll create member placeholders. Add names, skills, and materials whenever
                      you’re ready.
                    </p>
                    <button type="submit" className="primary full">
                      Create project
                      <ArrowRight size={16} />
                    </button>
                  </form>
                </>
              ) : (
                <>
                  <button className="text-button" onClick={() => setWizard(1)}>
                    <ArrowLeft size={14} />
                    Back
                  </button>
                  <span className="eyebrow">YOUR PROJECT IS READY</span>
                  <h2>How would you like to start?</h2>
                  <p className="muted">
                    Two starting points. One canvas. Every block stays yours to change.
                  </p>
                  <button
                    className="start-choice"
                    onClick={() => {
                      setWizard(0);
                      setSelected(null);
                    }}
                  >
                    <span className="choice-icon">
                      <Blocks size={24} />
                    </span>
                    <span>
                      <strong>Start from scratch</strong>
                      <small>A blank canvas for your own workflow.</small>
                    </span>
                    <ArrowUpRight size={21} />
                  </button>
                  <button
                    className="start-choice ai"
                    onClick={() => {
                      setModal('planner');
                    }}
                  >
                    <span className="choice-icon">
                      <Sparkles size={24} />
                    </span>
                    <span>
                      <strong>Generate with AI</strong>
                      <small>A tailored draft from your planning model.</small>
                    </span>
                    <ArrowUpRight size={21} />
                  </button>
                  <div className="note">
                    Real AI generation requires a configured model and an API credential in your
                    local backend environment.
                  </div>
                  <button className="text-button centered" onClick={loadTemplate}>
                    Or open a separate three-person example
                    <ArrowRight size={15} />
                  </button>
                </>
              )}
            </div>
          </section>
        </div>
      )}
      {modal && (
        <div
          className="modal-backdrop"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget && busy !== 'plan') {
              setModal(null);
              setIntakeProject(null);
            }
          }}
        >
          <section
            className={`modal modal-${modal}`}
            role="dialog"
            aria-modal="true"
            aria-label={modal}
          >
            <div className="modal-head">
              <div>
                <span className="eyebrow">KNOT STUDIO</span>
                <h2>
                  {
                    {
                      agents: 'Meet your agents',
                      project: 'Project settings',
                      planner: 'AI workflow designer',
                      check: 'Workflow check',
                      saved: 'Your project library',
                      help: 'A guide to your canvas',
                      exported: 'Your workflow, ready to go.',
                    }[modal]
                  }
                </h2>
              </div>
              <button
                className="secondary page-back"
                title="Close dialog"
                disabled={busy === 'plan'}
                onClick={() => {
                  setModal(null);
                  setIntakeProject(null);
                }}
              >
                <ArrowLeft size={16} /> Back
              </button>
            </div>
            <div className="modal-body">
              {modal === 'agents' && (
                <AgentsSettings
                  wf={wf}
                  change={change}
                  credentials={credentials}
                  onCredentialsChange={setCredentials}
                />
              )}
              {modal === 'project' && <ProjectSettings wf={wf} change={change} />}
              {modal === 'planner' && (
                <RequirementIntake
                  wf={intakeProject || wf}
                  planner={planner}
                  setPlanner={(p) => {
                    try {
                      if (p.credential_ref && !/^[A-Z_][A-Z0-9_]*$/.test(p.credential_ref))
                        throw Error(
                          'Use an uppercase environment variable name, never an API key.',
                        );
                      assertSafeWorkflow(p);
                      plannerInitialized.current = true;
                      setPlannerReady(true);
                      setPlanner(p);
                    } catch (e) {
                      notify((e as Error).message);
                    }
                  }}
                  credentials={credentials}
                  onCredentialsChange={setCredentials}
                  busy={busy === 'plan'}
                  generate={generate}
                />
              )}
              {modal === 'check' && (
                <div className="check-content">
                  {busy === 'check' ? (
                    <div className="loading">
                      <LoaderCircle className="spin" />
                      Checking connections, configuration, and permissions…
                    </div>
                  ) : (
                    <>
                      <div
                        className={`check-summary ${issues.some((i) => i.severity === 'error') ? 'has-errors' : ''}`}
                      >
                        <CheckCircle2 size={28} />
                        <div>
                          <h3>
                            {issues.some((i) => i.severity === 'error')
                              ? 'A few things need your attention.'
                              : 'Ready for a mock run.'}
                          </h3>
                          <p>
                            {issues.filter((i) => i.severity === 'error').length} errors ·{' '}
                            {issues.filter((i) => i.severity === 'warning').length} configuration
                            notes
                          </p>
                        </div>
                      </div>
                      <p className="muted small">
                        This checks the current canvas for export. Real runs also require valid
                        model names, credentials, and all input files.
                      </p>
                      <div className="issue-list">
                        {issues.map((i, j) => (
                          <button
                            key={j}
                            className={`issue ${i.severity}`}
                            onClick={() => {
                              if (i.node_id) {
                                setSelected(i.node_id);
                                setModal(null);
                                flow.fitView({
                                  nodes: [{ id: i.node_id }],
                                  maxZoom: 1,
                                  duration: 300,
                                });
                              }
                            }}
                          >
                            <CircleAlert size={17} />
                            <span>
                              <strong>
                                {i.severity === 'error' ? 'Fix required' : 'Configuration note'}
                              </strong>
                              {i.message}
                            </span>
                            {i.node_id && <ChevronRight size={16} />}
                          </button>
                        ))}
                      </div>
                      {wf.design_notes.length > 0 && (
                        <div className="design-notes">
                          <h4>Why this workflow?</h4>
                          {wf.design_notes.map((n, i) => (
                            <p key={i}>{n}</p>
                          ))}
                        </div>
                      )}
                      <button
                        className="primary full"
                        disabled={issues.some((i) => i.severity === 'error') || !!busy}
                        onClick={exportZip}
                      >
                        <Download size={16} />
                        Export runnable ZIP
                      </button>
                    </>
                  )}
                </div>
              )}
              {modal === 'saved' && (
                <div className="saved-content">
                  <button
                    className="secondary"
                    onClick={() => {
                      startProject('');
                    }}
                  >
                    <Plus size={17} />
                    Create a new project
                  </button>
                  {projects.length ? (
                    projects.map((p) => (
                      <button
                        className="saved-project"
                        key={p.project.id}
                        onClick={() => {
                          openProject(p);
                        }}
                      >
                        <span className="project-folder">
                          <FolderOpen size={24} />
                        </span>
                        <span>
                          <strong>{p.project.name}</strong>
                          <small>
                            {p.project.members.length} members · {p.nodes.length} blocks
                          </small>
                        </span>
                        <ArrowUpRight size={18} />
                      </button>
                    ))
                  ) : (
                    <p className="empty-text">
                      Your canvas autosaves on this device. Use Save to add a named project to this
                      library.
                    </p>
                  )}
                  <button className="text-button" onClick={() => fileInput.current?.click()}>
                    <Upload size={16} />
                    Import a workflow JSON
                  </button>
                </div>
              )}
              {modal === 'help' && (
                <Suspense fallback={<p className="muted">Loading the visual guide…</p>}>
                  <QuickGuide
                    busy={!!busy}
                    onTour={startGuidedExample}
                    onHome={() => {
                      setFocusHomeComposer(true);
                      navigate('home');
                    }}
                  />
                </Suspense>
              )}
              {modal === 'exported' && (
                <div className="exported-content">
                  <div className="export-icon">
                    <Download size={30} />
                  </div>
                  <h3>Take your team’s workflow with you.</h3>
                  <p>
                    Your ZIP contains the fixed Python runner, current workflow, prompts, example
                    inputs, and setup instructions.
                  </p>
                  <ol className="export-steps">
                    <li>
                      <span>1</span>
                      <div>
                        <strong>Extract to a new folder</strong>
                        <p>Python 3.10 or newer is required.</p>
                      </div>
                    </li>
                    <li>
                      <span>2</span>
                      <div>
                        <strong>Try the mock run</strong>
                        <p>Open start.bat on Windows, or run bash start.sh on macOS/Linux.</p>
                      </div>
                    </li>
                    <li>
                      <span>3</span>
                      <div>
                        <strong>Review, then approve</strong>
                        <p>
                          The runner prints the exact command to continue. Final delivery waits for
                          your approval.
                        </p>
                      </div>
                    </li>
                  </ol>
                  <div className="note">
                    For real execution, configure model names and credentials locally, then run with
                    --mode real. See the bundled README.
                  </div>
                  <button className="primary full" onClick={() => setModal(null)}>
                    Back to canvas
                    <ArrowRight size={16} />
                  </button>
                </div>
              )}
            </div>
          </section>
        </div>
      )}
      {tourStep !== null && (
        <Suspense fallback={null}>
          <GuidedTour
            step={tourStep}
            onStep={moveTour}
            onSkip={() => endTour('skipped')}
            onFinish={() => endTour('completed')}
          />
        </Suspense>
      )}
    </div>
  );
}
