/** Hand-moved node positions in the dependency graph, kept per proof in the browser.
 * Only nodes that were moved away from their automatic (dagre) spot are stored. */

export type XY = { x: number; y: number };
export type Positions = Record<string, XY>;
type Positioned = { id: string; position: XY };

/** Moves smaller than this (in flow units) count as "not moved". */
const EPSILON = 0.5;

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

/** One key per proof and view: the proof view and the technical view show different nodes. */
export const positionsKey = (queryId: string, technical: boolean) =>
	`ezlogic:graph-layout:v1:${queryId}:${technical ? 'technical' : 'proof'}`;

function defaultStorage(): Storage | undefined {
	try {
		return globalThis.localStorage;
	} catch {
		return undefined; // blocked site data throws on access
	}
}

export function loadPositions(key: string, storage: Storage | undefined = defaultStorage()): Positions {
	try {
		const raw = storage?.getItem(key);
		if (!raw) return {};
		const parsed: unknown = JSON.parse(raw);
		if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
		const out: Positions = {};
		for (const [id, p] of Object.entries(parsed as Record<string, unknown>)) {
			if (p && typeof p === 'object' && finite((p as XY).x) && finite((p as XY).y)) {
				out[id] = { x: (p as XY).x, y: (p as XY).y };
			}
		}
		return out;
	} catch {
		return {};
	}
}

export function savePositions(key: string, positions: Positions, storage: Storage | undefined = defaultStorage()) {
	try {
		if (Object.keys(positions).length) storage?.setItem(key, JSON.stringify(positions));
		else storage?.removeItem(key);
	} catch {
		// Full or blocked storage: positions just aren't remembered.
	}
}

/** Put saved positions on the laid-out nodes; nodes without one keep their automatic spot. */
export function applyPositions<N extends Positioned>(layoutNodes: N[], saved: Positions): N[] {
	return layoutNodes.map((n) => (saved[n.id] ? { ...n, position: { ...saved[n.id] } } : n));
}

/** The nodes whose position differs from the automatic layout. */
export function movedPositions(nodes: Positioned[], layoutNodes: Positioned[]): Positions {
	const auto = new Map(layoutNodes.map((n) => [n.id, n.position]));
	const out: Positions = {};
	for (const n of nodes) {
		const a = auto.get(n.id);
		if (!a || !finite(n.position.x) || !finite(n.position.y)) continue;
		if (Math.abs(n.position.x - a.x) > EPSILON || Math.abs(n.position.y - a.y) > EPSILON) {
			out[n.id] = { x: n.position.x, y: n.position.y };
		}
	}
	return out;
}

/** The new saved set: `moved` for the nodes on screen, plus earlier saved positions of nodes
 * that aren't on screen right now (a collapsed branch keeps its layout). */
export function mergePositions(saved: Positions, moved: Positions, onScreen: ReadonlySet<string>): Positions {
	const kept = Object.entries(saved).filter(([id]) => !onScreen.has(id));
	return { ...Object.fromEntries(kept), ...moved };
}

export const samePositions = (a: Positions, b: Positions) => {
	const ka = Object.keys(a);
	return ka.length === Object.keys(b).length &&
		ka.every((k) => b[k] && b[k].x === a[k].x && b[k].y === a[k].y);
};
