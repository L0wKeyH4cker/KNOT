import type { Page } from './navigation';

export const ONBOARDING_KEY = 'knot.onboarding.v1';
export type OnboardingStatus = 'completed' | 'skipped';
type TourStorage = Pick<Storage, 'getItem' | 'setItem'>;

export function readOnboardingStatus(storage?: TourStorage): OnboardingStatus | null {
  try {
    const value = JSON.parse((storage || window.localStorage).getItem(ONBOARDING_KEY) || 'null');
    return value?.version === 1 && ['completed', 'skipped'].includes(value.status)
      ? value.status
      : null;
  } catch {
    return null;
  }
}

export function rememberOnboarding(status: OnboardingStatus, storage?: TourStorage) {
  try {
    (storage || window.localStorage).setItem(
      ONBOARDING_KEY,
      JSON.stringify({ version: 1, status }),
    );
  } catch {
    /* The tour still works when browser storage is unavailable. */
  }
}

export type TourStep = { id: string; page: Page; target: string | null };

export const TOUR_STEPS: TourStep[] = [
  {
    id: 'canvas',
    page: 'canvas',
    target: '[data-testid="workflow-canvas"]',
  },
  {
    id: 'blocks',
    page: 'canvas',
    target: '[data-tour="block-library"]',
  },
  {
    id: 'connections',
    page: 'canvas',
    target: '[data-testid="workflow-canvas"]',
  },
  {
    id: 'task',
    page: 'canvas',
    target: '.inspector',
  },
  {
    id: 'agents',
    page: 'agents',
    target: '.agent-editor',
  },
  {
    id: 'project',
    page: 'project',
    target: '.project-settings',
  },
  {
    id: 'planner',
    page: 'planner',
    target: '.requirement-dropzone',
  },
  {
    id: 'check',
    page: 'check',
    target: '.check-summary',
  },
  {
    id: 'export',
    page: 'canvas',
    target: '[data-tour="export-runner"]',
  },
  {
    id: 'complete',
    page: 'canvas',
    target: null,
  },
];
