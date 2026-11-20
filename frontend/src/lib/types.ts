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
	/** What the user typed (shown in the bubble). */
	text: string;
	/** Proof file attached to this message; its extracted text is sent to the agent. */
	attachment?: { name: string; size: number };
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
}

export type ChatMessage = UserMessage | AssistantMessage;

export interface Chat {
	id: string;
	title: string;
	messages: ChatMessage[];
	/** Opaque agent history returned by the backend, sent back on the next turn. */
	history: unknown[];
	updatedAt: number;
}
