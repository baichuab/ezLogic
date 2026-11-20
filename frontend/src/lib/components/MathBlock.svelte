<script lang="ts">
	import { tex } from '#lib/format.js';

	let { src, display = true, class: cls = '' }: { src: string; display?: boolean; class?: string } =
		$props();

	const html = $derived(tex(src, display));
</script>

<span class="math-block block {cls}">{@html html}</span>
