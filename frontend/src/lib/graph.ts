/**
 * Pure helpers for the lemma dependency graph view (LemmaGraphView.svelte): merging an expansion
 * into a graph, laying it out with dagre, and the bits of styling logic worth testing.
 */
import { Graph, layout } from '@dagrejs/dagre';
import type { LemmaEdge, LemmaGraph, LemmaNode } from './types';

// ---------------------------------------------------------------------------
// Merging `expand` results

const edgeKey = (e: LemmaEdge) => `${e.src}\u0000${e.dst}\u0000${e.kind}`;

/**
 * Merge `sub` (the result of expanding some of `base`'s truncated nodes, whose depths start at 0
 * at those nodes) into `base`.
 *
 * - Depths in `sub` are offset by the depth of the shallowest expanded root; a node already in
 *   `base` keeps the smaller depth.
 * - A node that was truncated in `base` and is expanded in `sub` takes `sub`'s outgoing edges
 *   (its dependencies, and its axiom edges, which are relative to what it now shows) and is no
 *   longer truncated. Every other node keeps its `base` edges.
 */
export function mergeExpansion(base: LemmaGraph, sub: LemmaGraph): LemmaGraph {
	const baseById = new Map(base.nodes.map((n) => [n.id, n]));
	const offsets = sub.roots.map((r) => baseById.get(r)?.depth).filter((d): d is number => d != null);
	const offset = offsets.length ? Math.min(...offsets) : 0;

	const nowExpanded = new Set(
		sub.nodes.filter((n) => !n.truncated && baseById.get(n.id)?.truncated).map((n) => n.id)
	);

	const nodes = new Map<string, LemmaNode>();
	for (const n of base.nodes) {
		nodes.set(n.id, nowExpanded.has(n.id) ? { ...n, truncated: false } : n);
	}
	for (const n of sub.nodes) {
		if (nodes.has(n.id)) continue;
		nodes.set(n.id, { ...n, depth: n.depth == null ? null : n.depth + offset });
	}

	const edges = new Map<string, LemmaEdge>();
	for (const e of base.edges) {
		if (!nowExpanded.has(e.src)) edges.set(edgeKey(e), e);
	}
	for (const e of sub.edges) {
		// Edges of nodes `base` already had in full stay as they were.
		const src = baseById.get(e.src);
		if (src && !nowExpanded.has(e.src)) continue;
		edges.set(edgeKey(e), e);
	}

	// An axiom whose only edges came from now-expanded nodes may be reached through their
	// dependencies instead; drop it if nothing points at it any more.
	const targets = new Set([...edges.values()].map((e) => e.dst));
	const merged = [...nodes.values()].filter((n) => n.kind !== 'axiom' || targets.has(n.id));
	return {
		...base,
		nodes: merged,
		edges: [...edges.values()],
		truncated: merged.some((n) => n.truncated),
		notes: [...base.notes, ...sub.notes.filter((x) => !base.notes.includes(x))]
	};
}

// ---------------------------------------------------------------------------
// Styling

export type NodeTone = 'local' | 'local-error' | 'mathlib' | 'core' | 'axiom' | 'sorry';

export function nodeTone(n: LemmaNode): NodeTone {
	if (n.kind === 'axiom') return n.id === 'sorryAx' ? 'sorry' : 'axiom';
	if (n.origin === 'local') return n.ok ? 'local' : 'local-error';
	return n.origin === 'mathlib' ? 'mathlib' : 'core';
}

const MAX_LABEL = 30;

/** The text drawn in a node: long names keep their last components, which say the most. */
export function shortLabel(label: string, max = MAX_LABEL): string {
	if (label.length <= max) return label;
	const parts = label.split('.');
	let out = parts.pop() ?? label;
	while (parts.length && out.length + parts[parts.length - 1].length + 1 <= max - 2) {
		out = `${parts.pop()}.${out}`;
	}
	return out.length > max - 1 ? `…${out.slice(-(max - 1))}` : `…${out}`;
}

/** The nodes directly connected to `id` (either direction), and `id` itself. */
export function neighbourhood(graph: Pick<LemmaGraph, 'edges'>, id: string): Set<string> {
	const out = new Set([id]);
	for (const e of graph.edges) {
		if (e.src === id) out.add(e.dst);
		if (e.dst === id) out.add(e.src);
	}
	return out;
}

