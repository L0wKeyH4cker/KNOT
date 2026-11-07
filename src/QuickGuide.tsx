import { useEffect, useId, useRef, useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronDown,
  Home,
  Maximize2,
  MousePointer2,
  X,
} from 'lucide-react';
import { TOUR_COPY } from './tour-copy';
import './quick-guide.css';

const steps = [
  {
    id: 'canvas',
    label: 'The canvas',
    image: 'canvas',
    alt: 'The Campus, reimagined example on the workflow canvas, from Start to Output.',
    caption: 'One shared view of your team’s work.',
    tips: [
      'Follow the example from left to right: inputs, parallel research, a combined report, and human review.',
      'Drag the background to pan. Use the zoom controls or Fit View to see the whole workflow.',
    ],
  },
  {
    id: 'blocks',
    label: 'Building blocks',
    image: 'blocks',
    alt: 'The building block library with Start, Agent Task, Shared Resource, Parallel, Condition, Human Review, and Output.',
    caption: 'Pick a block for the job you need.',
    tips: [
      'Drag a block from the left-hand library onto the canvas, or click to add one.',
      'Use Human Review before Output when a teammate should approve the final result.',
    ],
  },
  {
    id: 'connections',
    label: 'Connections',
    image: 'connections',
    alt: 'Two parallel tasks joined by solid execution connections and dashed data connections.',
    caption: 'Set the order. Share the right results.',
    tips: [
      'Connect side ports to set execution order. Connect top and bottom data ports to share results.',
      'A report task can wait for both research branches. A data connection grants access to that upstream result.',
    ],
  },
  {
    id: 'task',
    label: 'Task settings',
    image: 'task',
    alt: 'The Understand the people task with its assigned agent, human owner, instructions, and acceptance criteria.',
    caption: 'A clear brief makes a useful task.',
    tips: [
      'Select a block to choose its agent and human owner, then write task instructions and acceptance criteria.',
      'Choose an output format. Enable only the tools and file paths that this task needs.',
    ],
  },
  {
    id: 'agents',
    label: 'Your AI team',
    image: 'agents',
    alt: 'The agent settings page showing Research partner, an English system prompt, and model connection settings.',
    caption: 'Different roles. One team.',
    tips: [
      'Give each agent a role and system prompt, then choose its provider and API model ID.',
      'Save a key on this computer and test the connection when you are ready. Keys stay out of exported workflows.',
    ],
  },
  {
    id: 'project',
    label: 'People & inputs',
    image: 'project',
    alt: 'Project settings with the campus travel goal, deliverable, three team members, and example interview resources.',
    caption: 'Keep the context close to the work.',
    tips: [
      'Set the project goal and final deliverable, then add your teammates and their skills.',
      'Add text or CSV resources here and connect a Shared Resource block to the tasks that need them.',
    ],
  },
  {
    id: 'planner',
    label: 'AI designer',
    image: 'planner',
    alt: 'The AI workflow designer with a requirements upload area and a project brief.',
    caption: 'Start with a brief, then make it yours.',
    tips: [
      'Upload project requirements or describe your goal. Select and configure a planning model.',
      'Review the proposed tasks before generating the workflow. Every block stays editable on the canvas.',
    ],
  },
  {
    id: 'check',
    label: 'Workflow check',
    image: 'check',
    alt: 'Workflow check results showing that the example can run in mock mode and needs model configuration for real mode.',
    caption: 'Know what is ready and what needs attention.',
    tips: [
      'Use Check to review connections, task configuration, and permissions before exporting.',
      'The example works in mock mode straight away. Real mode also needs model IDs and local credentials.',
    ],
  },
  {
    id: 'export',
    label: 'Export & run',
    image: 'export',
    alt: 'The export confirmation with instructions to extract the runner, try mock mode, and configure real models.',
    caption: 'Your workflow, ready for its next chapter.',
    tips: [
      'Export runner downloads a ZIP with your workflow, Python runner, prompts, inputs, and setup instructions.',
      'Extract it to a new folder and follow the included launch instructions. Human Review pauses delivery until the assigned person approves.',
    ],
  },
] as const;

