import type { ProofGraph } from './types';
import { ApiError } from './api';

export type GraphState =
	| { kind: 'loading' | 'building' | 'unavailable' | 'unsaved' }
	| { kind: 'ready'; graph: ProofGraph }
	| { kind: 'error'; message: string; retryable: boolean };

/** One panel's lifecycle, including protection against fetches that ignore abort. */
export function createGraphLoader(
	fetchGraph: (id: string, signal: AbortSignal, build: boolean) => Promise<ProofGraph | null>,
	update: (state: GraphState) => void
) {
	let controller: AbortController | undefined;
	let generation = 0;
	function cancel() { generation++; controller?.abort(); }
	async function load(id: string | null | undefined, build = false) {
		cancel();
		const current = generation;
		if (!id) { update({ kind: 'unsaved' }); return; }
		controller = new AbortController();
		update({ kind: build ? 'building' : 'loading' });
		try {
			const graph = await fetchGraph(id, controller.signal, build);
			if (current === generation) update(graph ? { kind: 'ready', graph } : { kind: 'unavailable' });
		} catch (e) {
			if (current === generation) update({
				kind: 'error',
				message: e instanceof Error ? e.message : String(e),
				retryable: !(e instanceof ApiError && e.status === 404)
			});
		}
	}
	return { load, cancel };
}
