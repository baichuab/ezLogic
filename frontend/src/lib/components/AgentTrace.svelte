<script lang="ts">
	import type { LiveItem } from '#lib/types.js';
	import { traceSummary } from '#lib/format.js';
	import TimelineItems from './TimelineItems.svelte';

	/** Collapsed "how this was checked" section on a finished message. Hidden when there's
	 * nothing to summarise (no trace was stored, e.g. a cache hit or a reloaded history turn). */
	let { items }: { items: LiveItem[] } = $props();

	const summary = $derived(traceSummary(items));
</script>

{#if summary}
	<details class="group">
		<summary
			class="flex cursor-pointer list-none items-center gap-1.5 text-xs text-muted transition hover:text-ink-2 [&::-webkit-details-marker]:hidden"
		>
			<span class="inline-block transition-transform group-open:rotate-90" aria-hidden="true">▸</span>
			How this was checked · {summary}
		</summary>
		<div class="mt-2 pl-4 text-sm">
			<TimelineItems {items} />
		</div>
	</details>
{/if}