export function graphStats(graph: LemmaGraph) {
	let theorems = 0;
	let axioms = 0;
	let library = 0;
	let truncated = 0;
	for (const n of graph.nodes) {
		if (n.kind === 'axiom') axioms++;
		else {
			theorems++;
			if (n.origin !== 'local') library++;
		}
		if (n.truncated) truncated++;
	}
	const depths = graph.nodes.map((n) => n.depth ?? 0);
	return { theorems, axioms, library, truncated, depth: depths.length ? Math.max(...depths) : 0 };
}

// ---------------------------------------------------------------------------
// Layout

export interface PlacedNode {
	node: LemmaNode;
	text: string;
	/** Centre. */
	x: number;
	y: number;
	width: number;
	height: number;
}

export interface PlacedEdge {
	edge: LemmaEdge;
	path: string;
}

export interface GraphLayout {
	nodes: PlacedNode[];
	edges: PlacedEdge[];
	width: number;
	height: number;
}

const CHAR_W = 6.9; // ~13px monospace
const NODE_H = 30;
const AXIOM_H = 22;

function nodeSize(n: LemmaNode, text: string): { width: number; height: number } {
	if (n.kind === 'axiom') return { width: Math.max(56, text.length * 6.2 + 20), height: AXIOM_H };
	const badge = n.truncated ? 18 : 0;
	return { width: Math.max(64, text.length * CHAR_W + 24 + badge), height: NODE_H };
}

/** An SVG path through dagre's edge points: straight ends, smoothed corners. */
export function edgePath(points: { x: number; y: number }[]): string {
	if (points.length === 0) return '';
	if (points.length < 3) return points.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
	let d = `M${points[0].x.toFixed(1)},${points[0].y.toFixed(1)}`;
	for (let i = 1; i < points.length - 1; i++) {
		const p = points[i];
		const next = points[i + 1];
		const mx = (p.x + next.x) / 2;
		const my = (p.y + next.y) / 2;
		d += ` Q${p.x.toFixed(1)},${p.y.toFixed(1)} ${mx.toFixed(1)},${my.toFixed(1)}`;
	}
	const last = points[points.length - 1];
	return `${d} L${last.x.toFixed(1)},${last.y.toFixed(1)}`;
}

/**
 * Lay the graph out top-down: the proof's own theorems at the top, what they depend on below,
 * axioms at the bottom. Edges point from a theorem down to what it uses. `mutual` cycles are fine:
 * dagre reverses an edge per cycle for ranking and still routes it.
 */
export function layoutGraph(graph: LemmaGraph, opts: { showAxioms?: boolean } = {}): GraphLayout {
	const showAxioms = opts.showAxioms ?? true;
	const visible = graph.nodes.filter((n) => showAxioms || n.kind !== 'axiom');
	const ids = new Set(visible.map((n) => n.id));
	const edges = graph.edges.filter((e) => ids.has(e.src) && ids.has(e.dst) && e.src !== e.dst);

	const g = new Graph({ multigraph: false });
	g.setGraph({ rankdir: 'TB', nodesep: 18, ranksep: 54, edgesep: 8, marginx: 16, marginy: 16 });
	g.setDefaultEdgeLabel(() => ({}));
	const texts = new Map<string, string>();
	for (const n of visible) {
		const text = shortLabel(n.label);
		texts.set(n.id, text);
		g.setNode(n.id, nodeSize(n, text));
	}
	for (const e of edges) {
		// Axiom edges weigh less, so theorem chains stay straight.
		g.setEdge(e.src, e.dst, { weight: e.kind === 'axiom' ? 1 : 3, minlen: 1 });
	}
	layout(g);

	const placed: PlacedNode[] = visible.map((n) => {
		const p = g.node(n.id) as { x: number; y: number; width: number; height: number };
		return { node: n, text: texts.get(n.id)!, x: p.x, y: p.y, width: p.width, height: p.height };
	});
	const routed: PlacedEdge[] = edges.map((e) => {
		const label = g.edge(e.src, e.dst) as { points?: { x: number; y: number }[] } | undefined;
		return { edge: e, path: edgePath(label?.points ?? []) };
	});
	const info = g.graph() as { width?: number; height?: number };
	return { nodes: placed, edges: routed, width: info.width ?? 0, height: info.height ?? 0 };
}
