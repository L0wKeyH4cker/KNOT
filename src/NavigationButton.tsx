import { useId, useState } from 'react';
import type { ReactNode } from 'react';

export default function NavigationButton({
  label,
  description,
  active,
  onClick,
  children,
}: {
  label: string;
  description: string;
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  return (
    <div
      className="rail-item"
      onPointerEnter={() => setOpen(true)}
      onPointerLeave={() => setOpen(false)}
    >
      <button
        className={`rail-button ${active ? 'active' : ''}`}
        aria-label={label}
        aria-current={active ? 'page' : undefined}
        aria-describedby={open ? id : undefined}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && open) {
            event.stopPropagation();
            setOpen(false);
          }
        }}
        onClick={() => {
          setOpen(false);
          onClick();
        }}
      >
        {children}
      </button>
      {open && (
        <span className="rail-tooltip" id={id} role="tooltip">
          <strong>{label}</strong>
          <span>{description}</span>
        </span>
      )}
    </div>
  );
}
