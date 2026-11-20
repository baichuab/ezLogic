<script lang="ts">
	/**
	 * A tall curly brace whose point tracks the selected card.
	 * `tipY` is measured from the top of this element.
	 */
	let { tipY = 0, height = 0 }: { tipY?: number; height?: number } = $props();

	const W = 26;
	const M = W / 2;
	const R = 12;
	const PAD = 8;

	const path = $derived.by(() => {
		const H = Math.max(height - PAD * 2, 4 * R + 2);
		const y = Math.min(Math.max(tipY - PAD, 2 * R), H - 2 * R);
		return [
			`M ${W} 0`,
			`Q ${M} 0 ${M} ${R}`,
			`L ${M} ${y - R}`,
			`Q ${M} ${y} 1 ${y}`,
			`Q ${M} ${y} ${M} ${y + R}`,
			`L ${M} ${H - R}`,
			`Q ${M} ${H} ${W} ${H}`
		].join(' ');
	});
</script>

{#if height > 0}
	<svg
		width={W + 2}
		{height}
		viewBox="-1 {-PAD} {W + 2} {height}"
		fill="none"
		aria-hidden="true"
		class="text-line-strong"
	>
		<path
			d={path}
			stroke="currentColor"
			stroke-width="1.6"
			stroke-linecap="round"
			stroke-linejoin="round"
			style:d={`path("${path}")`}
			style:transition="d 220ms cubic-bezier(.2,.8,.2,1)"
		/>
	</svg>
{/if}
