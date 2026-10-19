// Opening Krita for an agent (scripts/krita-launch.ts, the krita-launch skill): start Krita only when it is not
// running, wait until the Creative Agent plugin's bridge answers, then report the loaded build and the open
// documents. It never opens or closes a painting and never restarts a running Krita.

export type LaunchDeps = {
  running: () => Promise<boolean>;
  start: () => Promise<void>;
  health: () => Promise<any>;
  context: () => Promise<any>;
  sleep: (ms: number) => Promise<void>;
  now?: () => number;
  timeoutMs?: number;
  intervalMs?: number;
};
export type Document = { name: string; filename: string | null; modified: boolean };
export type LaunchResult =
  | { status: 'ready'; started: boolean; build: string | null; krita_version: string | null; session_active: boolean;
      krita_actions: number; documents: Document[] }
  | { status: 'no_bridge'; started: boolean; message: string };

export async function launchKrita({ running, start, health, context, sleep, now = Date.now, timeoutMs = 180000, intervalMs = 3000 }: LaunchDeps): Promise<LaunchResult> {
  const started = !(await running());
  if (started) await start();
  const deadline = now() + timeoutMs;
  let status: any = null;
  while (!status) {
    try {
      status = await health();
    } catch {
      if (now() >= deadline) {
        return { status: 'no_bridge', started, message: 'Krita is ' + (started ? 'starting' : 'running') +
          ' but the Creative Agent plugin’s bridge does not answer: check the plugin is enabled (Settings → Python Plugin Manager), or wait for a large painting to finish loading.' };
      }
      await sleep(intervalMs);
    }
  }
  const open = await context().catch(() => ({ documents: [] }));
  const documents: Document[] = (open.documents ?? []).map((d: any) => ({ name: String(d.name ?? ''), filename: d.filename ?? null, modified: !!d.modified }));
  return { status: 'ready', started, build: status.build?.build_id ?? null, krita_version: status.krita_version ?? null,
    session_active: !!status.session_active, krita_actions: Number(status.krita_actions ?? 0), documents };
}
