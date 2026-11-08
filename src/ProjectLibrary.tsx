import { useEffect, useId, useRef, useState } from 'react';
import { FolderOpen, Plus, Trash2, Upload } from 'lucide-react';
import type { Workflow } from './model';
import { projectHref } from './project-storage';
import './project-library.css';

function DeleteConfirmation({
  project,
  onCancel,
  onDelete,
}: {
  project: Workflow;
  onCancel: () => void;
  onDelete: () => boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const title = useId();
  const description = useId();
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    cancel.current?.focus();
    return () => element?.close();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="delete-project-dialog"
      role="alertdialog"
      aria-labelledby={title}
      aria-describedby={description}
      onKeyDown={(event) => event.stopPropagation()}
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
    >
      <span className="delete-project-symbol">
        <Trash2 size={22} aria-hidden="true" />
      </span>
      <h3 id={title}>Delete this project?</h3>
      <p id={description}>
        <strong>{project.project.name}</strong>, its saved workflow, and its cost ledger will be
        removed from this browser. Export any cost records you need first. This cannot be undone.
      </p>
      {failed && (
        <p className="delete-project-error" role="alert">
          Could not delete the project. Please try again.
        </p>
      )}
      <div className="delete-project-actions">
        <button ref={cancel} className="secondary" onClick={onCancel}>
          Cancel
        </button>
        <button
          className="delete-project-confirm"
          onClick={() => {
            if (onDelete()) onCancel();
            else setFailed(true);
          }}
        >
          <Trash2 size={15} aria-hidden="true" /> Delete project
        </button>
      </div>
    </dialog>
  );
}

export default function ProjectLibrary({
  projects,
  onCreate,
  onImport,
  onPrepareOpen,
  onDelete,
}: {
  projects: Workflow[];
  onCreate: () => void;
  onImport: () => void;
  onPrepareOpen: (project: Workflow) => boolean;
  onDelete: (project: Workflow) => boolean;
}) {
  const [pending, setPending] = useState<Workflow | null>(null);
  return (
    <div className="saved-content" data-testid="project-library">
      <button className="secondary" onClick={onCreate}>
        <Plus size={17} aria-hidden="true" /> Create a new project
      </button>
      {projects.length ? (
        projects.map((project) => (
          <div className="saved-project" key={project.project.id}>
            <a
              className="saved-project-open"
              href={projectHref(
                window.location.pathname,
                window.location.search,
                project.project.id,
              )}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`Open ${project.project.name} in a new tab`}
              onClick={(event) => {
                if (!onPrepareOpen(project)) event.preventDefault();
              }}
              onAuxClick={(event) => {
                if (event.button === 1 && !onPrepareOpen(project)) event.preventDefault();
              }}
            >
              <span className="project-folder">
                <FolderOpen size={24} aria-hidden="true" />
              </span>
              <span className="saved-project-info">
                <strong>{project.project.name}</strong>
                <small>{project.nodes.length} blocks</small>
              </span>
            </a>
            <button
              className="saved-project-delete"
              title="Delete project"
              aria-label={`Delete ${project.project.name}`}
              onClick={() => setPending(project)}
            >
              <Trash2 size={18} aria-hidden="true" />
            </button>
          </div>
        ))
      ) : (
        <p className="empty-text">
          No saved projects yet. Create a project or import a workflow to get started.
        </p>
      )}
      <button className="text-button" onClick={onImport}>
        <Upload size={16} aria-hidden="true" /> Import a workflow JSON
      </button>
      {pending && (
        <DeleteConfirmation
          project={pending}
          onCancel={() => setPending(null)}
          onDelete={() => onDelete(pending)}
        />
      )}
    </div>
  );
}
