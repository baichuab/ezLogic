<script lang="ts">
	import { onMount } from 'svelte';
	import { getProofGraph, isMockMode } from '#lib/api.js';
	import { createGraphLoader, type GraphState } from '#lib/graph-loader.js';
	import { nodeLabel, theoremView, visibleGraph } from '#lib/graph.js';
	import { loadPositions, positionsKey, savePositions, type Positions } from '#lib/graph-positions.js';
	import GraphCanvas from './ProofGraph.svelte';
	import NodeDetail from './ProofGraphNodeDetail.svelte';
	let { queryId, onclose }: { queryId?: string | null; onclose: () => void } = $props();
	let loadState = $state<GraphState>({ kind: 'loading' });
	let mounted = $state(false);
	let selectedId = $state<string | null>(null);
	let technical = $state(false);
	let expanded = $state.raw(new Set<string>());
	// Hand-moved node positions for the current proof and view (see graph-positions.ts).
	let positions = $state.raw<Positions>({});
	let layoutVersion = $state(0); // bumped by Reset layout to remount the canvas
	let closeButton: HTMLButtonElement;
	const loader = createGraphLoader(getProofGraph, (next) => {
		loadState = next;
		if (next.kind === 'ready') {
			technical = false;
			positions = loadPositions(positionsKey(next.graph.query_id, false));
			reset(next.graph.root_node_id);
		}
	});
	onMount(() => { mounted = true; closeButton?.focus(); return loader.cancel; });
	$effect(() => { void loader.load(queryId); return loader.cancel; });
	const saved = $derived(loadState.kind === 'ready' ? loadState.graph : null);
	const overview = $derived(saved ? theoremView(saved) : null);
	const graph = $derived(technical ? saved : overview);
	const visible = $derived(graph ? visibleGraph(graph, expanded) : null);
	const visibleIds = $derived(new Set(visible?.nodes.map((n) => n.node_id)));
	const selected = $derived(graph?.nodes.find((n) => n.node_id === selectedId));

	function reset(root: string) {
		selectedId = root;
		expanded = new Set([root]);
	}
	function toggleBranch(id: string) {
		const next = new Set(expanded);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		expanded = next;
	}
	function setTechnical(on: boolean, graph: { query_id: string; root_node_id: string }) {
		technical = on;
		positions = loadPositions(positionsKey(graph.query_id, on));
		reset(graph.root_node_id);
	}
	function moved(next: Positions) {
		positions = next;
		if (saved) savePositions(positionsKey(saved.query_id, technical), next);
	}
	function resetLayout() {
		positions = {};
		if (saved) savePositions(positionsKey(saved.query_id, technical), {});
		layoutVersion++;
	}
	function select(id: string) {
		if (!visibleIds.has(id) && selectedId) expanded = new Set([...expanded, selectedId]);
		selectedId = id;
	}
</script>

<section class="flex h-full min-h-0 flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-sm" aria-label="Dependency graph panel" data-proof-graph>
	<header class="flex items-start gap-3 border-b border-line px-5 py-4">
		<div class="min-w-0 flex-1"><h2 class="font-semibold text-ink">Dependency graph</h2><p class="mt-1 text-xs text-ink-2">{technical ? 'A → B means A references B' : 'A → B means the proof of A uses B directly'}</p></div>
		<button bind:this={closeButton} type="button" onclick={onclose} class="rounded-lg px-3 py-1 text-sm text-ink-2 hover:bg-sunken" aria-label="Close dependency graph">Close</button>
	</header>
	<div class="min-h-0 flex-1 overflow-y-auto">
		{#if isMockMode}<p class="border-b border-line bg-warn-soft px-5 py-2 text-xs text-warn">Demo graph — illustrative data, not extracted from this proof.</p>{/if}
		{#if loadState.kind === 'loading'}<p class="p-6 text-sm text-muted" role="status">Loading dependency graph…</p>
		{:else if loadState.kind === 'building'}<p class="p-6 text-sm text-muted" role="status">Building dependency graph with Lean…</p>
		{:else if loadState.kind === 'unsaved'}<p class="p-6 text-sm text-muted">A saved proof is needed to load its graph.</p>
		{:else if loadState.kind === 'unavailable' || loadState.kind === 'error'}
			<div class="p-6">
				<p class="text-sm text-ink-2" role="status">{loadState.kind === 'error' ? loadState.message : 'This proof has no saved dependency graph.'}</p>
				{#if loadState.kind === 'unavailable' || (loadState.kind === 'error' && loadState.retryable)}
					<button type="button" class="mt-3 rounded-lg border border-line px-3 py-1.5 text-sm text-accent" onclick={() => loader.load(queryId, true)}>
						{loadState.kind === 'unavailable' ? 'Build dependency graph' : 'Retry graph'}
					</button>
				{/if}
			</div>
		{:else if saved}
			<div class="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3 text-xs">
				<button type="button" aria-pressed={technical} class="rounded-md border border-line px-2 py-1 text-accent aria-pressed:bg-accent-soft" onclick={() => setTechnical(!technical, saved)}>
					Technical details
				</button>
				{#if visible}
				<span class="text-muted">{visible.nodes.length} {technical ? 'technical' : 'proof'} {visible.nodes.length === 1 ? 'node' : 'nodes'} shown</span>
					{#if selected?.depends_on_ids?.length && selected.node_id !== saved.root_node_id}
						<button type="button" class="text-accent underline" onclick={() => toggleBranch(selected.node_id)}>
							{expanded.has(selected.node_id) ? 'Collapse dependencies' : 'Expand dependencies'}
						</button>
					{/if}
					{#if expanded.size > 1}
						<button type="button" class="text-accent underline" onclick={() => reset(saved.root_node_id)}>Reset view</button>
					{/if}
					{#if Object.keys(positions).length}
						<button type="button" class="text-accent underline" onclick={resetLayout}>Reset layout</button>
					{/if}
				{/if}
			</div>
			<p class="border-b border-line px-5 py-2 text-[11px] text-muted">Drag a node to move it · drag the background to pan · Shift-drag to select several</p>
			{#if graph && visible}
				{#if mounted}
					{#key JSON.stringify([graph.query_id, technical, layoutVersion, ...expanded])}
						<GraphCanvas graph={visible} {selectedId} onselect={select} {positions} onmove={moved} />
					{/key}
				{/if}
				<div class="border-t border-line px-5 py-3">
					<label class="text-xs text-ink-2" for="graph-declaration">Go to {technical ? 'declaration' : 'theorem or lemma'}</label>
					<select id="graph-declaration" class="mt-1 w-full rounded-lg border border-line bg-surface p-2 font-mono text-xs text-ink" value={selectedId ?? ''} onchange={(e) => select(e.currentTarget.value)}>
						{#each visible.nodes as n (n.node_id)}<option value={n.node_id}>{nodeLabel(n)}</option>{/each}
					</select>
				</div>
				{#if selected}<NodeDetail {graph} {visibleIds} node={selected} onselect={select} />{/if}
			{:else}
				<div class="p-6">
					<p class="text-sm text-ink-2">Update this saved graph to see its theorem and lemma dependencies.</p>
					<button type="button" class="mt-3 rounded-lg border border-line px-3 py-1.5 text-sm text-accent" onclick={() => loader.load(queryId, true)}>Update graph</button>
				</div>
			{/if}
		{/if}
	</div>
</section>
