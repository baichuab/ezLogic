<script lang="ts">
	import { Handle, Position, type NodeProps, type Node } from '@xyflow/svelte';
	import type { ProofGraphNode } from '#lib/types.js';
	import { nodeLabel } from '#lib/graph.js';
	let { data, selected }: NodeProps<Node<{ node: ProofGraphNode; root: boolean; related?: boolean }>> = $props();
</script>

<Handle type="target" position={Position.Top} isConnectable={false} />
<div class="flex h-full w-full flex-col justify-center rounded-xl border-2 px-4 py-2 shadow-sm
	{selected ? 'border-accent bg-accent-soft' : data.related ? 'border-accent bg-surface' : 'border-line-strong bg-surface'}">
	<p class="text-[10px] font-semibold uppercase tracking-wider text-muted">{data.root ? 'Root theorem' : data.node.kind === 'theorem' ? 'Theorem or lemma' : 'Declaration'}</p>
	<p class="truncate font-mono text-sm text-ink" title={nodeLabel(data.node)}>{nodeLabel(data.node)}</p>
	<p class="mt-1 text-[11px] text-ink-2">{data.node.depends_on_ids === null ? 'Dependencies not extracted' : `${data.node.depends_on_ids.length} direct dependencies`}</p>
</div>
<Handle type="source" position={Position.Bottom} isConnectable={false} />
