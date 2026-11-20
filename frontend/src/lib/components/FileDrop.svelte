<script lang="ts">
	import { ACCEPTED_EXTENSIONS, FileError, formatBytes, validateProofFile } from '#lib/extract.js';

	let {
		file = $bindable(null),
		error = $bindable(''),
		disabled = false
	}: { file?: File | null; error?: string; disabled?: boolean } = $props();

	let input: HTMLInputElement | undefined = $state();
	let dragging = $state(false);

	function pick(f: File | undefined) {
		if (!f) return;
		try {
			validateProofFile(f);
			file = f;
			error = '';
		} catch (e) {
			error = e instanceof FileError ? e.message : String(e);
		}
	}

	function clear() {
		file = null;
		error = '';
		if (input) input.value = '';
	}
</script>

<div class="space-y-1.5">
	{#if file}
		<div
			class="flex items-center gap-3 rounded-2xl border border-line-strong/70 bg-surface px-4 py-2.5 text-sm"
		>
			<svg viewBox="0 0 20 20" class="size-5 shrink-0 text-ink-2" fill="none" stroke="currentColor" stroke-width="1.6">
				<path d="M5 2.5h6.5L15 6v11.5H5z M11.5 2.5V6H15" stroke-linejoin="round" />
			</svg>
			<span class="min-w-0 flex-1 truncate text-ink">{file.name}</span>
			<span class="shrink-0 text-xs text-muted">{formatBytes(file.size)}</span>
			<button
				type="button"
				onclick={clear}
				{disabled}
				class="grid size-6 shrink-0 place-items-center rounded-full text-ink-2 transition hover:bg-sunken hover:text-ink disabled:opacity-40"
				aria-label="Remove file"
			>
				<svg viewBox="0 0 20 20" class="size-3.5" fill="none" stroke="currentColor" stroke-width="2">
					<path d="M5 5l10 10M15 5L5 15" stroke-linecap="round" />
				</svg>
			</button>
		</div>
	{:else}
		<button
			type="button"
			{disabled}
			onclick={() => input?.click()}
			ondragover={(e) => {
				e.preventDefault();
				dragging = true;
			}}
			ondragleave={() => (dragging = false)}
			ondrop={(e) => {
				e.preventDefault();
				dragging = false;
				pick(e.dataTransfer?.files[0]);
			}}
			class="flex w-full items-center justify-center gap-2 rounded-2xl border border-dashed px-4 py-3 text-sm transition disabled:opacity-40
			{dragging ? 'border-ink-2 bg-sunken text-ink' : 'border-line-strong/70 bg-surface text-ink-2 hover:border-ink-2/60 hover:text-ink'}"
		>
			<svg viewBox="0 0 20 20" class="size-4" fill="none" stroke="currentColor" stroke-width="1.8">
				<path d="M10 13V3m0 0L6 7m4-4l4 4M4 13v3.5h12V13" stroke-linecap="round" stroke-linejoin="round" />
			</svg>
			<span>
				Upload a proof <span class="text-muted">(.tex or .pdf, optional)</span> — click or drop a file
			</span>
		</button>
	{/if}

	<input
		bind:this={input}
		type="file"
		accept={ACCEPTED_EXTENSIONS.join(',')}
		class="hidden"
		onchange={(e) => {
			pick(e.currentTarget.files?.[0]);
			e.currentTarget.value = '';
		}}
	/>

	{#if error}
		<p class="px-2 text-xs text-warn" role="alert">{error}</p>
	{/if}
</div>
