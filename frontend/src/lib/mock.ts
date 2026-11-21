import type {
	AgentEvent,
	AssistantMessage,
	Chat,
	LemmaEdge,
	LemmaGraph,
	LemmaNode,
	ProofStep,
	ToolCall
} from './types';

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

export interface MockStep {
	event: AgentEvent;
	/** Milliseconds `streamChat`'s mock branch waits before yielding this event. */
	delay: number;
}

function chunk(text: string, size: number): string[] {
	const out: string[] = [];
	for (let i = 0; i < text.length; i += size) out.push(text.slice(i, i + size));
	return out;
}

/** `token` events for `text`, split into small chunks, so it streams in visibly rather than all at once. */
function textEvents(text: string, delay: number, size = 8): MockStep[] {
	return chunk(text, size).map((content) => ({ event: { type: 'token', content }, delay }));
}

/**
 * A scripted `AgentEvent` sequence standing in for a real `/api/chat` run,
 * built from `AgentEvent`s (not a ready-made `AssistantMessage`) so mock mode
 * exercises the same `applyEvent` / `finalizeLive` / `fromReply` code path as
 * the real backend: commentary streams in as `token`s (with the ```json steps
 * block hidden live by `liveProse`, the same as a real reply would be), tool
 * calls appear as `tool_call_start`/`tool_result`, and the proof's
 * verification status is derived from those tool calls, not asserted.
 *
 * For manual testing of the live view, `userText` can be `/slow` (longer
 * delays, to watch each step) or `/error` (ends in an `error` event instead
 * of `done`, partway through).
 */
export function mockEvents(userText = ''): MockStep[] {
	const trimmed = userText.trim().toLowerCase();
	const delay = trimmed.startsWith('/slow') ? 260 : 60;

	if (trimmed.startsWith('/error')) {
		return [
			...textEvents('Let me take a look at this.\n\n', delay),
			{ event: { type: 'tool_call_start', id: 'mock-err', name: 'check_lean_snippet' }, delay },
			{
				event: {
					type: 'error',
					detail: 'Mock error (type /error to trigger this): simulated failure for manual testing.'
				},
				delay
			}
		];
	}

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
	const commentary = 'Let me formalise this and check it compiles with Lean.\n\n';
	const summary = ['```json', JSON.stringify({ intro: GAUSS_INTRO, steps: GAUSS_STEPS }), '```'].join('\n');

	return [
		...textEvents(commentary, delay),
		{ event: { type: 'tool_call_start', id: 'mock-1', name: writeCall.name }, delay },
		{ event: { type: 'tool_result', id: 'mock-1', ...writeCall }, delay },
		{ event: { type: 'tool_call_start', id: 'mock-2', name: checkCall.name }, delay },
		{ event: { type: 'tool_result', id: 'mock-2', ...checkCall }, delay },
		...textEvents(summary, delay, 24),
		{
			event: {
				type: 'done',
				cached: false,
				query_id: `mock-${Date.now().toString(36)}`,
				response: GAUSS_LEAN,
				reply: commentary + summary,
				finished: true,
				tool_calls: [writeCall, checkCall]
			},
			delay
		}
	];
}

// ---------------------------------------------------------------------------
// Lemma dependency graph (mock `POST /api/lemma-graph`)
//
// The chain below GAUSS_LEAN's theorem, as the backend reports it (names, modules and links taken
// from real Lean output). `mockLemmaGraph` / `mockExpandLemmaGraph` cut it at a depth the way the
// backend does, so expanding truncated nodes works in mock mode too.

const BIG_OPS = 'Mathlib.Algebra.BigOperators.Group.Finset.Basic';
const CQP = ['Classical.choice', 'Quot.sound', 'propext'];

interface MockLemma {
	module: string;
	statement: string;
	uses: string[];
	axioms: string[];
	classField?: boolean;
}

