import { useCallback, useEffect, useState } from 'react';

const routes = {
  home: '',
  canvas: '/workspace',
  new: '/new',
  saved: '/projects',
  project: '/workspace/project',
  agents: '/workspace/agents',
  planner: '/workspace/designer',
  check: '/workspace/check',
  exported: '/workspace/export',
  help: '/guide',
} as const;

export type Page = keyof typeof routes;

function currentPage(): Page {
  const path = window.location.hash.slice(1).replace(/\/$/, '');
  return (Object.keys(routes) as Page[]).find((page) => routes[page] === path) || 'home';
}

export function usePage() {
  const [page, setPage] = useState<Page>(currentPage);

  useEffect(() => {
    const sync = () => setPage(currentPage());
    window.addEventListener('popstate', sync);
    window.addEventListener('hashchange', sync);
    return () => {
      window.removeEventListener('popstate', sync);
      window.removeEventListener('hashchange', sync);
    };
  }, []);

  const navigate = useCallback((next: Page) => {
    const target = `${window.location.pathname}${window.location.search}${routes[next] ? `#${routes[next]}` : ''}`;
    if (currentPage() !== next) window.history.pushState(null, '', target);
    setPage(next);
  }, []);

  return [page, navigate] as const;
}
