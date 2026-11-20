<script lang="ts">
	import type { VerificationStatus } from '#lib/types.js';

	let { status }: { status: VerificationStatus } = $props();

	const META = {
		verified: { label: 'Verified in Lean 4', cls: 'bg-ok-soft text-ok', icon: '✓' },
		unverified: { label: 'Not yet verified', cls: 'bg-warn-soft text-warn', icon: '○' },
		failed: { label: 'Verification incomplete', cls: 'bg-warn-soft text-warn', icon: '!' }
	} as const;

	const m = $derived(META[status]);
</script>

<span class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium {m.cls}">
	<span aria-hidden="true">{m.icon}</span>{m.label}
</span>
