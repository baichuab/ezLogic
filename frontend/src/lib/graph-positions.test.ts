import { describe, expect, it } from 'vitest';
import { applyPositions, loadPositions, mergePositions, movedPositions, positionsKey, samePositions, savePositions } from './graph-positions';

function memoryStorage(): Storage {
	const data = new Map<string, string>();
	return {
		get length() { return data.size; },
		clear: () => data.clear(),
		getItem: (k) => data.get(k) ?? null,
		key: (i) => [...data.keys()][i] ?? null,
		removeItem: (k) => { data.delete(k); },
		setItem: (k, v) => { data.set(k, String(v)); }
	};
}

const throwing = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('full'); }, removeItem() { throw new Error('blocked'); } } as unknown as Storage;

describe('graph positions', () => {
	it('uses separate keys per proof and view', () => {
		expect(positionsKey('q1', false)).not.toBe(positionsKey('q1', true));
		expect(positionsKey('q1', false)).not.toBe(positionsKey('q2', false));
	});

	it('round-trips through storage and removes the key when empty', () => {
		const storage = memoryStorage();
		savePositions('k', { A: { x: 1, y: 2 } }, storage);
		expect(loadPositions('k', storage)).toEqual({ A: { x: 1, y: 2 } });
		savePositions('k', {}, storage);
		expect(storage.getItem('k')).toBeNull();
		expect(loadPositions('k', storage)).toEqual({});
	});

	it('survives storage that throws or is missing', () => {
		expect(loadPositions('k', throwing)).toEqual({});
		expect(() => savePositions('k', { A: { x: 1, y: 2 } }, throwing)).not.toThrow();
		expect(loadPositions('k', undefined)).toEqual({});
	});

	it('drops garbage and non-finite values', () => {
		const storage = memoryStorage();
		storage.setItem('bad', 'not json');
		expect(loadPositions('bad', storage)).toEqual({});
		storage.setItem('arr', '[1,2]');
		expect(loadPositions('arr', storage)).toEqual({});
		storage.setItem('k', JSON.stringify({ A: { x: 1, y: 2 }, B: { x: 'a', y: 2 }, C: null, D: { x: 1 }, E: { x: 1e400, y: 0 } }));
		expect(loadPositions('k', storage)).toEqual({ A: { x: 1, y: 2 } });
	});

	it('applies saved positions only to known nodes', () => {
		const layout = [{ id: 'A', position: { x: 0, y: 0 } }, { id: 'B', position: { x: 10, y: 10 } }];
		const out = applyPositions(layout, { A: { x: 5, y: 6 }, gone: { x: 9, y: 9 } });
		expect(out.map((n) => [n.id, n.position])).toEqual([['A', { x: 5, y: 6 }], ['B', { x: 10, y: 10 }]]);
		expect(layout[0].position).toEqual({ x: 0, y: 0 }); // input untouched
	});

	it('keeps only moved nodes', () => {
		const layout = [{ id: 'A', position: { x: 0, y: 0 } }, { id: 'B', position: { x: 10, y: 10 } }];
		const nodes = [{ id: 'A', position: { x: 0.1, y: 0 } }, { id: 'B', position: { x: 40, y: 10 } }, { id: 'X', position: { x: 1, y: 1 } }];
		expect(movedPositions(nodes, layout)).toEqual({ B: { x: 40, y: 10 } });
		expect(samePositions({ B: { x: 40, y: 10 } }, movedPositions(nodes, layout))).toBe(true);
		expect(samePositions({ B: { x: 40, y: 10 } }, {})).toBe(false);
	});

	it('keeps positions of nodes in collapsed branches', () => {
		const saved = { A: { x: 1, y: 1 }, hidden: { x: 2, y: 2 } };
		// A is on screen and was moved back to its automatic spot, so it's no longer saved.
		expect(mergePositions(saved, { B: { x: 3, y: 3 } }, new Set(['A', 'B'])))
			.toEqual({ hidden: { x: 2, y: 2 }, B: { x: 3, y: 3 } });
	});
});
