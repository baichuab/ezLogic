<script lang="ts">
	import { highlightLean } from '#lib/format.js';

	let {
		source,
		file = 'Proof.lean',
		highlight,
		verified = false
	}: {
		source: string;
		file?: string;
		/** 1-based inclusive line range to emphasise. */
		highlight?: [number, number];
		verified?: boolean;
	} = $props();

	const lines = $derived(highlightLean(source));
	let scroller: HTMLDivElement | undefined = $state();
	let copied = $state(false);

	const inRange = (n: number) => !!highlight && n >= highlight[0] && n <= highlight[1];

	// Keep the highlighted lines in view when the step changes.
	$effect(() => {
		const start = highlight?.[0];
		if (!scroller || !start) return;
		const el = scroller.querySelector<HTMLElement>(`[data-line="${start}"]`);
		if (!el) return;
		const top = el.offsetTop - scroller.clientHeight / 3;
		scroller.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
	});

	async function copy() {
		await navigator.clipboard?.writeText(source);
		copied = true;
		setTimeout(() => (copied = false), 1200);
	}
</script>

<div class="overflow-hidden rounded-xl border border-black/20 bg-code-bg text-code-ink shadow-sm">
	<div class="flex items-center gap-2 border-b border-white/5 px-4 py-2 text-xs">
		<span class="font-mono text-code-ink/80">{file}</span>
		{#if verified}
			<span class="rounded-full bg-emerald-400/10 px-2 py-0.5 text-emerald-300">✓ compiles</span>
		{/if}
		{#if highlight}
			<span class="text-code-ink/50">
				· lines {highlight[0]}{highlight[1] !== highlight[0] ? `–${highlight[1]}` : ''}
			</span>
		{/if}
		<button
			type="button"
			onclick={copy}
			class="ml-auto rounded px-2 py-1 text-code-ink/70 transition hover:bg-white/10 hover:text-code-ink"
		>
			{copied ? 'Copied' : 'Copy'}
		</button>
	</div>
	<div bind:this={scroller} class="max-h-80 overflow-auto py-2 font-mono text-[13px] leading-6">
		{#each lines as line, i (i)}
			{@const n = i + 1}
			<div
				data-line={n}
				class="flex pr-4 {inRange(n) ? 'bg-code-hl' : highlight ? 'opacity-55' : ''}"
			>
				<span
					class="w-11 shrink-0 select-none pr-3 text-right text-code-ink/30 {inRange(n)
						? 'border-l-2 border-accent text-code-ink/70'
						: 'border-l-2 border-transparent'}">{n}</span
				>
				<span class="whitespace-pre">{@html line || ' '}</span>
			</div>
		{/each}
	</div>
</div>
