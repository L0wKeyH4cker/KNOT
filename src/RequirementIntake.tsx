import { useRef, useState } from 'react';
import {
  Upload,
  FileText,
  ArrowRight,
  Sparkles,
  LoaderCircle,
  Trash2,
  Plus,
  CircleAlert,
} from 'lucide-react';
import { Field } from './Inspector';
import LongWaitNotice from './LongWaitNotice';
import { PlannerSettings } from './Settings';
import type { Planner } from './Settings';
import { api } from './model';
import type { Workflow } from './model';
import { withRequirements } from './requirements';
import type { RequirementAnalysis, RequirementDocument } from './requirements';

type Props = {
  wf: Workflow;
  planner: Planner;
  setPlanner: (p: Planner) => void;
  credentials: Record<string, boolean>;
  onCredentialsChange: (credentials: Record<string, boolean>) => void;
  busy: boolean;
  generate: (candidate: Workflow) => Promise<void>;
};

async function encodeFile(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = '';
  for (let i = 0; i < bytes.length; i += 8192)
    binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
  return btoa(binary);
}

export default function RequirementIntake({
  wf,
  planner,
  setPlanner,
  credentials,
  onCredentialsChange,
  busy,
  generate,
}: Props) {
  const [document, setDocument] = useState<RequirementDocument | null>(null);
  const [analysis, setAnalysis] = useState<RequirementAnalysis | null>(null);
  const [phase, setPhase] = useState<'idle' | 'extract' | 'analyze'>('idle');
  const [error, setError] = useState('');
  const [dragging, setDragging] = useState(false);
  const [goal, setGoal] = useState(wf.project.goal);
  const [deliverable, setDeliverable] = useState(wf.project.deliverable);
  const input = useRef<HTMLInputElement>(null);
  const locked = phase !== 'idle' || busy;
  const configured = !!planner.model.trim() && !!planner.credential_ref.trim();

  async function upload(file?: File) {
    if (!file || locked) return;
    setError('');
    try {
      if (file.size > 5 * 1024 * 1024) throw Error('Choose a document smaller than 5 MiB.');
      if (!/\.(pdf|txt|md)$/i.test(file.name))
        throw Error('Choose a PDF, TXT, or Markdown document.');
      setPhase('extract');
      const result = await api<{ document: RequirementDocument }>('requirements/extract', {
        filename: file.name,
        content_base64: await encodeFile(file),
      });
      setDocument(result.document);
      setAnalysis(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPhase('idle');
      if (input.current) input.current.value = '';
    }
  }
  async function analyze() {
    if (!document || locked) return;
    setError('');
    setPhase('analyze');
    setAnalysis(null);
    try {
      const result = await api<{ analysis: RequirementAnalysis }>('requirements/analyze', {
        document,
        planner,
      });
      setAnalysis(result.analysis);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPhase('idle');
    }
  }
  async function build(fromDocument: boolean) {
    setError('');
    try {
      const candidate =
        fromDocument && document && analysis
          ? withRequirements(wf, document, analysis)
          : { ...wf, project: { ...wf.project, goal, deliverable } };
      await generate(candidate);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  const updateTask = (index: number, patch: Partial<RequirementAnalysis['tasks'][number]>) => {
    if (analysis)
      setAnalysis({
        ...analysis,
        tasks: analysis.tasks.map((t, i) => (i === index ? { ...t, ...patch } : t)),
      });
  };
  const listField = (
    label: string,
    key: 'deliverables' | 'constraints' | 'missing_information',
    hint?: string,
  ) =>
    analysis && (
      <Field label={label} hint={hint}>
        <textarea
          rows={3}
          value={analysis[key].join('\n')}
          disabled={locked}
          onChange={(e) => setAnalysis({ ...analysis, [key]: e.target.value.split('\n') })}
        />
      </Field>
    );
  return (
    <div className="requirements-designer">
      {phase !== 'idle' && (
        <LongWaitNotice
          key={phase}
          activity={
            phase === 'extract'
              ? 'Reading your document.'
              : 'Your model is analyzing the requirements.'
          }
        />
      )}
      <div className="requirements-intro">
        <h3>Turn requirements into a workflow</h3>
      </div>
      <ol className="intake-steps" aria-label="Requirement workflow steps">
        <li className={!document ? 'active' : 'done'}>
          <span>1</span> Upload & read
        </li>
        <li className={document && !analysis ? 'active' : analysis ? 'done' : ''}>
          <span>2</span> Review tasks
        </li>
        <li className={analysis ? 'active' : ''}>
          <span>3</span> Generate workflow
        </li>
      </ol>
      <input
        ref={input}
        type="file"
        accept=".pdf,.txt,.md"
        className="hidden"
        data-testid="requirements-file-input"
        aria-label="Requirement document file"
        disabled={locked}
        onChange={(e) => void upload(e.target.files?.[0])}
      />
      <button
        type="button"
        className={`requirement-dropzone ${dragging ? 'dragging' : ''}`}
        disabled={locked}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          void upload(e.dataTransfer.files[0]);
        }}
        onClick={() => input.current?.click()}
      >
        <span className="upload-icon">
          {phase === 'extract' ? (
            <LoaderCircle className="spin" size={24} />
          ) : document ? (
            <FileText size={24} />
          ) : (
            <Upload size={24} />
          )}
        </span>
        <strong>
          {phase === 'extract'
            ? 'Reading your document…'
            : document
              ? document.filename
              : 'Upload project requirements'}
        </strong>
        <span>
          {document
            ? `${document.page_count} page(s) · Click to replace`
            : 'Drop a file here or click to browse'}
        </span>
        <small>PDF, TXT, or Markdown · up to 5 MiB · PDF up to 40 pages</small>
      </button>
      {error && (
        <div className="requirement-error" role="alert">
          <CircleAlert size={18} />
          <span>{error}</span>
        </div>
      )}
      {document && (
        <div className="requirement-document">
          <button
            className="text-button"
            disabled={locked}
            onClick={() => {
              setDocument(null);
              setAnalysis(null);
              setError('');
            }}
          >
            <Trash2 size={14} /> Remove document
          </button>
          {document.warnings.map((warning, i) => (
            <div key={i} className="note">
              {warning}
            </div>
          ))}
          <Field
            label="Extracted requirement text"
            hint="Editing this text clears the analysis; analyze again to update the tasks."
          >
            <textarea
              className="document-preview"
              rows={7}
              maxLength={60000}
              value={document.text}
              disabled={locked}
              onChange={(e) => {
                setDocument({ ...document, text: e.target.value });
                setAnalysis(null);
              }}
            />
          </Field>
          <button
            className="secondary full"
            disabled={locked || !configured || !document.text.trim()}
            onClick={() => void analyze()}
          >
            {phase === 'analyze' ? (
              <LoaderCircle size={17} className="spin" />
            ) : (
              <Sparkles size={17} />
            )}
            {phase === 'analyze' ? 'Finding tasks and deliverables…' : 'Analyze requirements'}
          </button>
          <p className="muted">
            Extraction stays local. Analysis sends this text to your planning model.
          </p>
        </div>
      )}
      {analysis && (
        <div className="requirement-analysis" data-testid="requirements-analysis">
          <div className="section-label">
            REVIEW THE WORK <span>{analysis.tasks.length} tasks</span>
          </div>
          <Field label="Suggested project name">
            <input
              value={analysis.project_name}
              disabled={locked}
              onChange={(e) => setAnalysis({ ...analysis, project_name: e.target.value })}
            />
          </Field>
          <Field label="Extracted project goal">
            <textarea
              rows={3}
              value={analysis.goal}
              disabled={locked}
              onChange={(e) => setAnalysis({ ...analysis, goal: e.target.value })}
            />
          </Field>
          {listField('Required deliverables', 'deliverables', 'One deliverable per line.')}
          {analysis.tasks.map((task, i) => (
            <article className="requirement-task" key={i}>
              <div className="requirement-task-head">
                <span>TASK {String(i + 1).padStart(2, '0')}</span>
                <small>
                  {task.source_pages.length
                    ? `Source: page ${task.source_pages.join(', ')}`
                    : 'Source: document or your edits'}
                </small>
                <button
                  className="icon-button"
                  title={`Remove task ${i + 1}`}
                  disabled={locked}
                  onClick={() =>
                    setAnalysis({ ...analysis, tasks: analysis.tasks.filter((_, j) => j !== i) })
                  }
                >
                  <Trash2 size={15} />
                </button>
              </div>
              <Field label={`Task ${i + 1} title`}>
                <input
                  value={task.title}
                  disabled={locked}
                  onChange={(e) => updateTask(i, { title: e.target.value })}
                />
              </Field>
              <Field label={`Task ${i + 1} description`}>
                <textarea
                  rows={2}
                  value={task.description}
                  disabled={locked}
                  onChange={(e) => updateTask(i, { description: e.target.value })}
                />
              </Field>
              <Field label={`Task ${i + 1} acceptance criteria`}>
                <textarea
                  rows={2}
                  value={task.acceptance}
                  disabled={locked}
                  onChange={(e) => updateTask(i, { acceptance: e.target.value })}
                />
              </Field>
            </article>
          ))}
          <button
            className="text-button"
            disabled={locked || analysis.tasks.length >= 12}
            onClick={() =>
              setAnalysis({
                ...analysis,
                tasks: [
                  ...analysis.tasks,
                  { title: '', description: '', acceptance: '', source_pages: [] },
                ],
              })
            }
          >
            <Plus size={15} /> Add task
          </button>
          {listField('Project constraints', 'constraints', 'One constraint per line.')}
          {listField('Missing information', 'missing_information')}
        </div>
      )}
      {!document && (
        <div className="requirement-manual">
          <div className="section-label">OR WRITE YOUR BRIEF</div>
          <Field label="Project goal">
            <textarea
              rows={3}
              value={goal}
              disabled={locked}
              placeholder="What should the team accomplish?"
              onChange={(e) => setGoal(e.target.value)}
            />
          </Field>
          <Field label="Expected deliverables">
            <input
              value={deliverable}
              disabled={locked}
              placeholder="e.g. Research report and comparison CSV"
              onChange={(e) => setDeliverable(e.target.value)}
            />
          </Field>
        </div>
      )}
      <div className="requirement-model">
        <div className="section-label">PLANNING MODEL</div>
        <fieldset disabled={locked} className="requirement-model-fields">
          <PlannerSettings
            planner={planner}
            setPlanner={setPlanner}
            credentials={credentials}
            onCredentialsChange={onCredentialsChange}
            busy={locked}
            generate={() => void build(false)}
            hasNodes={!!wf.nodes.length}
            configurationOnly
          />
        </fieldset>
      </div>
      {document && !configured && (
        <p className="note">Choose your planning model above to analyze this document.</p>
      )}
      {(analysis || !document) && (
        <div className="requirement-actions">
          {!!wf.nodes.length && (
            <p className="muted">
              Generating replaces this canvas. Undo restores the previous version.
            </p>
          )}
          <button
            className="primary full"
            disabled={locked || !configured || (!analysis && (!goal.trim() || !deliverable.trim()))}
            onClick={() => void build(!!analysis)}
          >
            {busy ? (
              <>
                <LoaderCircle size={17} className="spin" /> Designing your workflow…
              </>
            ) : (
              <>
                {analysis ? 'Generate workflow from requirements' : 'Generate with AI'}{' '}
                <ArrowRight size={17} />
              </>
            )}
          </button>
        </div>
      )}
    </div>
  );
}
