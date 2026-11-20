<script lang="ts">
	import type { AssistantMessage, ProofStep } from '#lib/types.js';
	import { KIND_LABEL } from '#lib/format.js';
	import { slide } from 'svelte/transition';
	import LeanCode from './LeanCode.svelte';
	import MathBlock from './MathBlock.svelte';
	import RichText from './RichText.svelte';

	let {
		message,
		step,
		index,
		showLean = $bindable(false),
		onclose,
		onstep
	}: {
		message: AssistantMessage;
		step: ProofStep;
		index: number;
		showLean?: boolean;
		onclose: () => void;
		onstep: (stepId: string) => void;
	} = $props();

	const total = $derived(message.steps.length);
	const prev = $derived(message.steps[index - 1]);
	const next = $derived(message.steps[index + 1]);
	const hasLean = $derived(!!message.lean);

	let body: HTMLDivElement | undefined = $state();
	$effect(() => {
		void step.id;
		body?.scrollTo({ top: 0 });
	});
</script>

<article
	class="flex h-full min-h-0 flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-[0_1px_2px_rgba(0,0,0,0.04),0_16px_40px_-24px_rgba(0,0,0,0.25)]"
	aria-labelledby="step-title"
>
	<header class="flex items-start gap-3 border-b border-line px-6 pb-4 pt-5">
		<div class="min-w-0 flex-1">
			<p class="text-xs font-medium uppercase tracking-wider text-accent">
				Step {index + 1} of {total} · {KIND_LABEL[step.kind]}
			</p>
			<h2 id="step-title" class="mt-0.5 text-lg font-semibold tracking-tight text-ink">
				{step.title}
			</h2>
		</div>

		<button
			type="button"
			onclick={() => (showLean = !showLean)}
			disabled={!hasLean}
			aria-pressed={showLean}
			title={hasLean ? (showLean ? 'Hide Lean code' : 'Show Lean code') : 'No Lean code for this step'}
			class="flex h-9 items-center gap-1.5 rounded-full border px-3 font-mono text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-35
			{showLean
				? 'border-code-bg bg-code-bg text-code-ink'
				: 'border-line-strong text-ink hover:border-ink-2 hover:bg-sunken'}"
		>
			<span aria-hidden="true">&gt;_</span>
			<span class="font-sans text-xs font-medium">Lean</span>
		</button>
		<button
			type="button"
			onclick={onclose}
			class="grid size-9 place-items-center rounded-full text-muted transition hover:bg-sunken hover:text-ink"
			aria-label="Close explanation"
			title="Close (Esc)"
		>
			<svg viewBox="0 0 20 20" class="size-4" fill="none" stroke="currentColor" stroke-width="1.8">
				<path d="M5 5l10 10M15 5L5 15" stroke-linecap="round" />
			</svg>
		</button>
	</header>

	<div bind:this={body} class="min-h-0 flex-1 overflow-y-auto px-6 pb-8 pt-5">
		{#if step.statementTex}
			<MathBlock
				src={step.statementTex}
				class="rounded-xl bg-sunken px-4 py-4 text-center text-[1.15rem] text-ink"
			/>
		{/if}

		{#if showLean && message.lean}
			<div transition:slide={{ duration: 180 }} class="pt-4">
				<LeanCode
					source={message.lean}
					file={message.leanFile}
					highlight={step.leanLines}
					verified={message.status === 'verified'}
				/>
			</div>
		{/if}

		<h3 class="mb-2 mt-6 text-xs font-medium uppercase tracking-wider text-muted">
			Thorough explanation
		</h3>
		<RichText
			text={step.explanation}
			class="space-y-3.5 font-serif text-[16.5px] leading-[1.7] text-ink [&_code]:font-mono"
		/>
	</div>

	<footer class="flex items-center gap-2 border-t border-line px-4 py-2.5 text-sm">
		<button
			type="button"
			disabled={!prev}
			onclick={() => prev && onstep(prev.id)}
			class="flex min-w-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-ink-2 transition hover:bg-sunken hover:text-ink disabled:invisible"
		>
			<span aria-hidden="true">←</span>
			<span class="truncate">{prev?.title ?? ''}</span>
		</button>
		<span class="mx-auto hidden shrink-0 text-xs text-muted sm:block">↑ ↓ to move · Esc to close</span>
		<button
			type="button"
			disabled={!next}
			onclick={() => next && onstep(next.id)}
			class="flex min-w-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-ink-2 transition hover:bg-sunken hover:text-ink disabled:invisible"
		>
			<span class="truncate">{next?.title ?? ''}</span>
			<span aria-hidden="true">→</span>
		</button>
	</footer>
</article>