const MOCK_LEMMAS: Record<string, MockLemma> = {
	'Finset.sum_range_succ': {
		module: BIG_OPS,
		statement: '∀ {M : Type u_4} [inst : AddCommMonoid M] (f : ℕ → M) (n : ℕ), ∑ x ∈ Finset.range (n + 1), f x = ∑ x ∈ Finset.range n, f x + f n',
		uses: ['Finset.sum_range_succ_comm', 'add_comm'],
		axioms: CQP
	},
	'Finset.sum_range_succ_comm': {
		module: BIG_OPS,
		statement: '∀ {M : Type u_4} [inst : AddCommMonoid M] (f : ℕ → M) (n : ℕ), ∑ x ∈ Finset.range (n + 1), f x = f n + ∑ x ∈ Finset.range n, f x',
		uses: ['Finset.notMem_range_self', 'Finset.range_add_one', 'Finset.sum_insert'],
		axioms: CQP
	},
	'Finset.sum_insert': {
		module: BIG_OPS,
		statement: '∀ {β : Type u} {α : Type v} {s : Finset α} {a : α} {f : α → β} [inst : AddCommMonoid β] [inst_1 : DecidableEq α], a ∉ s → ∑ x ∈ insert a s, f x = f a + ∑ x ∈ s, f x',
		uses: ['Finset.fold_insert', 'add_assoc', 'add_comm'],
		axioms: CQP
	},
	'Finset.fold_insert': {
		module: 'Mathlib.Data.Finset.Fold',
		statement: '∀ {α : Type u_1} {β : Type u_2} {op : β → β → β} [hc : Std.Commutative op] [ha : Std.Associative op] {f : α → β} {b : β} {s : Finset α} {a : α} [inst : DecidableEq α], a ∉ s → Finset.fold op b f (insert a s) = op (f a) (Finset.fold op b f s)',
		uses: [],
		axioms: CQP
	},
	'Finset.notMem_range_self': {
		module: 'Mathlib.Data.Finset.Range',
		statement: '∀ {n : ℕ}, n ∉ Finset.range n',
		uses: [],
		axioms: CQP
	},
	'Finset.range_add_one': {
		module: 'Mathlib.Data.Finset.Range',
		statement: '∀ {n : ℕ}, Finset.range (n + 1) = insert n (Finset.range n)',
		uses: [],
		axioms: CQP
	},
	'Finset.sum_range_zero': {
		module: BIG_OPS,
		statement: '∀ {M : Type u_4} [inst : AddCommMonoid M] (f : ℕ → M), ∑ k ∈ Finset.range 0, f k = 0',
		uses: ['Finset.range_zero', 'Finset.sum_empty'],
		axioms: ['Quot.sound', 'propext']
	},
	'Finset.range_zero': {
		module: 'Mathlib.Data.Finset.Range',
		statement: 'Finset.range 0 = ∅',
		uses: [],
		axioms: []
	},
	'Finset.sum_empty': {
		module: BIG_OPS,
		statement: '∀ {β : Type u} {α : Type v} [inst : AddCommMonoid β] {f : α → β}, ∑ x ∈ ∅, f x = 0',
		uses: [],
		axioms: ['Quot.sound']
	},
	mul_add: {
		module: 'Mathlib.Algebra.Ring.Defs',
		statement: '∀ {R : Type x} [inst : Mul R] [inst_1 : Add R] [inst_2 : LeftDistribClass R] (a b c : R), a * (b + c) = a * b + a * c',
		uses: ['left_distrib'],
		axioms: []
	},
	left_distrib: {
		module: 'Mathlib.Algebra.Ring.Defs',
		statement: '∀ {R : Type x} [inst : Mul R] [inst_1 : Add R] [inst_2 : LeftDistribClass R] (a b c : R), a * (b + c) = a * b + a * c',
		uses: ['LeftDistribClass.left_distrib'],
		axioms: []
	},
	'LeftDistribClass.left_distrib': {
		module: 'Mathlib.Algebra.Ring.Defs',
		statement: '∀ {R : Type u_1} {inst : Mul R} {inst_1 : Add R} [self : LeftDistribClass R] (a b c : R), a * (b + c) = a * b + a * c',
		uses: [],
		axioms: [],
		classField: true
	},
	add_comm: {
		module: 'Mathlib.Algebra.Group.Semigroup',
		statement: '∀ {G : Type u_1} [inst : AddCommMagma G] (a b : G), a + b = b + a',
		uses: ['AddCommMagma.add_comm'],
		axioms: []
	},
	'AddCommMagma.add_comm': {
		module: 'Mathlib.Algebra.Group.Semigroup',
		statement: '∀ {G : Type u} [self : AddCommMagma G] (a b : G), a + b = b + a',
		uses: [],
		axioms: [],
		classField: true
	},
	add_assoc: {
		module: 'Mathlib.Algebra.Group.Semigroup',
		statement: '∀ {G : Type u_1} [inst : AddSemigroup G] (a b c : G), a + b + c = a + (b + c)',
		uses: ['AddSemigroup.add_assoc'],
		axioms: []
	},
	'AddSemigroup.add_assoc': {
		module: 'Mathlib.Algebra.Group.Semigroup',
		statement: '∀ {G : Type u} [self : AddSemigroup G] (a b c : G), a + b + c = a + (b + c)',
		uses: [],
		axioms: [],
		classField: true
	},
	'MulZeroClass.mul_zero': {
		module: 'Mathlib.Algebra.GroupWithZero.Defs',
		statement: '∀ {M₀ : Type u} [self : MulZeroClass M₀] (a : M₀), a * 0 = 0',
		uses: [],
		axioms: [],
		classField: true
	},
	zero_add: {
		module: 'Mathlib.Algebra.Group.Defs',
		statement: '∀ {M : Type u} [inst : AddZeroClass M] (a : M), 0 + a = a',
		uses: ['AddZeroClass.zero_add'],
		axioms: []
	},
	'AddZeroClass.zero_add': {
		module: 'Mathlib.Algebra.Group.Defs',
		statement: '∀ {M : Type u} [self : AddZeroClass M] (a : M), 0 + a = a',
		uses: [],
		axioms: [],
		classField: true
	}
};

