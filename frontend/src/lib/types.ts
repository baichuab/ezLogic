/** What a proof step represents; drives the label shown on each card. */
export type StepKind =
	| 'theorem'
	| 'definition'
	| 'lemma'
	| 'strategy'
	| 'base-case'
	| 'inductive-step'
	| 'step'
	| 'conclusion'
	| 'response';

/**
 * One block of a proof, rendered as a grey card in the chat and as the
 * detail panel when expanded.
 *
 * Text fields may contain inline math as `$...$` and display math as `$$...$$`.
 */
export interface ProofStep {
	id: string;
	kind: StepKind;
	/** Short heading, e.g. "Base case". */
	title: string;
	/** The equation / theorem for this step, as LaTeX (no surrounding `$`). */
	statementTex: string;
	/** 2–3 line plain explanation shown on the card. */
	summary: string;
	/** Thorough explanation shown in the expanded panel. Paragraphs separated by blank lines. */
	explanation: string;
	/** 1-based inclusive line range of this step inside the message's `lean` source. */
	leanLines?: [number, number];
}

export type VerificationStatus = 'verified' | 'unverified' | 'failed';

export interface UserMessage {
	id: string;
	role: 'user';
	text: string;
}

/** One tool call shown in the "what the agent is doing" indicator while a message streams in. */
export interface ToolActivity {
	id: string;
	name: string;
	/** Usually the file path the tool acted on, when there is one. */
	target?: string;
	state: 'running' | 'ok' | 'failed';
}

export interface AssistantMessage {
	id: string;
	role: 'assistant';
	/** Optional sentence shown above the proof blocks. */
	intro?: string;
	steps: ProofStep[];
	/** Full Lean source for the proof; each step points at a slice of it. */
	lean?: string;
	leanFile?: string;
	status: VerificationStatus;
	/** `queries.query_id` for this turn, or `null` if the turn wasn't saved (see AgentDoneEvent). */
	queryId?: string | null;
	/** True if this answer was served from the Postgres cache rather than a fresh agent run. */
	cached?: boolean;
	/** False if the agent hit AGENT_MAX_STEPS before finishing. */
	finished?: boolean;
	/** Present only while the message is still streaming in; cleared once `done` arrives. */
	live?: { text: string; activity: ToolActivity[] };
	/** Set when the stream ended in an `error` event or was cut short. */
	errorDetail?: string;
}

export type ChatMessage = UserMessage | AssistantMessage;

export interface Chat {
	id: string;
	title: string;
	messages: ChatMessage[];
	updatedAt: number;
}

// ---------------------------------------------------------------------------
// Backend wire types: the shapes sent and received over HTTP/SSE. See
// database/README.md and backend/README.md for the authoritative contract.
//
// Fields marked "assumed" are not implemented by the backend yet (tracked in
// frontend/README.md as B1-B8). The frontend treats them as optional and
// falls back to deriving the same information itself when they're absent, so
// the UI doesn't regress when the field starts arriving.

export interface ChatRequest {
	chat_id: string;
	text: string;
	model?: string;
	allowBuild?: boolean;
}

/** `agent/lean.py`'s `LeanResult.to_dict()`: the result of a Lean check tool call. */
export interface LeanToolResult {
	ok: boolean;
	messages?: unknown[];
	output?: string;
	error?: string | null;
}

export interface ToolCall {
	name: string;
	arguments: Record<string, unknown>;
	result: unknown;
}

/** One `data: {...}` line of the `POST /api/chat` event stream. */
export type AgentEvent =
	| { type: 'token'; content: string }
	| { type: 'tool_call_start'; id: string; name: string }
	| ({ type: 'tool_result'; id: string } & ToolCall)
	| {
			type: 'done';
			cached: boolean;
			query_id: string | null;
			/** The Lean source produced by this turn (or the reply text, if no Lean tool ran). */
			response: string;
			/** The agent's prose explanation for this turn. */
			reply: string;
			finished: boolean;
			tool_calls: ToolCall[];
			/** Assumed backend addition (B2): whether the final Lean check passed. */
			verified?: boolean;
			/** Assumed backend addition (B3): the workspace path of the Lean file produced. */
			lean_file?: string;
	  }
	| { type: 'error'; detail: string };

export type AgentDoneEvent = Extract<AgentEvent, { type: 'done' }>;

export interface HistoryTurn {
	query_id: string;
	model: string;
	query: string;
	response: string;
	created_at: string;
	/** Assumed backend addition (B4): the stored explanation, when it differs from `response`. */
	reply?: string;
}

export interface HistoryResponse {
	turns: HistoryTurn[];
}

/** Assumed backend addition (B1): `POST /api/session` returning more than 204. */
export interface SessionInfo {
	guest_id: string;
	expires_at: string;
	created: boolean;
}
