// Save timing: saves the painting while the model thinks. A full .kra save holds Krita for seconds (5-6.5 s on merged
// New Moscow, 26% of all time in runs 5-8 when the plugin saved every 8 actions), and between painting calls Krita
// sits idle while the model writes the next one. After a painting call that left unsaved work, this asks the studio to
// checkpoint without waiting for it, so the save runs during the model's turn; the plugin's command queue makes the
// next call wait only for what is left of it. The plugin still saves on its own every CHECKPOINT_SECONDS as a backstop.
// With the native helper the plugin's saves run in the background (save_job: running): one just started counts as a
// save, since asking for another would only wait for it; the work after its copy is saved after the next quiet time.
// It runs after Luna review (registered later), so it saves each batch's final state, after any undo.
// A shipped Pi extension registered inline (src/extensions.mjs). It knows the studio only through SaveHost.
import type { ExtensionAPI, ToolResultEvent } from '@earendil-works/pi-coding-agent';

/** What the studio provides (studio.mjs saveHost). */
export interface SaveHost {
  painting(toolName: string): boolean;   // the paced painting tools
  checkpoint(): Promise<unknown>;        // save the painting now (studio.flushCheckpoint)
}
/** Unsaved work older than this is saved at the next painting call; a save during the model's turn costs nothing. */
export const QUIET_SAVE_MS = 30_000;

type Details = { checkpoint?: string; checkpoint_deferred?: boolean; unsaved_operations?: number; weight?: { level?: string } | null;
  save_job?: { job: number; state: 'running' | 'done' | 'failed' } };

export default function saveTiming(host: SaveHost, { now = Date.now }: { now?: () => number } = {}): (pi: ExtensionAPI) => void {
  return pi => {
    let lastSave = now();
    let saving: Promise<unknown> | null = null;
    pi.on('tool_result', async (event: ToolResultEvent) => {
      const toolName = (event as { toolName: string }).toolName;
      if (event.isError || !host.painting(toolName)) return undefined;
      const details = ((event as { details?: unknown }).details ?? {}) as Details;
      if (details.checkpoint && !details.checkpoint_deferred) { lastSave = now(); return undefined; }   // it saved inline
      if (details.save_job?.state === 'running') { lastSave = now(); return undefined; }   // it is saving in the background
      if (!details.checkpoint_deferred || !(details.unsaved_operations! > 0) || saving) return undefined;
      const heavy = !!details.weight?.level && details.weight.level !== 'ok';   // crash risk: keep the file current
      if (!heavy && now() - lastSave < QUIET_SAVE_MS) return undefined;
      saving = host.checkpoint().catch(() => {}).finally(() => { saving = null; lastSave = now(); });
      return undefined;                                   // never awaited: the model starts its turn now
    });
  };
}