export default function QuickGuide({
  busy,
  onTour,
  onHome,
}: {
  busy: boolean;
  onTour: () => void;
  onHome: () => void;
}) {
  const [index, setIndex] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const card = useRef<HTMLElement>(null);
  const navigation = useRef<HTMLElement>(null);
  const zoom = useRef<HTMLDialogElement>(null);
  const previousIndex = useRef(index);
  const headingId = useId();
  const step = steps[index];
  const copy = TOUR_COPY[step.id];
  const finalStep = index === steps.length - 1;
  const image = `./guide/${step.image}.jpg`;

  useEffect(() => {
    if (previousIndex.current === index) return;
    previousIndex.current = index;
    if (window.matchMedia('(max-width: 1050px)').matches) {
      card.current?.scrollIntoView({ block: 'start', behavior: 'instant' });
    }
    const nav = navigation.current;
    const active = nav?.querySelector('[aria-current="step"]');
    if (nav && active) {
      const bounds = nav.getBoundingClientRect();
      const item = active.getBoundingClientRect();
      if (item.left < bounds.left || item.right > bounds.right) {
        nav.scrollBy({ left: item.left - bounds.left - 8, behavior: 'instant' });
      }
    }
    heading.current?.focus({ preventScroll: true });
  }, [index]);

  return (
    <div className="quick-guide" data-testid="quick-guide">
      <div className="guide-intro">
        <div>
          <span className="guide-eyebrow">SEE IT. TRY IT. MAKE IT YOURS.</span>
          <p>A visual walkthrough, one small step at a time.</p>
        </div>
        <button className="secondary guide-tour-button" disabled={busy} onClick={onTour}>
          <MousePointer2 size={15} aria-hidden="true" /> Take a guided tour
          <ArrowRight size={15} aria-hidden="true" />
        </button>
      </div>

      <div className="guide-layout">
        <nav ref={navigation} className="guide-steps" aria-label="Quick guide steps">
          <ol>
            {steps.map((item, itemIndex) => (
              <li key={item.id}>
                <button
                  className={`guide-step-link ${itemIndex === index ? 'active' : ''}`}
                  aria-current={itemIndex === index ? 'step' : undefined}
                  onClick={() => setIndex(itemIndex)}
                >
                  <span className="guide-step-number" aria-hidden="true">
                    {String(itemIndex + 1).padStart(2, '0')}
                  </span>
                  {item.label}
                </button>
              </li>
            ))}
          </ol>
        </nav>

        <section ref={card} className="guide-card" aria-labelledby={headingId}>
          <div className="guide-card-top">
            <span className="guide-eyebrow" role="status">
              STEP {String(index + 1).padStart(2, '0')} OF {String(steps.length).padStart(2, '0')}
            </span>
            <span className="guide-example-label">Campus, reimagined · Example</span>
          </div>
          <div className="guide-stage">
            <figure className={`guide-figure guide-figure-${step.id}`}>
              <button
                className="guide-screenshot"
                aria-label={`Enlarge screenshot: ${step.label}`}
                onClick={() => zoom.current?.showModal()}
              >
                <img src={image} alt={step.alt} decoding="async" />
                <span className="guide-enlarge" aria-hidden="true">
                  <Maximize2 size={13} /> Enlarge
                </span>
              </button>
              <figcaption>{step.caption}</figcaption>
            </figure>
            <div className="guide-copy" key={step.id}>
              <span className="guide-chapter">{step.label}</span>
              <h3 ref={heading} id={headingId} tabIndex={-1}>
                {copy.title}
              </h3>
              <p>{copy.description}</p>
              <ul>
                {step.tips.map((tip) => (
                  <li key={tip}>
                    <Check size={15} aria-hidden="true" />
                    <span>{tip}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
          <div className="guide-controls">
            <button
              className="secondary"
              disabled={index === 0}
              onClick={() => setIndex((value) => Math.max(0, value - 1))}
            >
              <ArrowLeft size={15} aria-hidden="true" /> Previous
            </button>
            <span className="guide-progress" aria-hidden="true">
              {steps.map((item, itemIndex) => (
                <span key={item.id} className={itemIndex <= index ? 'filled' : ''} />
              ))}
            </span>
            <button
              className="primary"
              onClick={
                finalStep
                  ? onHome
                  : () => setIndex((value) => Math.min(steps.length - 1, value + 1))
              }
            >
              {finalStep ? 'Try my own project' : 'Next'}
              {finalStep ? (
                <Home size={15} aria-hidden="true" />
              ) : (
                <ArrowRight size={15} aria-hidden="true" />
              )}
            </button>
          </div>
        </section>
      </div>

      <details className="guide-reference">
        <summary>
          Keyboard shortcuts & run modes <ChevronDown size={15} aria-hidden="true" />
        </summary>
        <div className="guide-reference-body">
          <div>
            <h3>A few handy shortcuts</h3>
            <dl className="guide-shortcuts">
              <dt>Undo / Redo</dt>
              <dd>
                <kbd>Ctrl / ⌘ Z</kbd> / <kbd>Shift Z</kbd>
              </dd>
              <dt>Duplicate a block</dt>
              <dd>
                <kbd>Ctrl / ⌘ D</kbd>
              </dd>
              <dt>Delete a selection</dt>
              <dd>
                <kbd>Delete</kbd>
              </dd>
              <dt>Save project</dt>
              <dd>
                <kbd>Ctrl / ⌘ S</kbd>
              </dd>
            </dl>
          </div>
          <div>
            <h3>Choose how you run</h3>
            <p>
              <strong>Mock</strong> uses fixed, labeled example results without API calls.
            </p>
            <p>
              <strong>Real</strong> uses your configured models and local credentials. A failed API
              call never switches to mock output.
            </p>
          </div>
        </div>
      </details>

      <dialog
        className="guide-image-dialog"
        ref={zoom}
        aria-label={`${step.label} screenshot`}
        onKeyDown={(event) => event.stopPropagation()}
      >
        <div className="guide-image-dialog-head">
          <strong>{step.label}</strong>
          <button className="secondary" onClick={() => zoom.current?.close()}>
            <X size={16} aria-hidden="true" /> Close screenshot
          </button>
        </div>
        <div className="guide-image-scroll">
          <img src={image} alt={step.alt} />
        </div>
        <p>{step.caption}</p>
      </dialog>
    </div>
  );
}
