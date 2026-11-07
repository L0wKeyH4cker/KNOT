import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowLeft, ArrowRight, Check, Home, X } from 'lucide-react';
import { TOUR_STEPS } from './onboarding';
import { TOUR_COPY } from './tour-copy';

type Rect = { left: number; top: number; width: number; height: number };
type Layout = { anchor: Rect | null; width: number; height: number; cardHeight: number };
const margin = 16;
const gap = 18;
const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(value, max));

export default function GuidedTour({
  step,
  onStep,
  onHome,
  onClose,
  onFinish,
}: {
  step: number;
  onStep: (step: number) => void;
  onHome: () => void;
  onClose: () => void;
  onFinish: () => void;
}) {
  const current = TOUR_STEPS[step];
  const copy = TOUR_COPY[current.id];
  const complete = step === TOUR_STEPS.length - 1;
  const card = useRef<HTMLElement>(null);
  const next = useRef<HTMLButtonElement>(null);
  const maskId = useId().replace(/:/g, '');
  const titleId = useId();
  const descriptionId = useId();
  const [layout, setLayout] = useState<Layout>({
    anchor: null,
    width: window.innerWidth,
    height: window.innerHeight,
    cardHeight: 280,
  });

  useLayoutEffect(() => {
    let frame = 0;
    let scrolled = false;
    let observed: Element | null = null;
    const resize = new ResizeObserver(() => schedule());
    function measure() {
      const width = window.innerWidth;
      const height = window.innerHeight;
      const element = current.target ? document.querySelector(current.target) : null;
      if (element && element !== observed) {
        if (observed) resize.unobserve(observed);
        resize.observe(element);
        observed = element;
      }
      if (element && !scrolled) {
        element.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'instant' });
        scrolled = true;
      }
      const rect = element?.getBoundingClientRect();
      let anchor: Rect | null = null;
      if (rect && rect.width > 0 && rect.height > 0) {
        const left = clamp(rect.left - 7, 6, width - 6);
        const top = clamp(rect.top - 7, 6, height - 6);
        anchor = {
          left,
          top,
          width: Math.max(0, Math.min(rect.right + 7, width - 6) - left),
          height: Math.max(0, Math.min(rect.bottom + 7, height - 6) - top),
        };
      }
      const value = {
        anchor,
        width,
        height,
        cardHeight: card.current?.getBoundingClientRect().height || 280,
      };
      setLayout((previous) =>
        JSON.stringify(previous) === JSON.stringify(value) ? previous : value,
      );
    }
    function schedule() {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    }
    const root = document.getElementById('root');
    const mutations = new MutationObserver(schedule);
    if (root) mutations.observe(root, { childList: true, subtree: true });
    if (card.current) resize.observe(card.current);
    window.addEventListener('resize', schedule);
    window.addEventListener('scroll', schedule, true);
    measure();
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      mutations.disconnect();
      window.removeEventListener('resize', schedule);
      window.removeEventListener('scroll', schedule, true);
    };
  }, [current]);

  useEffect(() => {
    const root = document.getElementById('root');
    const wasInert = root?.inert || false;
    const overflow = document.body.style.overflow;
    if (root) root.inert = true;
    document.body.style.overflow = 'hidden';
    return () => {
      if (root) root.inert = wasInert;
      document.body.style.overflow = overflow;
    };
  }, []);

  const targetReady = !current.target || !!layout.anchor;
  useEffect(() => {
    if (targetReady) next.current?.focus({ preventScroll: true });
  }, [step, targetReady]);

  useEffect(() => {
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        onClose();
      } else if (event.key === 'Tab') {
        const controls = Array.from(
          card.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') || [],
        );
        const first = controls[0],
          last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        }
        if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    window.addEventListener('keydown', keyboard, true);
    return () => window.removeEventListener('keydown', keyboard, true);
  }, [onClose]);

  const width = Math.min(420, layout.width - margin * 2);
  let left = (layout.width - width) / 2;
  let top = (layout.height - layout.cardHeight) / 2;
  const anchor = layout.anchor;
  if (anchor) {
    if (layout.width < 700) {
      left = (layout.width - width) / 2;
      top = layout.height - layout.cardHeight - margin;
    } else if (layout.width - anchor.left - anchor.width >= width + gap + margin) {
      left = anchor.left + anchor.width + gap;
      top = anchor.top;
    } else if (anchor.left >= width + gap + margin) {
      left = anchor.left - width - gap;
      top = anchor.top;
    } else if (layout.height - anchor.top - anchor.height >= layout.cardHeight + gap + margin) {
      left = anchor.left + (anchor.width - width) / 2;
      top = anchor.top + anchor.height + gap;
    } else if (anchor.top >= layout.cardHeight + gap + margin) {
      left = anchor.left + (anchor.width - width) / 2;
      top = anchor.top - layout.cardHeight - gap;
    } else {
      left = layout.width - width - margin;
      top = layout.height - layout.cardHeight - margin;
    }
  }
  left = clamp(left, margin, layout.width - width - margin);
  top = clamp(top, margin, Math.max(margin, layout.height - layout.cardHeight - margin));

  return createPortal(
    <div className="guided-tour" data-testid="guided-tour">
      <svg className="tour-shade" width="100%" height="100%" aria-hidden="true">
        <defs>
          <mask
            id={maskId}
            maskUnits="userSpaceOnUse"
            x="0"
            y="0"
            width={layout.width}
            height={layout.height}
          >
            <rect width="100%" height="100%" fill="white" />
            {anchor && (
              <rect
                width={anchor.width}
                height={anchor.height}
                x={anchor.left}
                y={anchor.top}
                rx="12"
                fill="black"
              />
            )}
          </mask>
        </defs>
        <rect
          width="100%"
          height="100%"
          fill="#202741"
          fillOpacity="0.52"
          mask={`url(#${maskId})`}
        />
      </svg>
      {anchor && <div className="tour-spotlight" style={anchor} aria-hidden="true" />}
      <section
        ref={card}
        className={`tour-card ${complete ? 'tour-complete' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        style={{ left, top, width }}
      >
        <div className="tour-card-top">
          <span className="tour-step-label">
            {complete ? 'Tour complete' : `Step ${step + 1} of ${TOUR_STEPS.length - 1}`}
          </span>
          <button className="tour-close" aria-label="Close tour" onClick={onClose}>
            <X size={16} />
          </button>
        </div>
        {complete && (
          <span className="tour-done-icon">
            <Check size={25} />
          </span>
        )}
        <h2 id={titleId}>{copy.title}</h2>
        <p id={descriptionId}>{copy.description}</p>
        <div
          className="tour-progress"
          aria-label={complete ? 'Tour complete' : `Step ${step + 1} of ${TOUR_STEPS.length - 1}`}
        >
          {TOUR_STEPS.slice(0, -1).map((item, index) => (
            <span key={item.id} className={index <= step ? 'active' : ''} />
          ))}
        </div>
        <div className="tour-card-actions">
          <button className="tour-previous" disabled={step === 0} onClick={() => onStep(step - 1)}>
            <ArrowLeft size={14} /> Previous
          </button>
          <button
            ref={next}
            className="primary tour-next"
            disabled={!!current.target && !anchor}
            onClick={complete ? onFinish : () => onStep(step + 1)}
          >
            {complete ? (
              <>
                <Home size={15} /> Back to home
              </>
            ) : (
              <>
                Next <ArrowRight size={15} />
              </>
            )}
          </button>
          {!complete && (
            <button className="tour-home" onClick={onHome}>
              Back to home
            </button>
          )}
        </div>
      </section>
    </div>,
    document.body,
  );
}
