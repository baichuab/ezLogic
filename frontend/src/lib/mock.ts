import type { AgentEvent, AssistantMessage, Chat, ProofStep, ToolCall } from './types';

export const GAUSS_LEAN = `import Mathlib

open Finset

/-- Twice the sum 0 + 1 + ⋯ + n equals n(n+1). -/
theorem two_mul_sum_range (n : ℕ) :
    2 * ∑ i ∈ range (n + 1), i = n * (n + 1) := by
  induction n with
  | zero => simp
  | succ k ih =>
    rw [sum_range_succ, mul_add, ih]
    ring`;

export const GAUSS_FILE = 'GaussSum.lean';

export const GAUSS_INTRO =
	'Here is the proof, broken into six steps. Select any block for a fuller explanation and its Lean code.';

/** The worked example used for the demo chat and for `mockEvents()`. */
export const GAUSS_STEPS: ProofStep[] = [
	{
		id: 's1',
		kind: 'theorem',
		title: 'Statement',
		statementTex: '2\\sum_{i=0}^{n} i \\;=\\; n(n+1)',
		summary:
			'For every natural number $n$, twice the sum $0 + 1 + \\dots + n$ equals $n(n+1)$. We state it with the factor of 2 so no division is needed.',
		explanation: `This is Gauss's formula for the sum of the first $n$ natural numbers, usually written $\\sum_{i=0}^{n} i = \\frac{n(n+1)}{2}$.

Natural-number division in Lean truncates, so $\\frac{n(n+1)}{2}$ would force us to prove separately that $n(n+1)$ is even. Multiplying both sides by 2 gives an equivalent statement that lives entirely in $\\mathbb{N}$ with only addition and multiplication.

In Lean, $\\sum_{i=0}^{n} i$ is written \`∑ i ∈ range (n + 1), i\`: \`range (n + 1)\` is the finite set $\\{0, 1, \\dots, n\\}$.`,
		leanLines: [5, 7]
	},
	{
		id: 's2',
		kind: 'strategy',
		title: 'Proof strategy',
		statementTex:
			'P(0) \\;\\land\\; \\big(\\forall k,\\ P(k) \\Rightarrow P(k+1)\\big) \\;\\Longrightarrow\\; \\forall n,\\ P(n)',
		summary:
			'We prove the statement by induction on $n$: check $n = 0$, then show that if it holds for $k$ it also holds for $k + 1$.',
		explanation: `Let $P(n)$ be the claim $2\\sum_{i=0}^{n} i = n(n+1)$. Mathematical induction says that if $P(0)$ holds, and $P(k)$ implies $P(k+1)$ for every $k$, then $P(n)$ holds for all $n$.

The tactic \`induction n with\` asks Lean to split the goal into exactly these two cases, named \`zero\` and \`succ\`. In the \`succ\` case Lean introduces a fresh variable \`k\` and the induction hypothesis \`ih : P(k)\`.`,
		leanLines: [8, 8]
	},
	{
		id: 's3',
		kind: 'base-case',
		title: 'Base case',
		statementTex: '2\\sum_{i=0}^{0} i \\;=\\; 2 \\cdot 0 \\;=\\; 0 \\;=\\; 0 \\cdot (0+1)',
		summary:
			'When $n = 0$ the sum has a single term, $0$, so both sides are $0$. Lean’s simplifier closes this automatically.',
		explanation: `For $n = 0$ the range $\\{0\\}$ has one element, so the sum is $0$ and the left side is $2 \\cdot 0 = 0$. The right side is $0 \\cdot 1 = 0$.

\`simp\` unfolds \`range 1\`, evaluates the singleton sum and the multiplications by zero, and sees that both sides are equal. No manual rewriting is needed.`,
		leanLines: [9, 9]
	},
	{
		id: 's4',
		kind: 'inductive-step',
		title: 'Peel off the last term',
		statementTex: '\\sum_{i=0}^{k+1} i \\;=\\; \\sum_{i=0}^{k} i \\;+\\; (k+1)',
		summary:
			'Assume the formula for $k$. To reach $k + 1$, split the sum into the part we already know plus the new last term $k + 1$.',
		explanation: `In the inductive step we assume $2\\sum_{i=0}^{k} i = k(k+1)$ and must show $2\\sum_{i=0}^{k+1} i = (k+1)(k+2)$.

The key move is to separate the final term of the sum. The lemma \`Finset.sum_range_succ\` states exactly this: summing over $\\{0, \\dots, k+1\\}$ is summing over $\\{0, \\dots, k\\}$ and then adding $f(k+1)$.

Then \`mul_add\` distributes the factor 2 so the left side becomes $2\\sum_{i=0}^{k} i + 2(k+1)$. That puts the known sum on its own, ready for the induction hypothesis.`,
		leanLines: [10, 11]
	},
	{
		id: 's5',
		kind: 'step',
		title: 'Apply the induction hypothesis',
		statementTex: '2\\sum_{i=0}^{k} i + 2(k+1) \\;=\\; k(k+1) + 2(k+1)',
		summary:
			'The hypothesis tells us $2\\sum_{i=0}^{k} i = k(k+1)$, so we substitute it directly into the left-hand side.',
		explanation: `After distributing, the expression $2\\sum_{i=0}^{k} i$ appears verbatim in the goal. The induction hypothesis \`ih\` says this equals $k(k+1)$, so rewriting with \`ih\` replaces it.

This is the only place the hypothesis is used, and it is what links the case $k + 1$ back to the case $k$. The goal is now a pure polynomial identity with no sums left.`,
		leanLines: [11, 11]
	},
	{
		id: 's6',
		kind: 'conclusion',
		title: 'Finish with algebra',
		statementTex: 'k(k+1) + 2(k+1) \\;=\\; (k+1)(k+2) \\qquad \\blacksquare',
		summary:
			'Both sides expand to $k^2 + 3k + 2$, so the identity holds. This completes the induction and the proof.',
		explanation: `Factoring out $(k+1)$ gives $k(k+1) + 2(k+1) = (k+1)(k+2)$. Equivalently, both sides expand to $k^2 + 3k + 2$.

The \`ring\` tactic decides equalities in commutative (semi)rings like $\\mathbb{N}$ by normalising both sides to a canonical polynomial form, so it closes the goal.

With the base case and the inductive step done, induction gives the result for every $n \\in \\mathbb{N}$. Lean reports no remaining goals, and the proof is verified.`,
		leanLines: [12, 12]
	}
];

