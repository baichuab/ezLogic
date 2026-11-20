import { describe, expect, it } from 'vitest';
import { liveProse, traceSummary } from './format';
import type { LiveItem } from './types';

describe('liveProse', () => {
	it('returns plain prose unchanged', () => {
		expect(liveProse('Let me check this compiles.')).toBe('Let me check this compiles.');
	});

	it('hides a complete fenced block entirely, keeping the surrounding prose', () => {
		const text = 'Here is the plan.\n```json\n{"steps": []}\n```\nAnd here is why it works.';
		const out = liveProse(text);
		expect(out).not.toContain('steps');
		expect(out).not.toContain('```');
		expect(out).toContain('Here is the plan.');
		expect(out).toContain('And here is why it works.');
	});

	it('hides multiple complete blocks', () => {
		const text = '```lean\ntheorem a\n```\nmiddle\n```lean\ntheorem b\n```';
		const out = liveProse(text);
		expect(out).not.toContain('theorem a');
		expect(out).not.toContain('theorem b');
		expect(out).toContain('middle');
	});

	it('shows a placeholder for a json block that has not closed yet', () => {
		const out = liveProse('Here is the plan.\n```json\n{"steps": [{"title": "Statem');
		expect(out).toContain('Here is the plan.');
		expect(out).toContain('Preparing proof steps…');
		expect(out).not.toContain('{"steps"'); // the raw, half-written JSON itself must not leak
		expect(out).not.toContain('Statem');
	});

	it('shows a different placeholder for an open lean block', () => {
		const out = liveProse('```lean\ntheorem foo : True :=');
		expect(out).toBe('Writing Lean…');
	});

	it('shows a generic placeholder for an open block of unknown language', () => {
		const out = liveProse('```\nsome raw content');
		expect(out).toBe('Writing…');
	});

	it('leaves an unterminated inline $ as plain text (no special casing needed)', () => {
		expect(liveProse('The value is $x')).toBe('The value is $x');
	});

	it('never leaks any part of a json block, however the text is split token by token', () => {
		const reply =
			'Here is the proof.\n```json\n' +
			JSON.stringify({ steps: [{ title: 'UNIQUE_MARKER_XYZ', summary: 'x' }] }) +
			'\n```\nDone.';
		for (let i = 1; i <= reply.length; i++) {
			const prefix = reply.slice(0, i);
			expect(liveProse(prefix), `prefix length ${i}`).not.toContain('UNIQUE_MARKER_XYZ');
		}
		// Sanity check the test isn't vacuous: the final, complete prefix does hide the
		// marker but still shows the surrounding prose.
		const full = liveProse(reply);
		expect(full).toContain('Here is the proof.');
		expect(full).toContain('Done.');
	});
});

describe('traceSummary', () => {
	const tool = (name: string, state: 'ok' | 'failed' | 'running'): Extract<LiveItem, { kind: 'tool' }> => ({
		kind: 'tool',
		id: name,
		name,
		state
	});

	it('is empty when there are no tool steps at all (hides the section)', () => {
		expect(traceSummary([])).toBe('');
		expect(traceSummary([{ kind: 'text', text: 'just prose' }])).toBe('');
	});

	it('counts tool steps, singular vs plural', () => {
		expect(traceSummary([tool('read_file', 'ok')])).toBe('1 tool step');
		expect(traceSummary([tool('read_file', 'ok'), tool('list_files', 'ok')])).toBe('2 tool steps');
	});

	it('has no Lean-check clause when no check ran', () => {
		expect(traceSummary([tool('read_file', 'ok'), tool('write_file', 'ok')])).toBe('2 tool steps');
	});

	it('reports the result of the last Lean check, not an earlier one', () => {
		const items = [tool('check_lean_file', 'failed'), tool('edit_file', 'ok'), tool('check_lean_file', 'ok')];
		expect(traceSummary(items)).toBe('3 tool steps · last Lean check passed');
	});

	it('reports a failing last check', () => {
		const items = [tool('check_lean_file', 'ok'), tool('edit_file', 'ok'), tool('check_lean_file', 'failed')];
		expect(traceSummary(items)).toBe('3 tool steps · last Lean check failed');
	});

	it('falls back to the last snippet check when no file check is present', () => {
		const items = [tool('check_lean_snippet', 'failed'), tool('check_lean_snippet', 'ok')];
		expect(traceSummary(items)).toBe('2 tool steps · last Lean check passed');
	});
});
