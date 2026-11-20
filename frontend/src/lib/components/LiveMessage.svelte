<script lang="ts">
	import type { AssistantMessage } from '#lib/types.js';
	import TimelineItems from './TimelineItems.svelte';

	/** A message that's still streaming, was stopped, or ended in an error: `message.live` must be set. */
	let { message, onretry }: { message: AssistantMessage; onretry: () => void } = $props();

	const live = $derived(message.live!);
</script>

<div class="space-y-3 pl-11">
	<div class="flex items-center gap-2 text-sm">
		{#if live.state === 'streaming'}
			<span class="flex gap-1" aria-hidden="true">
				<span class="size-1.5 animate-bounce rounded-full bg-muted"></span>
				<span class="size-1.5 animate-bounce rounded-full bg-muted [animation-delay:120ms]"></span>
				<span class="size-1.5 animate-bounce rounded-full bg-muted [animation-delay:240ms]"></span>
			</span>
			<span class="text-ink-2">Working…</span>
		{:else if live.state === 'stopped'}
			<span class="inline-flex items-center gap-1.5 rounded-full bg-sunken px-2.5 py-0.5 text-xs font-medium text-ink-2">
				<span aria-hidden="true">■</span>Stopped
			</span>
		{:else}
			<span class="inline-flex items-center gap-1.5 rounded-full bg-warn-soft px-2.5 py-0.5 text-xs font-medium text-warn">
				<span aria-hidden="true">!</span>Error
			</span>
		{/if}
	</div>

	{#if live.items.length > 0}
		<TimelineItems items={live.items} />
	{/if}

	{#if live.state === 'error'}
		<div
			class="flex items-center gap-3 rounded-xl border border-warn/30 bg-warn-soft px-4 py-3 text-sm text-warn"
			role="alert"
		>
			<span class="flex-1">{live.errorDetail ?? 'Something went wrong.'}</span>
			<button type="button" onclick={onretry} class="font-medium underline underline-offset-2">Retry</button>
		</div>
	{/if}
</div>