const MOCK_AXIOMS: Record<string, string> = {
	'Classical.choice': '{α : Sort u} → Nonempty α → α',
	'Quot.sound': '∀ {α : Sort u} {r : α → α → Prop} {a b : α}, r a b → Quot.mk r a = Quot.mk r b',
	propext: '∀ {a b : Prop}, (a ↔ b) → a = b'
};

const MOCK_ROOT = 'two_mul_sum_range';
const MOCK_ROOT_LEMMA: MockLemma = {
	module: '',
	statement: '∀ (n : ℕ), 2 * ∑ i ∈ Finset.range (n + 1), i = n * (n + 1)',
	uses: ['Finset.sum_range_succ', 'Finset.sum_range_zero', 'MulZeroClass.mul_zero', 'mul_add', 'zero_add'],
	axioms: CQP
};

/** Breadth-first from `roots` to `depth`, like backend/lemma_graph's metaprogram and builder. */
function mockGraphFrom(roots: string[], depth: number): LemmaGraph {
	const lemma = (id: string) => (id === MOCK_ROOT ? MOCK_ROOT_LEMMA : MOCK_LEMMAS[id]);
	const depthOf = new Map<string, number>();
	const order: string[] = [];
	const truncated = new Set<string>();
	for (const r of roots) {
		if (!lemma(r) || depthOf.has(r)) continue;
		depthOf.set(r, 0);
		order.push(r);
	}
	for (let i = 0; i < order.length; i++) {
		const id = order[i];
		const d = depthOf.get(id)!;
		const uses = lemma(id).uses;
		if (!uses.length) continue;
		if (d > 0 && d >= depth) {
			truncated.add(id);
			continue;
		}
		for (const u of uses) {
			if (depthOf.has(u)) continue;
			depthOf.set(u, d + 1);
			order.push(u);
		}
	}
	const shown = (id: string) => (truncated.has(id) ? [] : lemma(id).uses.filter((u) => depthOf.has(u)));
	const edges: LemmaEdge[] = [];
	const usedAxioms = new Set<string>();
	const nodes: LemmaNode[] = order.map((id) => {
		const l = lemma(id);
		const local = id === MOCK_ROOT;
		for (const u of shown(id)) edges.push({ src: id, dst: u, kind: 'uses' });
		const covered = new Set(shown(id).flatMap((u) => lemma(u).axioms));
		for (const a of l.axioms.filter((a) => !covered.has(a))) {
			edges.push({ src: id, dst: a, kind: 'axiom' });
			usedAxioms.add(a);
		}
		return {
			id,
			label: id,
			kind: 'theorem',
			origin: local ? 'local' : 'mathlib',
			module: local ? null : l.module,
			statement: l.statement,
			class_field: !!l.classField,
			depth: depthOf.get(id)!,
			truncated: truncated.has(id),
			ok: true,
			start_line: local ? 6 : null,
			end_line: local ? 12 : null,
			axioms: l.axioms
		};
	});
	for (const a of [...usedAxioms].sort()) {
		nodes.push({
			id: a,
			label: a,
			kind: 'axiom',
			origin: 'core',
			module: a === 'propext' ? 'Init.Core' : 'Init.Prelude',
			statement: MOCK_AXIOMS[a] ?? null,
			class_field: false,
			depth: null,
			truncated: false,
			ok: true,
			start_line: null,
			end_line: null,
			axioms: null
		});
	}
	return {
		ok: true,
		truncated: truncated.size > 0,
		roots: order.filter((id) => depthOf.get(id) === 0),
		nodes,
		edges,
		messages: [],
		notes: [],
		lean_version: '4.35.0'
	};
}

/** The demo graph for GAUSS_LEAN (whatever source is passed). */
export function mockLemmaGraph(depth = 2): LemmaGraph {
	return mockGraphFrom([MOCK_ROOT], depth);
}

export function mockExpandLemmaGraph(names: string[], depth = 2): LemmaGraph {
	return mockGraphFrom(names, depth);
}
