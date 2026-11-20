<script lang="ts">
	import type { LiveItem } from '#lib/types.js';
	import { liveProse, toolLabel } from '#lib/format.js';
	import RichText from './RichText.svelte';

	/** Shared rendering of an agent timeline: used live (while streaming, with a spinner on a
	 * running tool) and, collapsed, in the finished message's "How this was checked" section
	 * (where nothing is ever `running`). */
	let { items }: { items: LiveItem[] } = $props();
</script>

<ol class="space-y-2">
	{#each items as item, i (i)}
		<li>
			{#if item.kind === 'text'}
				{@const prose = liveProse(item.text)}
				{#if prose}
					<RichText text={prose} class="text-ink-2" />
				{/if}
			{:else}
				<div class="flex items-center gap-2">
					<span class="grid size-4 shrink-0 place-items-center" aria-hidden="true">
						{#if item.state === 'running'}
							<span class="size-2 animate-pulse rounded-full bg-accent"></span>
						{:else if item.state === 'ok'}
							<span class="text-ok">✓</span>
						{:else}
							<span class="text-warn">✗</span>
						{/if}
					</span>
					<span class="text-ink-2">{toolLabel(item.name)}</span>
					{#if item.target}
						<span class="truncate font-mono text-xs text-muted">{item.target}</span>
					{/if}
				</div>
			{/if}
		</li>
	{/each}
</ol>