/** A complete worked example, in the shape of a finished UI message. Used for `demoChats()`. */
export function gaussProof(id = 'a-gauss'): AssistantMessage {
	return {
		id,
		role: 'assistant',
		intro: GAUSS_INTRO,
		lean: GAUSS_LEAN,
		leanFile: GAUSS_FILE,
		status: 'verified',
		steps: GAUSS_STEPS
	};
}

export function demoChats(): Chat[] {
	const now = Date.now();
	return [
		{
			id: 'c-gauss',
			title: 'Sum of the first n naturals',
			updatedAt: now,
			messages: [
				{
					id: 'u-gauss',
					role: 'user',
					text: 'Prove that 0 + 1 + 2 + … + n = n(n+1)/2 for every natural number n.'
				},
				gaussProof()
			]
		}
	];
}

/**
 * A scripted `AgentEvent` sequence standing in for a real `/api/chat` run,
 * ending in a `done` event for the Gauss sum proof above. Built from
 * `AgentEvent`s (not a ready-made `AssistantMessage`) so mock mode exercises
 * the same `applyEvent` / `fromDone` / `fromReply` code path as the real
 * backend, including the ```json steps block and the tool-call-derived
 * verification status.
 */
export function mockEvents(): AgentEvent[] {
	const writeCall: ToolCall = {
		name: 'write_file',
		arguments: { path: GAUSS_FILE, content: GAUSS_LEAN },
		result: { result: `wrote ${GAUSS_FILE}` }
	};
	const checkCall: ToolCall = {
		name: 'check_lean_file',
		arguments: { path: GAUSS_FILE },
		result: { ok: true, messages: [], output: '', error: null }
	};
	const reply = ['```json', JSON.stringify({ intro: GAUSS_INTRO, steps: GAUSS_STEPS }), '```'].join('\n');

	return [
		{ type: 'tool_call_start', id: 'mock-1', name: writeCall.name },
		{ type: 'tool_result', id: 'mock-1', ...writeCall },
		{ type: 'tool_call_start', id: 'mock-2', name: checkCall.name },
		{ type: 'tool_result', id: 'mock-2', ...checkCall },
		{
			type: 'done',
			cached: false,
			query_id: `mock-${Date.now().toString(36)}`,
			response: GAUSS_LEAN,
			reply,
			finished: true,
			tool_calls: [writeCall, checkCall]
		}
	];
}
