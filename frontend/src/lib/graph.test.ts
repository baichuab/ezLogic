import { describe, expect, it } from 'vitest';
import { edgePath, graphStats, layoutGraph, mergeExpansion, neighbourhood, nodeTone, shortLabel } from './graph';
import { mockExpandLemmaGraph, mockLemmaGraph } from './mock';
import type { LemmaGraph, LemmaNode } from './types';

function node(id: string, extra: Partial<LemmaNode> = {}): LemmaNode {
	return {
		id,
		label: id,
		kind: 'theorem',
		origin: 'mathlib',
		module: 'Mathlib.X',
		statement: null,
		class_field: false,
		depth: 1,
		truncated: false,
		ok: true,
		start_line: null,
		end_line: null,
		axioms: [],
		...extra
	};
}

function graph(nodes: LemmaNode[], edges: LemmaGraph['edges'], roots: string[] = []): LemmaGraph {
	return {
		ok: true,
		truncated: nodes.some((n) => n.truncated),
		roots,
		nodes,
		edges,
		messages: [],
		notes: [],
		lean_version: null
	};
}

/** Axioms reachable from `id` by following edges. */
function reachableAxioms(g: LemmaGraph, id: string): Set<string> {
	const out = new Set<string>();
	const seen = new Set<string>();
	const stack = [id];
	while (stack.length) {
		const n = stack.pop()!;
		if (seen.has(n)) continue;
		seen.add(n);
		for (const e of g.edges) {
			if (e.src !== n) continue;
			if (e.kind === 'axiom') out.add(e.dst);
			else stack.push(e.dst);
		}
	}
	return out;
}

describe('mergeExpansion', () => {
	it('adds the chain below a truncated node and offsets its depths', () => {
		const base = mockLemmaGraph(1);
		const target = base.nodes.find((n) => n.id === 'Finset.sum_range_succ')!;
		expect(target).toMatchObject({ depth: 1, truncated: true });

		const merged = mergeExpansion(base, mockExpandLemmaGraph(['Finset.sum_range_succ'], 1));
		const byId = new Map(merged.nodes.map((n) => [n.id, n]));

		expect(byId.get('Finset.sum_range_succ')).toMatchObject({ depth: 1, truncated: false });
		expect(byId.get('Finset.sum_range_succ_comm')).toMatchObject({ depth: 2, truncated: true });
		expect(merged.edges).toContainEqual({ src: 'Finset.sum_range_succ', dst: 'Finset.sum_range_succ_comm', kind: 'uses' });
	});

	it("replaces an expanded node's axiom edges so reachability stays exact", () => {
		let g = mockLemmaGraph(1);
		// Before: the truncated node points straight at its axioms.
		expect(g.edges.filter((e) => e.src === 'Finset.sum_range_succ' && e.kind === 'axiom')).toHaveLength(3);

		g = mergeExpansion(g, mockExpandLemmaGraph(['Finset.sum_range_succ'], 1));
		// After: they come through its dependencies instead.
		expect(g.edges.filter((e) => e.src === 'Finset.sum_range_succ' && e.kind === 'axiom')).toHaveLength(0);
		for (const n of g.nodes) {
			if (n.kind !== 'axiom' && n.axioms) expect(reachableAxioms(g, n.id)).toEqual(new Set(n.axioms));
		}
	});

	it('expanding everything eventually matches building the full graph at once', () => {
		let g = mockLemmaGraph(1);
		for (let i = 0; i < 10 && g.truncated; i++) {
			g = mergeExpansion(g, mockExpandLemmaGraph(g.nodes.filter((n) => n.truncated).map((n) => n.id), 1));
		}
		const full = mockLemmaGraph(10);
		const key = (x: LemmaGraph) => x.edges.map((e) => `${e.src}>${e.dst}>${e.kind}`).sort();
		expect(g.truncated).toBe(false);
		expect(key(g)).toEqual(key(full));
		expect(new Map(g.nodes.map((n) => [n.id, n.depth]))).toEqual(new Map(full.nodes.map((n) => [n.id, n.depth])));
	});

	it('keeps the edges and depth of nodes the base already had in full', () => {
		const base = graph(
			[node('r', { depth: 0, origin: 'local' }), node('a', { truncated: true }), node('b', { depth: 1 })],
			[
				{ src: 'r', dst: 'a', kind: 'uses' },
				{ src: 'r', dst: 'b', kind: 'uses' }
			],
			['r']
		);
		const sub = graph(
			[node('a', { depth: 0 }), node('b', { depth: 1 }), node('c', { depth: 2 })],
			[
				{ src: 'a', dst: 'b', kind: 'uses' },
				{ src: 'b', dst: 'c', kind: 'uses' } // b was complete in base: ignored
			],
			['a']
		);
		const merged = mergeExpansion(base, sub);
		expect(merged.nodes.find((n) => n.id === 'b')!.depth).toBe(1);
		expect(merged.edges).toContainEqual({ src: 'a', dst: 'b', kind: 'uses' });
		expect(merged.edges).not.toContainEqual({ src: 'b', dst: 'c', kind: 'uses' });
		expect(merged.truncated).toBe(false);
	});

	it('drops axiom nodes nothing points at any more', () => {
		const base = graph(
			[node('a', { depth: 1, truncated: true, axioms: ['propext'] }), node('propext', { kind: 'axiom', depth: null })],
			[{ src: 'a', dst: 'propext', kind: 'axiom' }]
		);
		const sub = graph([node('a', { depth: 0, axioms: [] })], [], ['a']);
		expect(mergeExpansion(base, sub).nodes.map((n) => n.id)).toEqual(['a']);
	});
});

