import { gaussProof } from './mock';
import { KIND_LABEL } from './format';
import type { AssistantMessage, ProofStep, StepKind } from './types';

/** Coerce loosely-typed JSON from the model into a valid ProofStep. */
function normaliseStep(raw: Partial<ProofStep>, i: number): ProofStep {
	const kind = (raw.kind && raw.kind in KIND_LABEL ? raw.kind : 'step') as StepKind;
	const lines = raw.leanLines;
	return {
		id: String(raw.id ?? `s${i + 1}`),
		kind,
		title: String(raw.title ?? ''),
		statementTex: String(raw.statementTex ?? ''),
		summary: String(raw.summary ?? ''),
		explanation: String(raw.explanation ?? raw.summary ?? ''),
		leanLines:
			Array.isArray(lines) && lines.length === 2 && lines.every(Number.isFinite)
				? [lines[0], lines[1]]
				: undefined
	};
}

/**
 * Backend base URL. Set `VITE_API_URL=http://localhost:8000` to talk to the
 * FastAPI agent; leave unset to use the built-in demo proof.
 */
const API_URL: string | undefined = import.meta.env.VITE_API_URL;

export const isMockMode = !API_URL;

export interface SendResult {
	message: AssistantMessage;
	history: unknown[];
}

let counter = 0;
const uid = (prefix: string) => `${prefix}-${Date.now().toString(36)}-${(counter++).toString(36)}`;

export async function sendMessage(text: string, history: unknown[]): Promise<SendResult> {
	if (isMockMode) {
		await new Promise((r) => setTimeout(r, 1400));
		const message = gaussProof(uid('a'));
		message.intro =
			'Demo mode: the backend isn’t connected (set VITE_API_URL), so this is a sample proof. Select any block for details and Lean code.';
		return { message, history };
	}

	const res = await fetch(`${API_URL}/api/chat`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ message: text, history })
	});
	if (!res.ok) {
		const detail = await res.json().catch(() => null);
		throw new Error(detail?.detail ?? `Request failed (${res.status})`);
	}
	const data: { reply: string; messages: unknown[]; finished: boolean } = await res.json();
	return { message: fromReply(data.reply, data.finished), history: data.messages };
}

/**
 * Turn the agent's reply into blocks.
 *
 * If the reply contains a ```json block of the shape `{ "steps": ProofStep[], "lean"?: string }`
 * it is used directly. Otherwise the whole reply becomes one block, with the
 * first ```lean fence (if any) as its code. Remove the fallback once the
 * backend returns structured steps.
 */
export function fromReply(reply: string, finished = true): AssistantMessage {
	const id = uid('a');
	const status = finished ? 'unverified' : 'failed';

	const json = reply.match(/```json\s*([\s\S]*?)```/);
	if (json) {
		try {
			const parsed = JSON.parse(json[1]) as {
				steps: Partial<ProofStep>[];
				lean?: string;
				verified?: boolean;
			};
			if (Array.isArray(parsed.steps) && parsed.steps.length) {
				return {
					id,
					role: 'assistant',
					steps: parsed.steps.map(normaliseStep),
					lean: parsed.lean,
					status: parsed.verified ? 'verified' : status
				};
			}
		} catch {
			// fall through to the plain-text fallback
		}
	}

	const lean = reply.match(/```lean4?\s*([\s\S]*?)```/)?.[1]?.trimEnd();
	const prose = reply.replace(/```[\s\S]*?```/g, '').trim();
	const firstPara = prose.split(/\n\s*\n/)[0] ?? prose;
	return {
		id,
		role: 'assistant',
		lean,
		status,
		steps: [
			{
				id: 's1',
				kind: 'response',
				title: 'Response',
				statementTex: '',
				summary: firstPara,
				explanation: prose,
				leanLines: lean ? [1, lean.split('\n').length] : undefined
			}
		]
	};
}
