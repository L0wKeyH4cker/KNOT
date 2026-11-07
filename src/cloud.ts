// Optional Supabase cloud library. Each browser signs in anonymously; row-level security
// limits every row in public.workflows to its owner. Without configuration, or if sign-in
// fails, the app keeps working with device-only storage and says so.
import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import type { Workflow } from './model';

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string | undefined;
const client: SupabaseClient | null = url && key ? createClient(url, key) : null;

export const cloudConfigured = client !== null;

let ready: Promise<string> | null = null;
function session(): Promise<string> {
  if (!client) return Promise.reject(new Error('Cloud sync is not configured.'));
  ready ??= (async () => {
    const { data } = await client.auth.getSession();
    if (data.session) return data.session.user.id;
    const { data: signed, error } = await client.auth.signInAnonymously();
    if (error || !signed.user) throw new Error(error?.message || 'Anonymous sign-in failed.');
    return signed.user.id;
  })().catch((e) => {
    ready = null;
    throw e;
  });
  return ready;
}

export async function cloudSave(wf: Workflow): Promise<void> {
  await session();
  const { error } = await client!.from('workflows').upsert(
    {
      project_id: wf.project.id,
      name: wf.project.name ?? '',
      workflow: wf,
      updated_at: new Date().toISOString(),
    },
    { onConflict: 'owner,project_id' },
  );
  if (error) throw new Error(error.message);
}

export async function cloudList(): Promise<unknown[]> {
  await session();
  const { data, error } = await client!
    .from('workflows')
    .select('workflow')
    .order('updated_at', { ascending: false })
    .limit(50);
  if (error) throw new Error(error.message);
  return (data ?? []).map((r) => r.workflow);
}

export async function cloudDelete(projectId: string): Promise<void> {
  await session();
  const { error } = await client!.from('workflows').delete().eq('project_id', projectId);
  if (error) throw new Error(error.message);
}