describe('layoutGraph', () => {
	it('places every node and routes every edge, roots above their dependencies', () => {
		const g = mockLemmaGraph(3);
		const l = layoutGraph(g);
		expect(l.nodes).toHaveLength(g.nodes.length);
		expect(l.edges).toHaveLength(g.edges.length);
		const y = new Map(l.nodes.map((p) => [p.node.id, p.y]));
		for (const e of g.edges) expect(y.get(e.src)!).toBeLessThan(y.get(e.dst)!);
		for (const e of l.edges) expect(e.path.startsWith('M')).toBe(true);
		expect(l.width).toBeGreaterThan(0);
		expect(l.height).toBeGreaterThan(0);
	});

	it('can hide axioms', () => {
		const g = mockLemmaGraph(3);
		const l = layoutGraph(g, { showAxioms: false });
		expect(l.nodes.some((p) => p.node.kind === 'axiom')).toBe(false);
		expect(l.edges.some((e) => e.edge.kind === 'axiom')).toBe(false);
	});

	it('handles cycles (mutual theorems) and self-edges', () => {
		const g = graph(
			[node('even', { depth: 0, origin: 'local' }), node('odd', { depth: 0, origin: 'local' })],
			[
				{ src: 'even', dst: 'odd', kind: 'uses' },
				{ src: 'odd', dst: 'even', kind: 'uses' },
				{ src: 'odd', dst: 'odd', kind: 'uses' }
			]
		);
		const l = layoutGraph(g);
		expect(l.nodes).toHaveLength(2);
		expect(l.edges).toHaveLength(2);
		for (const p of l.nodes) expect(Number.isFinite(p.x) && Number.isFinite(p.y)).toBe(true);
	});

	it('handles an empty graph', () => {
		expect(layoutGraph(graph([], [])).nodes).toEqual([]);
	});
});

describe('helpers', () => {
	it('shortLabel keeps the end of long dotted names', () => {
		expect(shortLabel('mul_add')).toBe('mul_add');
		const s = shortLabel('Mathlib.Algebra.BigOperators.Finset.sum_range_succ_comm');
		expect(s.length).toBeLessThanOrEqual(30);
		expect(s.endsWith('sum_range_succ_comm')).toBe(true);
		expect(s.startsWith('…')).toBe(true);
		expect(shortLabel('x'.repeat(50)).length).toBeLessThanOrEqual(30);
	});

	it('nodeTone tells local, failed, library, axiom and sorry apart', () => {
		expect(nodeTone(node('t', { origin: 'local' }))).toBe('local');
		expect(nodeTone(node('t', { origin: 'local', ok: false }))).toBe('local-error');
		expect(nodeTone(node('t'))).toBe('mathlib');
		expect(nodeTone(node('t', { origin: 'core' }))).toBe('core');
		expect(nodeTone(node('propext', { kind: 'axiom' }))).toBe('axiom');
		expect(nodeTone(node('sorryAx', { kind: 'axiom' }))).toBe('sorry');
	});

	it('neighbourhood includes both directions', () => {
		const g = mockLemmaGraph(2);
		const near = neighbourhood(g, 'Finset.sum_range_succ');
		expect(near.has('two_mul_sum_range')).toBe(true);
		expect(near.has('add_comm')).toBe(true);
		expect(near.has('mul_add')).toBe(false);
	});

	it('graphStats counts theorems, library theorems, axioms and depth', () => {
		const s = graphStats(mockLemmaGraph(1));
		expect(s.depth).toBe(1);
		expect(s.theorems).toBe(6);
		expect(s.library).toBe(5);
		expect(s.axioms).toBeGreaterThan(0);
		expect(s.truncated).toBeGreaterThan(0);
	});

	it('edgePath draws straight lines for two points and curves for more', () => {
		expect(edgePath([{ x: 0, y: 0 }, { x: 10, y: 20 }])).toBe('M0.0,0.0 L10.0,20.0');
		expect(edgePath([{ x: 0, y: 0 }, { x: 5, y: 10 }, { x: 10, y: 20 }])).toContain('Q');
		expect(edgePath([])).toBe('');
	});
});
