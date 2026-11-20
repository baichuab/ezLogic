<script lang="ts">
	let {
		running = false,
		allowEmpty = false,
		onsend,
		onstop,
		placeholder = 'Type a theorem, proof sketch or question…'
	}: {
		/** True while a proof is being written/checked anywhere (only one run at a time is allowed). */
		running?: boolean;
		/** True when a file is attached and ready: lets Send fire with no typed text. */
		allowEmpty?: boolean;
		onsend: (text: string) => void;
		onstop?: () => void;
		placeholder?: string;
	} = $props();

	let text = $state('');
	let el: HTMLTextAreaElement | undefined = $state();

	function submit() {
		const t = text.trim();
		if ((!t && !allowEmpty) || running) return;
		onsend(t);
		text = '';
		queueMicrotask(resize);
	}

	function resize() {
		if (!el) return;
		el.style.height = 'auto';
		el.style.height = Math.min(el.scrollHeight, 200) + 'px';
	}

	function onkeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
			e.preventDefault();
			submit();
		}
	}
</script>

<form
	class="flex items-end gap-2 rounded-[1.6rem] border border-line-strong/70 bg-surface py-2 pl-5 pr-2 shadow-[0_1px_2px_rgba(0,0,0,0.04),0_8px_24px_-12px_rgba(0,0,0,0.12)] transition focus-within:border-ink-2/60"
	onsubmit={(e) => {
		e.preventDefault();
		submit();
	}}
>
	<textarea
		bind:this={el}
		bind:value={text}
		oninput={resize}
		{onkeydown}
		rows="1"
		disabled={running}
		placeholder={running ? 'A proof is currently running…' : placeholder}
		aria-label="Message"
		class="max-h-[200px] min-h-6 flex-1 resize-none self-center bg-transparent py-1.5 text-[15px] leading-6 text-ink outline-none placeholder:text-muted disabled:cursor-not-allowed"
	></textarea>
	<button
		type={running ? 'button' : 'submit'}
		onclick={running ? () => onstop?.() : undefined}
		disabled={!running && !text.trim() && !allowEmpty}
		class="grid size-9 shrink-0 place-items-center rounded-full bg-ink text-paper transition hover:opacity-85 disabled:cursor-not-allowed disabled:opacity-25"
		aria-label={running ? 'Stop' : 'Send'}
		title={running ? 'Stop' : 'Send'}
	>
		{#if running}
			<span class="size-3 rounded-sm bg-paper"></span>
		{:else}
			<svg viewBox="0 0 20 20" class="size-4" fill="none" stroke="currentColor" stroke-width="2">
				<path d="M10 16V4M5 9l5-5 5 5" stroke-linecap="round" stroke-linejoin="round" />
			</svg>
		{/if}
	</button>
</form>
