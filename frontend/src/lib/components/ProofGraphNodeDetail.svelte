<script lang="ts">
	import type { ProofGraph, ProofGraphNode } from '#lib/types.js';
	import { nodeLabel, usedBy } from '#lib/graph.js';
	import LeanCode from './LeanCode.svelte';
	import RichText from './RichText.svelte';
	let { graph, visibleIds, node, onselect }: { graph: ProofGraph; visibleIds: ReadonlySet<string>; node: ProofGraphNode; onselect: (id: string) => void } = $props();
	const byId = $derived(new Map(graph.nodes.map((n) => [n.node_id, n])));
	const incoming = $derived(usedBy(graph, node.node_id).filter((parent) => visibleIds.has(parent.node_id)));
</script>

<section class="border-t border-line px-5 py-4" aria-label="Selected declaration" aria-live="polite">
	<p class="text-xs font-medium uppercase tracking-wider text-muted">Selected declaration</p>
	<h3 class="mt-1 break-all font-mono text-sm font-semibold text-ink">{nodeLabel(node)}</h3>
	{#if node.statement}<div class="mt-3"><LeanCode source={node.statement} file="Declaration statement" /></div>{/if}
	{#if node.explanation}<div class="mt-3"><p class="text-xs text-muted">Explanation (not verification evidence)</p><RichText text={node.explanation} /></div>{/if}
	<div class="mt-4 grid gap-4 sm:grid-cols-2">
		<div><h4 class="text-xs font-semibold text-ink-2">Depends on</h4>
			{#if node.depends_on_ids === null}<p class="mt-1 text-sm text-muted">Dependencies not extracted</p>
			{:else if !node.depends_on_ids.length}<p class="mt-1 text-sm text-muted">No direct dependencies</p>
			{:else}<ul class="mt-1 space-y-1">{#each node.depends_on_ids as id (id)}<li><button type="button" class="break-all text-left font-mono text-xs text-accent underline underline-offset-2" onclick={() => onselect(id)}>{nodeLabel(byId.get(id)!)}</button></li>{/each}</ul>{/if}
		</div>
		<div><h4 class="text-xs font-semibold text-ink-2">Used by (in this view)</h4>
			{#if !incoming.length}<p class="mt-1 text-sm text-muted">No incoming references</p>
			{:else}<ul class="mt-1 space-y-1">{#each incoming as parent (parent.node_id)}<li><button type="button" class="break-all text-left font-mono text-xs text-accent underline underline-offset-2" onclick={() => onselect(parent.node_id)}>{nodeLabel(parent)}</button></li>{/each}</ul>{/if}
		</div>
	</div>
</section>
