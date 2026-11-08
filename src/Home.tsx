import {
  ArrowRight,
  ArrowUp,
  ArrowUpRight,
  Blocks,
  ChevronRight,
  FolderOpen,
  Github,
  HelpCircle,
  Paperclip,
} from 'lucide-react';
import type { Workflow } from './model';
import { useEffect, useRef } from 'react';
import BrandLogo, { HomeLogo } from './BrandLogo';

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
  const motionLogo = useRef<HTMLObjectElement>(null);
  const composerHovered = useRef(false);

  function syncComposerHover(hovered = composerHovered.current) {
    composerHovered.current = hovered;
    motionLogo.current?.contentDocument?.documentElement.dispatchEvent(
      new CustomEvent('knot:composer-hover', { detail: hovered }),
    );
  }

  useEffect(() => {
    if (focusComposer) composer.current?.focus();
  }, [focusComposer]);
  return (
    <div className="home-page" data-testid="home-page">
      <header className="home-header">
        <HomeLogo />
        <button className="home-projects" onClick={onProjects}>
          <FolderOpen size={16} />
          My projects
        </button>
      </header>

      <main className="home-main">
        <div className="home-intro">
          <div className="home-symbol">
            <object
              ref={motionLogo}
              className="home-motion-logo"
              data="/brand/KNOT-motion.svg"
              type="image/svg+xml"
              width="458"
              height="128"
              aria-label="KNOT interactive logo"
              onLoad={() => syncComposerHover()}
            >
              <BrandLogo />
            </object>
          </div>
          <h1>
            Your idea. <span>A team in motion.</span>
          </h1>
        </div>

        <form
          className="idea-composer"
          onPointerEnter={(event) => {
            if (event.pointerType !== 'touch') syncComposerHover(true);
          }}
          onPointerLeave={(event) => {
            if (event.pointerType !== 'touch') syncComposerHover(false);
          }}
          onSubmit={(event) => {
            event.preventDefault();
            onStart(idea.trim());
          }}
        >
          <textarea
            ref={composer}
            aria-label="Describe your project"
            placeholder="Describe what you want your team to do…"
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
              <h2>Recent projects</h2>
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
                <ArrowRight size={15} />
              </button>
            ))}
          </section>
        )}
      </main>

      <footer className="home-footer">
        <a
          className="home-github"
          href="https://github.com/L0wKeyH4cker/KNOT"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="View KNOT on GitHub (opens in a new tab)"
        >
          <Github size={18} aria-hidden="true" />
          GitHub
          <ArrowUpRight size={16} aria-hidden="true" />
        </a>
        <button className="home-guide" onClick={onHelp}>
          <HelpCircle size={22} aria-hidden="true" />
          A quick guide <ArrowRight size={20} aria-hidden="true" />
        </button>
      </footer>
    </div>
  );
}
