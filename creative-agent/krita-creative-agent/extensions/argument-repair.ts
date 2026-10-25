// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Argument repair for tool calls whose JSON did not parse (src/argument-repair.ts repairJsonText). Pi keeps such a call
// with empty arguments and the text it received in argumentsError, and refuses it at validation; in the artist's chats
// of 2026-10-23/24, 15 big paint_batch calls (deepseek) were lost to one brace too many or too few. When the assistant
// message ends, before any of its calls runs, a call whose brackets can be put right gets its arguments back; the
// repair is recorded, and the painter is told once in that call's result. A shipped Pi extension registered inline
// (src/runtime.mjs); it knows the host only through `record`.
import type { ExtensionAPI, MessageEndEvent, MessageEndEventResult, ToolResultEvent, ToolResultEventResult } from '@earendil-works/pi-coding-agent';
import { repairJsonText, RECEIVED } from '../src/argument-repair.ts';

export type RepairRecord = { type: 'argument_repair'; tool: string; call_id: string; repairs: string[] };
type ToolCall = { type: 'toolCall'; id: string; name: string; arguments: unknown; argumentsError?: string };

export const TOLD = 'Your arguments for this call were malformed JSON (a brace or bracket too many or too few); the host repaired them and ran the call. Check the result, and keep each batch small enough to write exactly.';

export default function argumentRepair({ record = () => {} }: { record?: (event: RepairRecord) => void } = {}): (pi: ExtensionAPI) => void {
  return pi => {
    const repaired = new Map<string, string[]>();
    pi.on('message_end', async (event: MessageEndEvent): Promise<MessageEndEventResult | undefined> => {
      const message = event.message as { role: string; content?: unknown };
      if (message.role !== 'assistant' || !Array.isArray(message.content)) return undefined;
      let changed = false;
      const content = message.content.map((part: unknown) => {
        const call = part as ToolCall;
        if (call?.type !== 'toolCall' || typeof call.argumentsError !== 'string') return part;
        const at = call.argumentsError.indexOf(RECEIVED);
        const notes: string[] = [];
        const fixed = at < 0 ? null : repairJsonText(call.argumentsError.slice(at + RECEIVED.length), 16, notes);
        if (!fixed) return part;
        changed = true;
        repaired.set(call.id, notes);
        record({ type: 'argument_repair', tool: call.name, call_id: call.id, repairs: ['malformed JSON repaired: ' + call.argumentsError.slice(0, Math.max(0, at)).trim().slice(0, 200), ...notes] });
        const { argumentsError: _dropped, ...rest } = call;
        return { ...rest, arguments: fixed };
      });
      return changed ? { message: { ...event.message, content } as MessageEndEvent['message'] } : undefined;
    });
    pi.on('tool_result', async (event: ToolResultEvent): Promise<ToolResultEventResult | undefined> => {
      const notes = repaired.get(event.toolCallId);
      if (!notes) return undefined;
      repaired.delete(event.toolCallId);
      const dropped = notes.length ? ` Your arguments were cut short: ${notes.join('; ')}: send it again in the next call.` : '';
      return { content: [...event.content, { type: 'text', text: JSON.stringify({ host_repaired: TOLD + dropped }) }] };
    });
  };
}
