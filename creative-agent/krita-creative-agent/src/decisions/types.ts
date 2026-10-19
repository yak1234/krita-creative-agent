// The shapes every decision caller and endpoint share. Callers write questions and read answers in the System One
// form whatever the endpoint's protocol; the client returns either answers or a fallback reason, never both.
import type { ImageContent } from '@earendil-works/pi-ai';

/** An image as Pi carries it (`ImageContent`), or any `{data, mimeType?}`; a missing type means PNG. */
export type DecisionImage = Pick<ImageContent, 'data'> & Partial<Pick<ImageContent, 'type' | 'mimeType'>>;
/** One ordered part of the state: text, an inline data URL (an image), or an image object. Null parts are dropped. */
export type DecisionPart = string | DecisionImage | null | undefined;

export type NoulQuestion = { type: 'noul'; instructions: string; criteria?: { true?: string; false?: string } };
export type ChoiceQuestion = { type: 'choice'; instructions: string; criteria: Record<string, string> };
export type ScoreQuestion = { type: 'score'; instructions: string; criteria: string[] | Record<string, string> };
export type Question = NoulQuestion | ChoiceQuestion | ScoreQuestion;
export type Questions = Record<string, Question>;

/** Probabilities by option (choice value or score level), as the endpoint reports them. */
export type Probabilities = Record<string, number>;
export type NoulAnswer = { type: 'noul'; noul: number };
export type ChoiceAnswer = { type: 'choice'; choice: string; confidence?: number; probabilities?: Probabilities };
export type ScoreAnswer = { type: 'score'; score: number; confidence?: number; probabilities?: Probabilities };
export type RefusalAnswer = { type: 'refusal' };
export type Answer = NoulAnswer | ChoiceAnswer | ScoreAnswer | RefusalAnswer;
/** Answers by question name. They come from the wire unvalidated: callers check each value before use. */
export type Answers = Record<string, Answer | undefined>;

export type DecisionRequest = { parts?: DecisionPart[]; questions: Questions; signal?: AbortSignal; purpose?: string };
export type DecisionUsage = { input_tokens: number; output_tokens: number; cost: number };

export type FallbackReason = 'not_connected' | 'text_only_model' | 'images_unverified' | 'refused' | 'timeout'
  | 'cancelled' | 'service_or_response_error';
export type DecisionAnswered = { answers: Answers; model: string; elapsed_ms: number; usage: DecisionUsage;
  fallback?: undefined; status?: undefined };
export type DecisionFallback = { fallback: FallbackReason; elapsed_ms: number; status?: number;
  answers?: undefined; model?: undefined; usage?: undefined };
/** What decide() returns: handle `fallback` first, then `answers` is there. */
export type DecisionResult = DecisionAnswered | DecisionFallback;

/** What a check needs from a decision client. */
export interface DecisionMaker { decide(request: DecisionRequest): Promise<DecisionResult> }

export type ModelInfo = { id: string; name: string; images: boolean | null; price_per_million_input?: number };
export type ListModels = (options: { fetch: typeof globalThis.fetch; key: string | null }) => Promise<ModelInfo[]>;
export type ProtocolId = 'systemone' | 'openai';
export type Endpoint = { id: string; name: string; protocol: ProtocolId; url: string; keyHint: string; defaultModel: string;
  envKey?: string; custom?: boolean; listModels: ListModels };
/** A custom endpoint as stored: its id is the key it is stored under. */
export type CustomEndpointConfig = { name?: string; url: string; defaultModel?: string };

export type ProtocolBody = { model: string; parts: DecisionPart[] | undefined; questions: Questions };
export type Protocol = { body(request: ProtocolBody): object; answers(body: unknown): Answers | null };

/** The one tracing call the client makes (LangfuseTracing.observeGeneration). */
export type GenerationUpdate = Record<string, unknown>;
export interface DecisionTracing {
  observeGeneration<T>(name: string, observation: { model: string; input: unknown; sessionId?: string; tags?: string[]; metadata?: object },
    call: () => Promise<T>, finish: (result: T) => GenerationUpdate): Promise<T>;
}
/** Trace context for a decision: the chat's Langfuse session and extra tags. */
export type TraceInfo = { sessionId?: string; tags?: string[] };
