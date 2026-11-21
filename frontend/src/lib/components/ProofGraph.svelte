<script lang="ts">
	import { untrack } from 'svelte';
	import { SvelteFlow, Controls, Background, MarkerType, type Node, type Edge } from '@xyflow/svelte';
	import '@xyflow/svelte/style.css';
	import type { ProofGraph } from '#lib/types.js';
	import { layoutGraph, nodeLabel } from '#lib/graph.js';
	import { applyPositions, mergePositions, movedPositions, samePositions, type Positions } from '#lib/graph-positions.js';
	import DeclarationNode from './ProofGraphNode.svelte';
	let { graph, selectedId, onselect, positions, onmove }: {
		graph: ProofGraph;
		selectedId: string | null;
		onselect: (id: string) => void;
		/** Hand-moved positions to start from (the panel remounts this canvas to apply new ones). */
		positions: Positions;
		/** Called with the full saved set after nodes are moved. */
		onmove: (positions: Positions) => void;
	} = $props();
	const nodeTypes = { declaration: DeclarationNode };
	const layout = $derived(layoutGraph(graph));
	// Positions are set once per mount; after that xyflow owns them through bind:nodes.
	let nodes = $state.raw<Node[]>(untrack(() => applyPositions(layout.nodes, positions)));
	let edges = $state.raw<Edge[]>([]);

	// Selection only restyles nodes and edges; it never touches positions.
	$effect(() => {
		const neighbours = new Set(layout.edges.filter((e) => e.source === selectedId || e.target === selectedId).flatMap((e) => [e.source, e.target]));
		nodes = untrack(() => nodes).map((n) => ({ ...n, selected: n.id === selectedId, ariaLabel: nodeLabel(n.data.node as ProofGraph['nodes'][number]), data: { ...n.data, related: neighbours.has(n.id) } }));
		edges = layout.edges.map((e) => ({
			...e,
			markerEnd: { type: MarkerType.ArrowClosed, color: 'var(--c-ink-2)' },
			style: `stroke: ${e.source === selectedId || e.target === selectedId ? 'var(--c-accent)' : 'var(--c-muted)'}; stroke-width: 2;`,
			ariaLabel: `${e.source} depends on ${e.target}`
		}));
	});

	let saved = untrack(() => positions);
	function persist() {
		const onScreen = new Set(layout.nodes.map((n) => n.id));
		const next = mergePositions(saved, movedPositions(nodes, layout.nodes), onScreen);
		if (samePositions(next, saved)) return;
		saved = next;
		onmove(next);
	}
	// Drags save on drop (below); this also catches arrow-key moves of a selected node.
	$effect(() => {
		void nodes;
		const timer = setTimeout(persist, 300);
		return () => clearTimeout(timer);
	});
</script>

<div class="graph-canvas h-[360px] min-h-[280px] w-full shrink-0 bg-paper lg:h-[420px]" data-proof-graph>
	<SvelteFlow bind:nodes {edges} {nodeTypes} fitView minZoom={0.15} maxZoom={2}
		nodesDraggable panOnDrag selectionKey="Shift" nodesConnectable={false} deleteKey={null}
		onnodedragstop={persist} onselectiondragstop={persist}
		onnodeclick={({ node, event }) => { if (!(event.ctrlKey || event.metaKey || event.shiftKey)) onselect(node.id); }}
		onselectionchange={({ nodes: picked }) => { if (picked.length === 1 && picked[0].id !== selectedId) onselect(picked[0].id); }}>
		<Background gap={20} />
		<Controls showLock={false} />
	</SvelteFlow>
</div>

<style>
	.graph-canvas { --xy-background-color: var(--c-paper); --xy-controls-button-background-color: var(--c-surface); --xy-controls-button-color: var(--c-ink); --xy-controls-button-border-color: var(--c-line); }
</style>
