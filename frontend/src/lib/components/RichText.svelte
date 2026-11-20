<script lang="ts">
	import { paragraphs, segments } from '#lib/format.js';

	/**
	 * Prose with `$math$`, `$$display$$` and `code`. Blank lines separate paragraphs.
	 * Renders spans (displayed as blocks) so it can sit inside a <button>.
	 */
	let { text, class: cls = '' }: { text: string; class?: string } = $props();

	const paras = $derived(paragraphs(text).map(segments));
</script>

<span class="block {cls}">
	{#each paras as segs, i (i)}
		<span class="block">
			{#each segs as seg, j (j)}
				{#if seg.type === 'text'}{seg.value}{:else if seg.type === 'code'}<code
						class="rounded bg-sunken px-1 py-px font-mono text-[0.86em] text-ink">{seg.value}</code
					>{:else if seg.display}<span class="math-block my-2 block">{@html seg.html}</span
					>{:else}{@html seg.html}{/if}
			{/each}
		</span>
	{/each}
</span>
