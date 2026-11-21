import katex from 'katex';
import type { LiveItem, StepKind } from './types';

export function tex(src: string, displayMode = false): string {
	return katex.renderToString(src, { displayMode, throwOnError: false, output: 'html' });
}

export type Segment =
	| { type: 'text'; value: string }
	| { type: 'math'; html: string; display: boolean }
	| { type: 'code'; value: string };

/** Split prose into text, `$inline$`, `$$display$$` math and `code` segments. */
export function segments(src: string): Segment[] {
	const out: Segment[] = [];
	const re = /\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$|`([^`\n]+)`/g;
	let last = 0;
	for (const m of src.matchAll(re)) {
		if (m.index! > last) out.push({ type: 'text', value: src.slice(last, m.index) });
		if (m[1] !== undefined) out.push({ type: 'math', html: tex(m[1], true), display: true });
		else if (m[2] !== undefined) out.push({ type: 'math', html: tex(m[2]), display: false });
		else out.push({ type: 'code', value: m[3] });
		last = m.index! + m[0].length;
	}
	if (last < src.length) out.push({ type: 'text', value: src.slice(last) });
	return out;
}

export const paragraphs = (src: string) =>
	src
		.split(/\n\s*\n/)
		.map((p) => p.trim())
		.filter(Boolean);

export const KIND_LABEL: Record<StepKind, string> = {
	theorem: 'Theorem',
	definition: 'Definition',
	lemma: 'Lemma',
	strategy: 'Strategy',
	'base-case': 'Base case',
	'inductive-step': 'Inductive step',
	step: 'Step',
	conclusion: 'Conclusion',
	response: 'Response'
};

// ---------------------------------------------------------------------------
// Live agent view: the "what's happening" indicator and the collapsed trace

/** Friendlier wording than a raw tool name, for both the live indicator and the trace rows. */
export const TOOL_LABEL: Record<string, string> = {
	check_lean_file: 'Checking the proof with Lean',
	check_lean_snippet: 'Checking a snippet with Lean',
	write_file: 'Writing the proof',
	edit_file: 'Updating the proof',
	read_file: 'Reading the workspace',
	list_files: 'Looking at the workspace',
	delete_file: 'Cleaning up'
};

export const toolLabel = (name: string): string => TOOL_LABEL[name] ?? `Running ${name}`;

const FENCE = /```(\w*)\s*([\s\S]*?)```/g;
const OPEN_FENCE = /```(\w*)\s*([\s\S]*)$/;

/** Short placeholder for a fenced block that's still being written, by language tag. */
const OPEN_BLOCK_LABEL: Record<string, string> = {
	json: 'Preparing proof steps…',
	lean: 'Writing Lean…',
	lean4: 'Writing Lean…'
};

/**
 * What to show of the agent's streaming commentary. A *complete* fenced code
 * block (```json steps, ```lean, ...) is hidden outright: the finished
 * message shows the real thing properly rendered. A block that's still
 * *open* (no closing fence has arrived yet) becomes a short placeholder
 * instead of streaming raw, half-formed JSON or Lean onto the screen.
 */
export function liveProse(text: string): string {
	const withoutClosedBlocks = text.replace(FENCE, '');
	const open = withoutClosedBlocks.match(OPEN_FENCE);
	if (!open) return withoutClosedBlocks.trim();
	const lang = open[1].toLowerCase();
	const before = withoutClosedBlocks.slice(0, open.index);
	return (before + (OPEN_BLOCK_LABEL[lang] ?? 'Writing…')).trim();
}

/**
 * One-line summary for the collapsed "How this was checked" section on a
 * finished message, e.g. "4 tool steps · last Lean check passed". Empty when
 * there are no tool steps at all (the section is then hidden).
 */
export function traceSummary(items: LiveItem[]): string {
	const tools = items.filter((i): i is Extract<LiveItem, { kind: 'tool' }> => i.kind === 'tool');
	if (tools.length === 0) return '';
	const steps = `${tools.length} tool step${tools.length === 1 ? '' : 's'}`;
	const checks = tools.filter((t) => !t.probe && (t.name === 'check_lean_file' || t.name === 'check_lean_snippet'));
	const lastCheck = checks.at(-1);
	if (!lastCheck) return steps;
	return `${steps} · last Lean check ${lastCheck.state === 'ok' ? 'passed' : 'failed'}`;
}

// ---------------------------------------------------------------------------
// Minimal Lean 4 syntax highlighter (line-by-line, returns HTML).

const KEYWORDS = new Set(
	`theorem lemma def example abbrev instance structure class inductive where extends
	by at with fun match do let have show from calc if then else for in return
	import open namespace section end variable universe noncomputable private protected
	deriving mutual set_option attribute local`.split(/\s+/)
);
const TACTICS = new Set(
	`intro intros induction cases rcases obtain rw rwa simp simp_all exact apply refine
	constructor use ring ring_nf linarith nlinarith omega norm_num decide rfl trivial
	unfold field_simp positivity aesop gcongr push_cast exact_mod_cast specialize
	contradiction exfalso by_contra by_cases left right ext congr subst sorry`.split(/\s+/)
);

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

const TOKEN =
	/(--.*$)|(\/-[\s\S]*?-\/)|("(?:[^"\\]|\\.)*")|(\b\d+\b)|([A-Za-z_α-ωΑ-Ωℕℤℚℝℂ][\w'.α-ωΑ-Ωℕℤℚℝℂ₀-₉]*)|([∑∏∀∃λ→←↔≤≥≠∈∉⊆∧∨¬×⟨⟩:=|]+)/gm;

/** Highlight Lean source and return one HTML string per line. */
export function highlightLean(src: string): string[] {
	// Block comments may span lines: highlight the whole source, then split.
	let html = '';
	let last = 0;
	for (const m of src.matchAll(TOKEN)) {
		html += esc(src.slice(last, m.index));
		const [t, line, block, str, num, ident, sym] = m;
		const wrap = (cls: string, s: string) =>
			s
				.split('\n')
				.map((part) => `<span class="lean-${cls}">${esc(part)}</span>`)
				.join('\n');
		if (line || block) html += wrap('comment', t);
		else if (str) html += wrap('string', t);
		else if (num) html += wrap('number', t);
		else if (ident) {
			if (KEYWORDS.has(t)) html += wrap('keyword', t);
			else if (TACTICS.has(t)) html += wrap('tactic', t);
			else if (/^[A-Zℕℤℚℝℂ]/.test(t)) html += wrap('type', t);
			else html += esc(t);
		} else if (sym) html += wrap('symbol', t);
		else html += esc(t);
		last = m.index! + t.length;
	}
	html += esc(src.slice(last));
	return html.split('\n');
}
