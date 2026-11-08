import { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  ControlButton,
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
import NavigationButton from './NavigationButton';
import LongWaitNotice from './LongWaitNotice';
import { HomeLogo } from './BrandLogo';
import ExportRunGuide from './ExportRunGuide';
import { TOUR_STEPS, readOnboardingStatus, rememberOnboarding } from './onboarding';
import type { OnboardingStatus } from './onboarding';
import { usePage } from './navigation';
import BlockNode, { icons } from './BlockNode';
import Inspector, { Field } from './Inspector';
import { AgentsSettings, ProjectSettings } from './Settings';
import { ownerConnectionIssues } from './owner-connections';
import RequirementIntake from './RequirementIntake';
import { KNOT_STORAGE, KNOT_LIBRARY, migrateLegacyStorage } from './storage';
import {
  PROJECT_QUERY,
  PROJECT_DRAFT_PREFIX,
  PROJECT_DELETED_PREFIX,
  deleteLibraryProject,
  findProject,
  isProjectDeleted,
  prepareProjectForTab,
  projectHref,
  readProjectLibrary,
  saveLibraryProject,
  writeCurrentProject,
} from './project-storage';
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
import { cloudConfigured, cloudDelete, cloudList, cloudSave } from './cloud';
const nodeTypes = { block: BlockNode };
const GuidedTour = lazy(() => import('./GuidedTour'));
const QuickGuide = lazy(() => import('./QuickGuide'));
const ProjectLibrary = lazy(() => import('./ProjectLibrary'));
const requestedProjectId = new URLSearchParams(window.location.search).get(PROJECT_QUERY);
const projectTab = requestedProjectId !== null;
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
    if (requestedProjectId !== null) return findProject(localStorage, requestedProjectId);
    const raw = localStorage.getItem(STORAGE);
    return raw ? findProject(localStorage, parseWorkflow(JSON.parse(raw)).project.id) : null;
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
    return readProjectLibrary(localStorage);
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
  const [execution, setExecution] = useState({
    backend: 'codex' as 'codex' | 'claude' | 'opencode',
    model: '',
  });
  const [exportDownloaded, setExportDownloaded] = useState(false);
  const plannerInitialized = useRef(plannerReady);
  const [draft, setDraft] = useState({ name: '', members: 3, goal: '', deliverable: '' });
  const [setupErrors, setSetupErrors] = useState<Partial<Record<keyof typeof draft, string>>>({});
  const updateDraft = (patch: Partial<typeof draft>) => {
    setDraft((value) => ({ ...value, ...patch }));
    setSetupErrors((errors) => {
      const next = { ...errors };
      for (const key of Object.keys(patch) as (keyof typeof draft)[]) delete next[key];
      return next;
    });
  };
  const [intakeProject, setIntakeProject] = useState<Workflow | null>(null);
  const [firstVisit, setFirstVisit] = useState(() => readOnboardingStatus() === null);
  const [tourStep, setTourStep] = useState<number | null>(null);
  const [focusHomeComposer, setFocusHomeComposer] = useState(false);
  const tourSnapshot = useRef<{ workflow: Workflow; search: string; showData: boolean } | null>(
    null,
  );
  const pendingTourProjects = useRef<Workflow[]>([]);
  const templateRequest = useRef(0);
  const validationRequest = useRef(0);
  // React Flow needs measured sizes on every controlled-node update. Keep this
  // rendering state separate from the workflow, its exports and undo history.
  const nodeMeasurements = useRef({
    projectId: wf.project.id,
    sizes: new Map<string, { width: number; height: number }>(),
  });
  if (nodeMeasurements.current.projectId !== wf.project.id) {
    nodeMeasurements.current = { projectId: wf.project.id, sizes: new Map() };
  }
  const nodeIds = new Set(wf.nodes.map((node) => node.id));
  for (const id of nodeMeasurements.current.sizes.keys()) {
    if (!nodeIds.has(id)) nodeMeasurements.current.sizes.delete(id);
  }
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
  const lastPersisted = useRef<Workflow | null>(restored);
  current.current = wf;
  const notify = useCallback((message: string) => {
    setToast(message);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(''), 6500);
  }, []);
  useEffect(() => {
    if (projectTab && !restored) {
      notify('This project is no longer available. Choose another project from your library.');
      navigate('saved', { replace: true });
    }
  }, [notify, navigate]);
  const dismissWelcome = () => {
    templateRequest.current += 1;
    setBusy((value) => (value === 'template' ? '' : value));
    rememberOnboarding('skipped');
    setFirstVisit(false);
  };
  const archiveTourProjects = useCallback(() => {
    if (!pendingTourProjects.current.length) return;
    const stored: unknown = JSON.parse(localStorage.getItem(LIBRARY) || '[]');
    if (!Array.isArray(stored)) throw new Error('Invalid project library');
    const previous = pendingTourProjects.current.filter(
      (project) => !isProjectDeleted(localStorage, project.project.id),
    );
    const ids = new Set(previous.map((project) => project.project.id));
    const next = [
      ...previous,
      ...stored
        .map(parseWorkflow)
        .filter(
          (project) =>
            !ids.has(project.project.id) && !isProjectDeleted(localStorage, project.project.id),
        ),
    ];
    localStorage.setItem(LIBRARY, JSON.stringify(next));
    pendingTourProjects.current = [];
    setSavedProjects(next);
  }, []);
  const closeTour = () => {
    const snapshot = tourSnapshot.current;
    if (snapshot) {
      // Closing the coachmark makes the example editable. Archive the original
      // before autosaving the example, so an unfinished project stays recoverable.
      if (hasProject(snapshot.workflow)) {
        pendingTourProjects.current = [
          snapshot.workflow,
          ...pendingTourProjects.current.filter(
            (project) => project.project.id !== snapshot.workflow.project.id,
          ),
        ];
      }
      past.current = [...past.current.slice(-49), snapshot.workflow];
      future.current = [];
      setHistoryTick((value) => value + 1);
      tourSnapshot.current = null;
    }
    setWf((workflow) => ({ ...workflow, viewport: flow.getViewport() }));
    rememberOnboarding('skipped');
    setFirstVisit(false);
    setTourStep(null);
  };
  const endTour = useCallback(
    (status: OnboardingStatus) => {
      const snapshot = tourSnapshot.current;
      if (snapshot) {
        let previous = snapshot.workflow;
        try {
          if (isProjectDeleted(localStorage, previous.project.id)) previous = emptyWorkflow();
        } catch {
          /* Keep the in-memory project usable when browser storage is unavailable. */
        }
        setWf(previous);
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
  const persistCurrent = useCallback(() => {
    const workflow = current.current;
    if (tourSnapshot.current || workflow === lastPersisted.current) return;
    try {
      assertSafeWorkflow(workflow);
      archiveTourProjects();
      writeCurrentProject(localStorage, workflow, !projectTab);
      lastPersisted.current = workflow;
      if (
        projectTab &&
        new URLSearchParams(window.location.search).get(PROJECT_QUERY) !== workflow.project.id
      ) {
        window.history.replaceState(
          null,
          '',
          projectHref(
            window.location.pathname,
            window.location.search,
            workflow.project.id,
            window.location.hash,
          ),
        );
      }
      setSavedStatus('Saved on this device');
    } catch {
      setSavedStatus('Not saved · storage unavailable');
    }
  }, [archiveTourProjects]);
  useEffect(() => {
    if (tourSnapshot.current) return;
    const timer = setTimeout(persistCurrent, 300);
    return () => clearTimeout(timer);
  }, [wf, tourStep, persistCurrent]);
  useEffect(() => {
    // A reload or tab close can happen before the debounced autosave runs.
    // Flush synchronously without writing the temporary guided-tour example.
    window.addEventListener('beforeunload', persistCurrent);
    window.addEventListener('pagehide', persistCurrent);
    return () => {
      window.removeEventListener('beforeunload', persistCurrent);
      window.removeEventListener('pagehide', persistCurrent);
    };
  }, [persistCurrent]);
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
      archiveTourProjects();
      const next = saveLibraryProject(localStorage, current.current);
      if (!projectTab) localStorage.setItem(STORAGE, JSON.stringify(current.current));
      lastPersisted.current = current.current;
      setSavedProjects(next);
    } catch (e) {
      notify('Could not save: ' + (e as Error).message);
      return;
    }
    if (!cloudConfigured) {
      notify('Project saved on this device. Open it anytime from your project library.');
      return;
    }
    notify('Saved on this device · syncing to cloud…');
    cloudSave(structuredClone(current.current))
      .then(() => notify('Project saved on this device and in the cloud library.'))
      .catch((e) =>
        notify('Saved on this device only. Cloud sync failed: ' + (e as Error).message),
      );
  }, [notify, archiveTourProjects]);
  const resetDeletedProject = useCallback(() => {
    setWf(emptyWorkflow());
    setSelected(null);
    setEdgeSelected(null);
    past.current = [];
    future.current = [];
    setHistoryTick((value) => value + 1);
    navigate('saved', { replace: true });
  }, [navigate]);
  useEffect(() => {
    const syncLibrary = (event: StorageEvent) => {
      if (event.storageArea !== localStorage) return;
      if (
        event.key === LIBRARY ||
        event.key === null ||
        event.key?.startsWith(PROJECT_DRAFT_PREFIX) ||
        event.key?.startsWith(PROJECT_DELETED_PREFIX)
      )
        setSavedProjects(readProjects());
      if (!event.key?.startsWith(PROJECT_DELETED_PREFIX) || event.newValue === null) return;
      const id = decodeURIComponent(event.key.slice(PROJECT_DELETED_PREFIX.length));
      past.current = past.current.filter((project) => project.project.id !== id);
      future.current = future.current.filter((project) => project.project.id !== id);
      pendingTourProjects.current = pendingTourProjects.current.filter(
        (project) => project.project.id !== id,
      );
      setHistoryTick((value) => value + 1);
      if (current.current.project.id === id) {
        if (tourSnapshot.current) endTour('skipped');
        else resetDeletedProject();
        notify('This project was deleted in another tab.');
      }
    };
    window.addEventListener('storage', syncLibrary);
    return () => window.removeEventListener('storage', syncLibrary);
  }, [notify, endTour, resetDeletedProject]);
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
    for (const update of changes) {
      if (update.type !== 'dimensions' || !update.dimensions || !nodeIds.has(update.id)) continue;
      const { width, height } = update.dimensions;
      if (Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0) {
        nodeMeasurements.current.sizes.set(update.id, { width, height });
      }
    }
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
  async function loadExample(guided: boolean, kind: 'team' | 'owner-api' = 'team') {
    const request = ++templateRequest.current;
    const source = activePage.current;
    const isCurrentRequest = () =>
      templateRequest.current === request && activePage.current === source;
    setBusy('template');
    try {
      const value = parseWorkflow(
        await api<Workflow>(kind === 'owner-api' ? 'template/owner-api' : 'template'),
      );
      if (!isCurrentRequest()) return;
      value.project.id = uid('example');
      if (guided) {
        // Keep the visitor's actual project and history untouched throughout the demo.
        tourSnapshot.current = { workflow: structuredClone(current.current), search, showData };
        setWf(value);
        setSearch('');
        setShowData(true);
        setTourStep(0);
        setToast('');
      } else change(value);
      if (kind === 'owner-api') setExecution({ backend: 'opencode', model: '' });
      navigate('canvas');
      setSelected(null);
      setEdgeSelected(null);
      if (guided) fitTour();
      else {
        notify(
          kind === 'owner-api'
            ? 'API test loaded. Open Project settings → Team members to configure Alice and Bob, then export with OpenCode.'
            : 'Example template loaded — all blocks are editable. Uses labeled sample data.',
        );
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
        mode: 'local',
        execution,
      });
      if (request !== validationRequest.current) return;
      setIssues(issues.filter((issue) => issue.code !== 'model'));
      setOnline(true);
    } catch (e) {
      if (request !== validationRequest.current) return;
      setIssues([
        ...localIssues(candidate).filter((issue) => issue.code !== 'model'),
        ...(execution.backend === 'opencode' ? ownerConnectionIssues(candidate) : []),
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
  function openExport() {
    setExportDownloaded(false);
    setModal('exported');
  }
  async function exportZip() {
    setBusy('export');
    try {
      assertSafeWorkflow(wf);
      const selection = {
        ...execution,
        model: execution.backend === 'opencode' ? '' : execution.model.trim(),
      };
      assertSafeWorkflow(selection);
      const ownerIssues = selection.backend === 'opencode' ? ownerConnectionIssues(wf) : [];
      if (ownerIssues.length) {
        setIssues(ownerIssues);
        setModal('check');
        return;
      }
      const check = await api<{ issues: Issue[] }>('validate', {
        workflow: wf,
        mode: 'local',
        execution: selection,
      });
      setIssues(check.issues.filter((issue) => issue.code !== 'model'));
      if (check.issues.some((i) => i.severity === 'error')) {
        setModal('check');
        return;
      }
      const res = await fetch('/api/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workflow: wf, execution: selection }),
      });
      if (!res.ok) {
        const x = await res.json();
        throw Error(x.error || 'Export failed');
      }
      download(
        await res.blob(),
        `${wf.project.name.replace(/[^a-z0-9\u4e00-\u9fff]+/gi, '-') || 'knot'}-runner.zip`,
      );
      setExecution(selection);
      setExportDownloaded(true);
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
      if (isProjectDeleted(localStorage, next.project.id)) next.project.id = uid('project');
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
    const local = readProjects();
    setSavedProjects(local);
    setModal('saved');
    if (cloudConfigured)
      cloudList()
        .then((rows) => {
          const cloud: Workflow[] = [];
          for (const r of rows) {
            try {
              const w = parseWorkflow(r);
              // A project deleted on this device stays deleted even if its cloud copy lingers.
              if (!isProjectDeleted(localStorage, w.project.id)) cloud.push(w);
            } catch {
              /* skip rows that no longer parse */
            }
          }
          const ids = new Set(cloud.map((w) => w.project.id));
          setSavedProjects([...cloud, ...local.filter((w) => !ids.has(w.project.id))]);
        })
        .catch((e) => notify('Cloud library unavailable: ' + (e as Error).message));
  };
  const projects = [
    ...(hasProject(wf) ? [wf] : []),
    ...savedProjects.filter((project) => project.project.id !== wf.project.id),
  ];
  const openProject = (project: Workflow) => {
    if (isProjectDeleted(localStorage, project.project.id)) {
      openLibrary();
      notify('This project was deleted. Choose another project from your library.');
      return;
    }
    change(project);
    setSelected(null);
    setEdgeSelected(null);
    navigate('canvas');
    requestAnimationFrame(() => flow.setViewport(project.viewport, { duration: 250 }));
  };
  const prepareProjectTab = (project: Workflow) => {
    try {
      archiveTourProjects();
      const hasLocalChanges =
        project.project.id === current.current.project.id &&
        JSON.stringify(current.current) !== JSON.stringify(lastPersisted.current);
      setSavedProjects(prepareProjectForTab(localStorage, project, hasLocalChanges));
      return true;
    } catch {
      notify('Could not open this project. Please try again.');
      return false;
    }
  };
  const deleteProject = (project: Workflow) => {
    try {
      setSavedProjects(deleteLibraryProject(localStorage, project.project.id));
      pendingTourProjects.current = pendingTourProjects.current.filter(
        (pending) => pending.project.id !== project.project.id,
      );
      past.current = past.current.filter((previous) => previous.project.id !== project.project.id);
      future.current = future.current.filter(
        (previous) => previous.project.id !== project.project.id,
      );
      setHistoryTick((value) => value + 1);
      if (current.current.project.id === project.project.id) resetDeletedProject();
      notify('Project deleted.');
      if (cloudConfigured)
        cloudDelete(project.project.id).catch((e) =>
          notify('Deleted on this device. Cloud copy not removed: ' + (e as Error).message),
        );
      return true;
    } catch {
      return false;
    }
  };
  const startProject = (idea: string) => {
    if (firstVisit) dismissWelcome();
    if (hasProject(wf)) save();
    setDraft({ name: '', members: 3, goal: idea, deliverable: '' });
    setSetupErrors({});
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
    measured: nodeMeasurements.current.sizes.get(n.id),
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
      stroke: e.kind === 'data' ? '#99aabf' : '#7183b4',
      strokeWidth: e.id === edgeSelected ? 3 : 1.7,
      strokeDasharray: e.kind === 'data' ? '5 5' : undefined,
    },
    markerEnd: {
      type: MarkerType.ArrowClosed,
      color: e.kind === 'data' ? '#99aabf' : '#7183b4',
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
          onOwnerExample={() => void loadExample(false, 'owner-api')}
          onProjects={openLibrary}
          onOpen={openProject}
          onHelp={() => setModal('help')}
          firstVisit={firstVisit}
          onDismissWelcome={dismissWelcome}
          focusComposer={focusHomeComposer}
        />
      )}
      {page !== 'home' && page !== 'new' && (
        <div
          className="editor-layout"
          inert={tourStep !== null}
          aria-hidden={tourStep !== null || undefined}
        >
          <header className="app-header">
            <HomeLogo onHome={() => navigate('home')} />
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
          <nav className="rail" aria-label="Main navigation">
            <div className="rail-middle">
              <NavigationButton
                label="Workflow canvas"
                description="Build and connect workflow blocks."
                active={!modal || ['planner', 'check', 'exported'].includes(modal)}
                onClick={() => navigate('canvas')}
              >
                <LayoutGrid size={21} />
              </NavigationButton>
              <NavigationButton
                label="Agents"
                description="Configure your AI team and model connections."
                active={modal === 'agents'}
                onClick={() => setModal('agents')}
              >
                <Bot size={21} />
              </NavigationButton>
              <NavigationButton
                label="Project settings"
                description="Manage the project, people and resources."
                active={modal === 'project'}
                onClick={() => setModal('project')}
              >
                <Settings2 size={21} />
              </NavigationButton>
              <NavigationButton
                label="Saved projects"
                description="Browse and open your saved projects."
                active={modal === 'saved'}
                onClick={openLibrary}
              >
                <FolderOpen size={21} />
              </NavigationButton>
            </div>
            <NavigationButton
              label="Help & shortcuts"
              description="Explore the guide and keyboard shortcuts."
              active={modal === 'help'}
              onClick={() => setModal('help')}
            >
              <HelpCircle size={21} />
            </NavigationButton>
            <span className="profile-avatar">Y</span>
          </nav>
          <div className="workspace">
            <div
              className={`canvas-workspace ${modal ? 'is-inactive' : ''}`}
              inert={!!modal}
              aria-hidden={!!modal || undefined}
            >
              <section className="project-bar">
                <div>
                  <div className="project-name">
                    <h1>{wf.project.name}</h1>
                    <button
                      className="icon-button"
                      title="Edit project"
                      onClick={() => setModal('project')}
                    >
                      <ChevronDown size={18} />
                    </button>
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
                    onClick={openExport}
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
                        color="#bdc0cb"
                        gap={22}
                        size={1}
                      />
                      <Controls showInteractive={false}>
                        <ControlButton
                          className="canvas-read-size"
                          title="Read at 100%"
                          aria-label="Read at 100%"
                          onClick={() => void flow.zoomTo(1, { duration: 250 })}
                        >
                          100%
                        </ControlButton>
                      </Controls>
                      <MiniMap
                        nodeColor={(n) => KINDS[(n.data.block as Block).type].color}
                        maskColor="#f0f1f6bb"
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
                    onMembers={() => setModal('project')}
                    credentials={credentials}
                  />
                )}
              </div>
            </div>
            {modal && (
              <section
                className={`workspace-panel panel-${modal}`}
                role="region"
                aria-label={modal}
              >
                <div className="page-title-bar panel-heading">
                  <h2>
                    {
                      {
                        agents: 'Meet your agents',
                        project: 'Project settings',
                        planner: 'AI workflow designer',
                        check: 'Workflow check',
                        saved: 'Your project library',
                        help: 'A guide to your canvas',
                        exported: exportDownloaded
                          ? 'Your workspace is ready.'
                          : 'Export your agent workspace',
                      }[modal]
                    }
                  </h2>
                  <button
                    className="secondary page-back"
                    title="Return to the previous view"
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
                  {modal === 'project' && (
                    <ProjectSettings
                      wf={wf}
                      change={change}
                      credentials={credentials}
                      onCredentialsChange={setCredentials}
                    />
                  )}
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
                                  : 'Ready to export your workspace.'}
                              </h3>
                              <p>
                                {issues.filter((i) => i.severity === 'error').length} errors ·{' '}
                                {issues.filter((i) => i.severity === 'warning').length}{' '}
                                configuration notes
                              </p>
                            </div>
                          </div>
                          <p className="muted small">
                            This checks task connections and inputs. Choose Codex or Claude at
                            export; the local launcher checks your installed assistant before
                            running.
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
                            onClick={openExport}
                          >
                            <Download size={16} />
                            Export runnable ZIP
                          </button>
                        </>
                      )}
                    </div>
                  )}
                  {modal === 'saved' && (
                    <Suspense fallback={<p className="muted">Loading your projects…</p>}>
                      <ProjectLibrary
                        projects={projects}
                        onCreate={() => startProject('')}
                        onImport={() => fileInput.current?.click()}
                        onPrepareOpen={prepareProjectTab}
                        onDelete={deleteProject}
                      />
                    </Suspense>
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
                      {exportDownloaded ? (
                        <>
                          <h3>Your agents have their assignments.</h3>
                          <p>
                            {execution.backend === 'opencode'
                              ? "OpenCode will run each task with its owner's model and API key"
                              : `Every role will use ${execution.backend === 'codex' ? 'Codex' : 'Claude'}${execution.model ? ` with ${execution.model}` : ' with its default model'}`}
                            . Tasks follow the connections and review gates on your canvas.
                          </p>
                        </>
                      ) : (
                        <form
                          className="workspace-export-form"
                          onSubmit={(event) => {
                            event.preventDefault();
                            void exportZip();
                          }}
                        >
                          <h3>
                            {execution.backend === 'opencode'
                              ? 'Your team. Their own models.'
                              : 'One choice. Every agent.'}
                          </h3>
                          <p>
                            {execution.backend === 'opencode'
                              ? "Run your team on one computer. Each task follows its owner's model connection; independent tasks can run together."
                              : 'Your agents share a coding assistant, each with its own assignment and working copy. Independent tasks can run together.'}
                          </p>
                          <div className="field">
                            <label htmlFor="export-backend">Run with</label>
                            <select
                              id="export-backend"
                              value={execution.backend}
                              onChange={(event) =>
                                setExecution({
                                  backend: event.target.value as 'codex' | 'claude' | 'opencode',
                                  model: '',
                                })
                              }
                            >
                              <option value="codex">Codex</option>
                              <option value="claude">Claude</option>
                              <option value="opencode">OpenCode · each owner's API</option>
                            </select>
                          </div>
                          {execution.backend !== 'opencode' ? (
                            <div className="field">
                              <label htmlFor="export-model">Shared model (optional)</label>
                              <input
                                id="export-model"
                                value={execution.model}
                                placeholder="Use your coding assistant’s default"
                                autoComplete="off"
                                maxLength={128}
                                onChange={(event) =>
                                  setExecution((value) => ({ ...value, model: event.target.value }))
                                }
                              />
                            </div>
                          ) : (
                            <div className="export-owner-connections">
                              <ul aria-label="Task owner connections">
                                {wf.project.members
                                  .filter((member) =>
                                    wf.nodes.some(
                                      (node) =>
                                        node.type === 'agent_task' &&
                                        node.config.owner_id === member.id,
                                    ),
                                  )
                                  .map((member) => (
                                    <li key={member.id}>
                                      <strong>{member.name}</strong>
                                      <span>
                                        {member.connection?.model || 'Model connection required'}
                                      </span>
                                    </li>
                                  ))}
                              </ul>
                              <button
                                type="button"
                                className="text-button"
                                onClick={() => setModal('project')}
                              >
                                Configure team connections ↗
                              </button>
                            </div>
                          )}
                          <div className="note">
                            {execution.backend === 'opencode'
                              ? 'Requires Python 3.10+ and OpenCode on the execution computer. Add each member’s API key in the extracted package before running. No API keys are included in the ZIP.'
                              : 'Requires Python 3.10+ and the selected coding CLI installed and signed in on your computer. Your account supplies model access. No API keys are included in the ZIP.'}
                          </div>
                          <button className="primary full" type="submit" disabled={!!busy}>
                            {busy === 'export' ? (
                              <LoaderCircle className="spin" size={17} />
                            ) : (
                              <Download size={17} />
                            )}
                            Download agent workspace
                          </button>
                        </form>
                      )}
                      <ExportRunGuide backend={execution.backend} />
                      {exportDownloaded && (
                        <button className="primary full" onClick={() => setModal(null)}>
                          Back to canvas
                          <ArrowRight size={16} />
                        </button>
                      )}
                    </div>
                  )}
                </div>
              </section>
            )}
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
              <HomeLogo onHome={() => navigate('home')} />
            </div>
            <div className="page-title-bar">
              <h2>{wizard === 1 ? 'Create a project' : 'How would you like to start?'}</h2>
            </div>
            <div className="onboarding-form">
              {wizard === 1 ? (
                <>
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
                    </span>
                    <ArrowUpRight size={19} />
                  </button>
                  <div className="onboarding-or">OR DESCRIBE YOUR PROJECT</div>
                  <form
                    noValidate
                    onSubmit={(e) => {
                      e.preventDefault();
                      const errors: typeof setupErrors = {};
                      if (!draft.name.trim()) errors.name = 'Please enter a project name.';
                      if (
                        !Number.isInteger(draft.members) ||
                        draft.members < 1 ||
                        draft.members > 50
                      )
                        errors.members = 'Team size must be a whole number from 1 to 50.';
                      if (!draft.deliverable.trim())
                        errors.deliverable = 'Please enter a final deliverable.';
                      if (!draft.goal.trim())
                        errors.goal = 'Please describe what you are working on.';
                      setSetupErrors(errors);
                      const firstError = Object.keys(errors)[0];
                      if (firstError) {
                        e.currentTarget
                          .querySelector<HTMLElement>(`[name="${firstError}"]`)
                          ?.focus();
                        return;
                      }
                      const next = emptyWorkflow();
                      next.project = {
                        ...next.project,
                        name: draft.name.trim(),
                        goal: draft.goal.trim(),
                        deliverable: draft.deliverable.trim(),
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
                    <Field label="Project name" error={setupErrors.name}>
                      <input
                        name="name"
                        required
                        maxLength={100}
                        placeholder="e.g. Campus mobility study"
                        value={draft.name}
                        onChange={(e) => updateDraft({ name: e.target.value })}
                      />
                    </Field>
                    <div className="form-grid">
                      <Field label="Team size" error={setupErrors.members}>
                        <input
                          name="members"
                          type="number"
                          min={1}
                          max={50}
                          required
                          value={draft.members}
                          onChange={(e) => updateDraft({ members: Number(e.target.value) })}
                        />
                      </Field>
                      <Field label="Final deliverable" error={setupErrors.deliverable}>
                        <input
                          name="deliverable"
                          required
                          placeholder="e.g. Research report + CSV"
                          value={draft.deliverable}
                          onChange={(e) => updateDraft({ deliverable: e.target.value })}
                        />
                      </Field>
                    </div>
                    <Field label="What are you working on?" error={setupErrors.goal}>
                      <textarea
                        name="goal"
                        required
                        rows={3}
                        placeholder="Describe your goal, what you need to research, and what a useful result looks like…"
                        value={draft.goal}
                        onChange={(e) => updateDraft({ goal: e.target.value })}
                      />
                    </Field>
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
      {!!busy && (
        <LongWaitNotice
          key={busy}
          activity={
            {
              plan: 'Your model is designing the workflow.',
              check: 'Checking your workflow.',
              export: 'Preparing your download.',
              template: 'Loading the example.',
            }[busy] || 'Processing your request.'
          }
        />
      )}
      {tourStep !== null && (
        <Suspense fallback={null}>
          <GuidedTour
            step={tourStep}
            onStep={moveTour}
            onHome={() => endTour('skipped')}
            onClose={closeTour}
            onFinish={() => endTour('completed')}
          />
        </Suspense>
      )}
    </div>
  );
}
