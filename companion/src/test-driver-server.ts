// The test driver's local socket (scripts/test-driver.ts): one test chat at a time behind a few routes, which the
// MCP's creative_test_* tools call (krita-creative-agent/test_driver_client.py). The socket is private to the user.
import { createServer, type IncomingMessage, type Server } from 'node:http';
import { chmod, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { methodsOf, type Call, type Canvas } from './tool-choice.ts';
import type { StartOptions, TestState } from './test-companion.ts';

/** What the driver needs from a test companion (src/test-companion.ts). */
export type Driven = {
  start(options: StartOptions): Promise<{ copy: string | null; krita: string }>;
  prompt(text: string): void;
  move(action: 'keep' | 'undo'): void;
  waitIdle(ms: number): Promise<TestState>;
  state(): TestState;
  toolCalls(): Call[];
  end(): Promise<{ krita: string }>;
};
export type DriverOptions = { directory: string; make: () => Driven; canvas: (copy: string | null, options: StartOptions) => Canvas | Promise<Canvas>;
  endpoint?: string };

const MAX_WAIT_SECONDS = 55;                 // below the MCP tool-call timeout: poll again for a longer move

class Refusal extends Error {
  readonly status: number;
  constructor(message: string, status: number) { super(message); this.status = status; }
}

async function body(req: IncomingMessage): Promise<Record<string, any>> {
  let text = '';
  for await (const chunk of req) text += chunk;
  return text ? JSON.parse(text) : {};
}

export async function serveDriver(options: DriverOptions): Promise<{ socket: string; close: () => Promise<void> }> {
  const folder = await mkdtemp(join(options.directory, 'driver-'));
  const socket = join(folder, 'socket');
  let chat: Driven | null = null, canvas: Canvas = { width: 1, height: 1 };
  const current = () => { if (!chat) throw new Refusal('No test chat is running: start one with creative_test_start.', 409); return chat; };
  const routes: Record<string, (input: Record<string, any>, url: URL) => Promise<unknown>> = {
    'POST /start': async input => {
      if (chat) throw new Refusal('A test chat is already running: end it with creative_test_end first.', 409);
      if (typeof input.prompt !== 'string' || !input.prompt.trim()) throw new Refusal('prompt is required.', 400);
      const next = options.make();
      const started = await next.start(input as StartOptions);
      chat = next;
      canvas = await options.canvas(started.copy, input as StartOptions);
      return { status: 'ok', ...started };
    },
    'POST /prompt': async input => {
      if (typeof input.text !== 'string' || !input.text.trim()) throw new Refusal('text is required.', 400);
      current().prompt(input.text);
      return { status: 'ok' };
    },
    'POST /move': async input => {
      if (input.action !== 'keep' && input.action !== 'undo') throw new Refusal('action is keep or undo.', 400);
      current().move(input.action);
      return { status: 'ok' };
    },
    'GET /state': async (_input, url) => {
      const wait = Number(url.searchParams.get('wait') ?? 0);
      if (!Number.isFinite(wait) || wait < 0 || wait > MAX_WAIT_SECONDS) throw new Refusal(`wait is 0-${MAX_WAIT_SECONDS} seconds; poll again for longer.`, 400);
      const driven = current();
      const state = wait ? await driven.waitIdle(wait * 1000) : driven.state();
      return { ...state, tool_calls: driven.toolCalls().map(call => ({ tool: call.tool, methods: methodsOf(call, canvas) })) };
    },
    'POST /end': async () => {
      const ended = await current().end();
      chat = null;
      return { status: 'ok', ...ended };
    },
  };
  const server: Server = createServer(async (req, res) => {
    res.setHeader('Content-Type', 'application/json');
    try {
      const url = new URL(req.url ?? '/', 'http://localhost');
      const route = routes[`${req.method} ${url.pathname}`];
      if (!route) throw new Refusal('Unknown test driver route.', 404);
      res.end(JSON.stringify(await route(await body(req), url)));
    } catch (error) {
      res.statusCode = error instanceof Refusal ? error.status : 500;
      res.end(JSON.stringify({ error: (error as Error).message }));
    }
  });
  await new Promise<void>((resolve, reject) => { server.once('error', reject); server.listen(socket, () => resolve()); });
  await chmod(socket, 0o600);
  if (options.endpoint) await writeFile(options.endpoint, JSON.stringify({ socket, pid: process.pid }), { mode: 0o600 });
  return {
    socket,
    close: async () => {
      if (chat) await chat.end().catch(() => {});
      await new Promise(resolve => server.close(resolve));
      if (options.endpoint) await rm(options.endpoint, { force: true });
      await rm(folder, { recursive: true, force: true });
    },
  };
}
