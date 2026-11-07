import { ArrowRight, ArrowUp, Blocks, ChevronRight, FolderOpen, Paperclip } from 'lucide-react';
import type { Workflow } from './model';
import { useEffect, useRef } from 'react';

type Props = {
  projects: Workflow[];
  idea: string;
  onIdeaChange: (idea: string) => void;
  busy: boolean;
  onStart: (idea: string) => void;
  onRequirements: (idea: string) => void;
  onExample: () => void;
  onProjects: () => void;
  onOpen: (project: Workflow) => void;
  onHelp: () => void;
  firstVisit: boolean;
  onDismissWelcome: () => void;
  focusComposer: boolean;
};

export default function Home({
  projects,
  idea,
  onIdeaChange,
  busy,
  onStart,
  onRequirements,
  onExample,
  onProjects,
  onOpen,
  onHelp,
  firstVisit,
  onDismissWelcome,
  focusComposer,
}: Props) {
  const composer = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (focusComposer) composer.current?.focus();
  }, [focusComposer]);
  return (
    <div className="home-page" data-testid="home-page">
      <header className="home-header">
        <a className="home-brand" href="#" aria-label="KNOT home">
          <span className="home-brand-mark">
            <Blocks size={21} />
          </span>
          KNOT
        </a>
        <button className="home-projects" onClick={onProjects}>
          <FolderOpen size={16} />
          My projects
        </button>
      </header>

      <main className="home-main">
        <div className="home-intro">
          <div className="home-symbol" aria-hidden="true">
            <span className="symbol-tile tile-one" />
            <span className="symbol-tile tile-two" />
            <span className="symbol-tile tile-three" />
            <span className="symbol-tile tile-four" />
          </div>
          <h1>
            Your idea. <span>A team in motion.</span>
          </h1>
          <p>What would you like to work on together?</p>
        </div>

        <form
          className="idea-composer"
          onSubmit={(event) => {
            event.preventDefault();
            onStart(idea.trim());
          }}
        >
          <textarea
            ref={composer}
            aria-label="Describe your project"
            placeholder="A research project, a big question, your next idea…"
            value={idea}
            maxLength={10000}
            rows={3}
            onChange={(event) => onIdeaChange(event.target.value)}
            onKeyDown={(event) => {
              if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
                event.preventDefault();
                onStart(idea.trim());
              }
            }}
          />
          <div className="composer-actions">
            <button
              type="button"
              className="attach-requirements"
              onClick={() => onRequirements(idea.trim())}
              aria-label="Upload project requirements"
            >
              <Paperclip size={16} />
              Add requirements
            </button>
            <button
              className="composer-submit"
              type="submit"
              aria-label="Continue to project setup"
            >
              <span>Continue</span>
              <ArrowUp size={18} />
            </button>
          </div>
        </form>

        <div className={`example-entry ${firstVisit ? 'first-visit' : ''}`}>
          <button
            className={`home-example ${firstVisit ? 'example-highlight' : ''}`}
            aria-describedby={firstVisit ? 'example-welcome' : undefined}
            aria-label="Try the three-person example template"
            disabled={busy}
            onClick={onExample}
          >
            {firstVisit && <span className="example-start-badge">START HERE</span>}
            {firstVisit ? 'Explore an example' : 'Or explore an example'} <ArrowRight size={14} />
          </button>
          {firstVisit && (
            <p className="example-welcome" id="example-welcome">
              New here? See how it works, step by step.
              <button onClick={onDismissWelcome} aria-label="Skip introduction">
                Skip
              </button>
            </p>
          )}
        </div>

        {projects.length > 0 && (
          <section className="home-recent" aria-label="Recent projects">
            <div className="recent-heading">
              <h2>Pick up where you left off</h2>
              <button onClick={onProjects}>
                View all <ChevronRight size={13} />
              </button>
            </div>
            {projects.slice(0, 1).map((project) => (
              <button
                className="recent-project"
                key={project.project.id}
                onClick={() => onOpen(project)}
              >
                <span className="recent-icon">
                  <Blocks size={17} />
                </span>
                <span className="recent-name">{project.project.name}</span>
                <span className="recent-meta">{project.project.members.length} members</span>
                <ArrowRight size={15} />
              </button>
            ))}
          </section>
        )}
      </main>

      <footer className="home-footer">
        <span>A little structure. A lot of possibility.</span>
        <button onClick={onHelp}>
          A quick guide <ArrowRight size={13} />
        </button>
      </footer>
    </div>
  );
}
