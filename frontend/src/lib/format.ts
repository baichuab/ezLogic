import katex from 'katex';
import type { StepKind } from './types';

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
