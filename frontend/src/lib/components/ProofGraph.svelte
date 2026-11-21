<script lang="ts">
	import { SvelteFlow, Controls, Background, MarkerType, type Node, type Edge } from '@xyflow/svelte';
	import '@xyflow/svelte/style.css';
	import type { ProofGraph } from '#lib/types.js';
	import { layoutGraph, nodeLabel } from '#lib/graph.js';
	import DeclarationNode from './ProofGraphNode.svelte';
	let { graph, selectedId, onselect }: { graph: ProofGraph; selectedId: string | null; onselect: (id: string) => void } = $props();
	const nodeTypes = { declaration: DeclarationNode };
	let nodes = $state.raw<Node[]>([]);
	let edges = $state.raw<Edge[]>([]);
	const layout = $derived(layoutGraph(graph));
	$effect(() => {
		const neighbours = new Set(layout.edges.filter((e) => e.source === selectedId || e.target === selectedId).flatMap((e) => [e.source, e.target]));
		nodes = layout.nodes.map((n) => ({ ...n, selected: n.id === selectedId, ariaLabel: nodeLabel(n.data.node), data: { ...n.data, related: neighbours.has(n.id) } }));
		edges = layout.edges.map((e) => ({
			...e,
			markerEnd: { type: MarkerType.ArrowClosed, color: 'var(--c-ink-2)' },
			style: `stroke: ${e.source === selectedId || e.target === selectedId ? 'var(--c-accent)' : 'var(--c-muted)'}; stroke-width: 2;`,
			ariaLabel: `${e.source} depends on ${e.target}`
		}));
	});
</script>

<div class="graph-canvas h-[360px] min-h-[280px] w-full shrink-0 bg-paper lg:h-[420px]" data-proof-graph>
	<SvelteFlow {nodes} {edges} {nodeTypes} fitView minZoom={0.15} maxZoom={2}
		nodesDraggable={false} nodesConnectable={false} deleteKey={null}
		onnodeclick={({ node }) => onselect(node.id)}
		onselectionchange={({ nodes: selected }) => { if (selected[0] && selected[0].id !== selectedId) onselect(selected[0].id); }}>
		<Background gap={20} />
		<Controls showLock={false} />
	</SvelteFlow>
</div>

<style>
	.graph-canvas { --xy-background-color: var(--c-paper); --xy-controls-button-background-color: var(--c-surface); --xy-controls-button-color: var(--c-ink); --xy-controls-button-border-color: var(--c-line); }
</style>
