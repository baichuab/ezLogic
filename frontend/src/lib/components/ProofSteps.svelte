<script lang="ts">
	import type { AssistantMessage } from '#lib/types.js';
	import { KIND_LABEL } from '#lib/format.js';
	import MathBlock from './MathBlock.svelte';
	import RichText from './RichText.svelte';
	import StatusBadge from './StatusBadge.svelte';

	let {
		message,
		selectedStepId = null,
		compact = false,
		onselect
	}: {
		message: AssistantMessage;
		selectedStepId?: string | null;
		compact?: boolean;
		onselect: (stepId: string) => void;
	} = $props();

	const last = $derived(message.steps.length - 1);
	/** Vertical offset of each timeline node from the top of its card. */
	const NODE_Y = 26;
</script>

<div class="space-y-3">
	<div class="flex flex-wrap items-center gap-x-3 gap-y-1 {compact ? 'pl-9' : 'pl-11'}">
		<StatusBadge status={message.status} />
		{#if message.intro && !compact}
			<p class="text-sm text-ink-2">{message.intro}</p>
		{/if}
	</div>

	<ol aria-label="Proof steps">
		{#each message.steps as step, i (step.id)}
			{@const selected = step.id === selectedStepId}
			<li class="relative flex {i < last ? 'pb-3' : ''}">
				<!-- Timeline: a continuous rail with one node per step -->
				<div class="relative shrink-0 {compact ? 'w-9' : 'w-11'}" aria-hidden="true">
					<span
						class="absolute left-1/2 w-px -translate-x-1/2 bg-line-strong"
						style:top={i === 0 ? `${NODE_Y}px` : '0'}
						style:bottom={i === last ? `calc(100% - ${NODE_Y}px)` : '0'}
					></span>
					<span
						class="absolute left-1/2 grid -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border-[1.5px] font-mono transition
						{compact ? 'size-5 text-[10px]' : 'size-6 text-[11px]'}
						{selected
							? 'border-accent bg-accent text-white'
							: 'border-line-strong bg-paper text-muted'}"
						style:top="{NODE_Y}px">{i + 1}</span
					>
				</div>

				<button
					type="button"
					data-step-key="{message.id}:{step.id}"
					onclick={() => onselect(step.id)}
					aria-expanded={selected}
					aria-label="Step {i + 1}: {step.title}. Open details"
					class="group relative min-w-0 flex-1 rounded-2xl border-2 bg-surface text-left transition
					{compact ? 'px-4 py-3' : 'px-5 py-4'}
					{selected
						? 'border-accent shadow-[0_0_0_4px_var(--c-accent-soft)]'
						: 'border-line hover:border-line-strong hover:shadow-sm'}"
				>
					<div class="mb-1 flex items-center gap-2 text-[11px] font-medium uppercase tracking-wider">
						<span class={selected ? 'text-accent' : 'text-muted'}>{KIND_LABEL[step.kind]}</span>
						{#if step.title && step.title.toLowerCase() !== (KIND_LABEL[step.kind] ?? '').toLowerCase()}
							<span class="truncate normal-case tracking-normal text-ink-2">· {step.title}</span>
						{/if}
						<span
							class="ml-auto shrink-0 normal-case tracking-normal text-muted opacity-0 transition group-hover:opacity-100 group-focus-visible:opacity-100
							{selected ? 'opacity-100!' : ''}"
						>
							{selected ? 'Open' : 'Expand'}
							<span aria-hidden="true">→</span>
						</span>
					</div>

					{#if step.statementTex}
						<MathBlock
							src={step.statementTex}
							class="py-1 text-center text-ink {compact ? 'text-[0.82rem]' : 'text-[0.98rem]'}"
						/>
					{/if}

					<RichText
						text={step.summary}
						class="mt-1 text-ink-2 {compact
							? 'line-clamp-2 text-[13px] leading-5'
							: 'line-clamp-3 text-sm leading-6'}"
					/>
				</button>
			</li>
		{/each}
	</ol>
</div>
