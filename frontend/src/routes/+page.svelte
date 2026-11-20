<script lang="ts">
	import { tick } from 'svelte';
	import { fade, fly } from 'svelte/transition';
	import { isMockMode, sendMessage } from '#lib/api.js';
	import { demoChats } from '#lib/mock.js';
	import type { AssistantMessage, Chat } from '#lib/types.js';
	import Brace from '#lib/components/Brace.svelte';
	import Composer from '#lib/components/Composer.svelte';
	import ProofSteps from '#lib/components/ProofSteps.svelte';
	import Sidebar from '#lib/components/Sidebar.svelte';
	import StepDetail from '#lib/components/StepDetail.svelte';

	// ---- state ---------------------------------------------------------------
	let chats = $state<Chat[]>(demoChats());
	let activeId = $state<string | null>(chats[0]?.id ?? null);
	let selection = $state<{ messageId: string; stepId: string } | null>(null);
	let showLean = $state(false);
	let sidebarPinned = $state(true);
	let drawerOpen = $state(false);
	let busy = $state(false);
	let error = $state<{ text: string; message: string } | null>(null);

	const active = $derived(chats.find((c) => c.id === activeId) ?? null);
	const selectedMessage = $derived(
		selection && active
			? (active.messages.find(
					(m): m is AssistantMessage => m.role === 'assistant' && m.id === selection!.messageId
				) ?? null)
			: null
	);
	const selectedIndex = $derived(
		selectedMessage ? selectedMessage.steps.findIndex((s) => s.id === selection!.stepId) : -1
	);
	const selectedStep = $derived(selectedMessage?.steps[selectedIndex] ?? null);
	const expanded = $derived(!!selectedStep);
	/** The sidebar docks only when no step is expanded (sketch state 3 collapses it to ≡). */
	const sidebarDocked = $derived(sidebarPinned && !expanded);

	// ---- actions -------------------------------------------------------------
	function selectStep(messageId: string, stepId: string) {
		if (selection?.messageId === messageId && selection.stepId === stepId) {
			selection = null;
			return;
		}
		selection = { messageId, stepId };
		drawerOpen = false;
	}

	function closeDetail() {
		selection = null;
	}

	function openChat(id: string) {
		activeId = id;
		selection = null;
		drawerOpen = false;
		error = null;
	}

	function newChat() {
		activeId = null;
		selection = null;
		drawerOpen = false;
		error = null;
	}

	async function send(text: string) {
		error = null;
		let chat = active;
		if (!chat) {
			chat = {
				id: `c-${Date.now().toString(36)}`,
				title: text.length > 48 ? text.slice(0, 47) + '…' : text,
				messages: [],
				history: [],
				updatedAt: Date.now()
			};
			chats.unshift(chat);
			activeId = chat.id;
			chat = chats[0];
		}
		chat.messages.push({ id: `u-${Date.now().toString(36)}`, role: 'user', text });
		scrollToBottom();

		busy = true;
		try {
			const res = await sendMessage(text, chat.history);
			chat.messages.push(res.message);
			chat.history = res.history;
			chat.updatedAt = Date.now();
			scrollToBottom();
		} catch (e) {
			error = { text, message: e instanceof Error ? e.message : String(e) };
		} finally {
			busy = false;
		}
	}

	function retry() {
		if (!error || !active) return;
		const { text } = error;
		const lastMsg = active.messages.at(-1);
		if (lastMsg?.role === 'user' && lastMsg.text === text) active.messages.pop();
		send(text);
	}

	// ---- scrolling & brace geometry -----------------------------------------
	let scroller: HTMLDivElement | undefined = $state();
	let braceEl: HTMLDivElement | undefined = $state();
	let brace = $state({ tipY: 0, height: 0 });

	async function scrollToBottom() {
		await tick();
		scroller?.scrollTo({ top: scroller.scrollHeight, behavior: 'smooth' });
	}

	function measureBrace() {
		if (!braceEl || !scroller || !selection) return;
		const card = scroller.querySelector<HTMLElement>(
			`[data-step-key="${selection.messageId}:${selection.stepId}"]`
		);
		const box = braceEl.getBoundingClientRect();
		if (!card) return;
		const r = card.getBoundingClientRect();
		brace = { tipY: r.top + r.height / 2 - box.top, height: box.height };
	}

	// Re-measure when the selection or layout changes; bring the card into view.
	$effect(() => {
		if (!selection || !braceEl) return;
		const key = `${selection.messageId}:${selection.stepId}`;
		tick().then(() => {
			scroller
				?.querySelector<HTMLElement>(`[data-step-key="${key}"]`)
				?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
			measureBrace();
		});
		const ro = new ResizeObserver(measureBrace);
		ro.observe(braceEl);
		if (scroller) ro.observe(scroller);
		return () => ro.disconnect();
	});

	function onkeydown(e: KeyboardEvent) {
		const t = e.target as HTMLElement;
		if (t.closest('textarea, input')) return;
		if (e.key === 'Escape') {
			if (drawerOpen) drawerOpen = false;
			else if (selection) closeDetail();
			return;
		}
		if (!selectedMessage || selectedIndex < 0) return;
		const dir = e.key === 'ArrowDown' || e.key === 'j' ? 1 : e.key === 'ArrowUp' || e.key === 'k' ? -1 : 0;
		const target = selectedMessage.steps[selectedIndex + dir];
		if (dir && target) {
			e.preventDefault();
			selection = { messageId: selectedMessage.id, stepId: target.id };
		}
	}

	const EXAMPLES = [
		'Prove that √2 is irrational',
		'Show there are infinitely many primes',
		'Prove 0 + 1 + ⋯ + n = n(n+1)/2'
	];
</script>

<svelte:window {onkeydown} />

<div class="flex h-dvh overflow-hidden">
	{#if sidebarDocked}
		<div class="hidden md:block" transition:fly={{ x: -24, duration: 160 }}>
			<Sidebar
				{chats}
				{activeId}
				onselect={openChat}
				onnew={newChat}
				oncollapse={() => (sidebarPinned = false)}
			/>
		</div>
	{/if}

	<main class="relative flex min-w-0 flex-1 flex-col">
		<!-- Top bar -->
		<header class="flex h-14 shrink-0 items-center gap-2 px-3">
			<button
				type="button"
				onclick={() => (drawerOpen = true)}
				class="grid size-9 place-items-center rounded-lg text-ink-2 transition hover:bg-sunken hover:text-ink
				{sidebarDocked ? 'md:hidden' : ''}"
				aria-label="Open chat history"
				title="Chat history"
			>
				<svg viewBox="0 0 20 20" class="size-5" fill="none" stroke="currentColor" stroke-width="1.7">
					<path d="M3.5 5.5h13M3.5 10h13M3.5 14.5h13" stroke-linecap="round" />
				</svg>
			</button>
			<h1 class="truncate text-sm font-medium text-ink-2">
				{active?.title ?? 'New proof'}
			</h1>
			{#if isMockMode}
				<span
					class="ml-auto rounded-full border border-line px-2.5 py-0.5 text-xs text-muted"
					title="Set VITE_API_URL to connect to the backend agent">Demo data</span
				>
			{/if}
		</header>

		<!-- Conversation + detail split -->
		<div class="flex min-h-0 flex-1 gap-0 px-3 lg:px-4">
			<section
				class="flex min-h-0 min-w-0 flex-col transition-[width] duration-200
				{expanded ? 'w-full lg:w-[400px] lg:shrink-0 xl:w-[440px]' : 'w-full'}"
			>
				<div
					bind:this={scroller}
					onscroll={measureBrace}
					class="min-h-0 flex-1 overflow-y-auto [scrollbar-gutter:stable]"
				>
					{#if !active || active.messages.length === 0}
						<!-- Sketch state 1: empty chat -->
						<div class="mx-auto flex h-full max-w-2xl flex-col items-center justify-center px-4 pb-10 text-center">
							<p class="font-serif text-4xl text-ink" aria-hidden="true">∀ ∃ ⊢</p>
							<h2 class="mt-4 text-2xl font-semibold tracking-tight">What would you like to prove?</h2>
							<p class="mt-2 max-w-md text-sm text-ink-2">
								Describe a theorem or paste a proof sketch. ezLogic formalises it in Lean, checks it,
								and explains each step.
							</p>
							<div class="mt-6 flex flex-wrap justify-center gap-2">
								{#each EXAMPLES as ex (ex)}
									<button
										type="button"
										onclick={() => send(ex)}
										class="rounded-full border border-line bg-surface px-3.5 py-1.5 text-sm text-ink-2 transition hover:border-line-strong hover:text-ink"
									>
										{ex}
									</button>
								{/each}
							</div>
						</div>
					{:else}
						<!-- Sketch state 2: chat with proof blocks -->
						<div class="mx-auto space-y-8 py-4 {expanded ? 'max-w-none pr-1' : 'max-w-3xl px-1'}">
							{#each active.messages as msg (msg.id)}
								{#if msg.role === 'user'}
									<div class="flex justify-end">
										<p
											class="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-sunken px-4 py-2.5 text-[15px] leading-6 text-ink"
										>
											{msg.text}
										</p>
									</div>
								{:else}
									<ProofSteps
										message={msg}
										compact={expanded}
										selectedStepId={selection?.messageId === msg.id ? (selection?.stepId ?? null) : null}
										onselect={(stepId) => selectStep(msg.id, stepId)}
									/>
								{/if}
							{/each}

							{#if busy}
								<div class="flex items-center gap-3 pl-11 text-sm text-ink-2" in:fade>
									<span class="flex gap-1" aria-hidden="true">
										<span class="size-1.5 animate-bounce rounded-full bg-muted"></span>
										<span class="size-1.5 animate-bounce rounded-full bg-muted [animation-delay:120ms]"></span>
										<span class="size-1.5 animate-bounce rounded-full bg-muted [animation-delay:240ms]"></span>
									</span>
									Writing and checking the Lean proof…
								</div>
							{/if}

							{#if error}
								<div
									class="ml-11 flex items-center gap-3 rounded-xl border border-warn/30 bg-warn-soft px-4 py-3 text-sm text-warn"
									role="alert"
								>
									<span class="flex-1">{error.message}</span>
									<button type="button" onclick={retry} class="font-medium underline underline-offset-2">
										Retry
									</button>
								</div>
							{/if}
						</div>
					{/if}
				</div>
			</section>

			{#if expanded && selectedMessage && selectedStep}
				<!-- Sketch state 3: brace + thorough explanation -->
				<div bind:this={braceEl} class="relative hidden w-10 shrink-0 justify-center pt-4 pb-2 lg:flex">
					<Brace tipY={brace.tipY - 16} height={Math.max(0, brace.height - 24)} />
				</div>
				<div
					class="fixed inset-0 z-30 bg-paper p-3 lg:static lg:z-auto lg:min-w-0 lg:flex-1 lg:bg-transparent lg:p-0 lg:pb-2 lg:pt-1"
					in:fly={{ x: 24, duration: 200 }}
				>
					<StepDetail
						message={selectedMessage}
						step={selectedStep}
						index={selectedIndex}
						bind:showLean
						onclose={closeDetail}
						onstep={(stepId) => selectStep(selectedMessage.id, stepId)}
					/>
				</div>
			{/if}
		</div>

		<!-- Composer: present in every state -->
		<div class="shrink-0 px-4 pb-4 pt-2">
			<div class="mx-auto max-w-3xl">
				<Composer {busy} onsend={send} />
				<p class="mt-2 text-center text-[11px] text-muted">
					Proofs are checked by Lean 4. Explanations are AI-generated.
				</p>
			</div>
		</div>
	</main>

	<!-- Chat history drawer (used when the sidebar is collapsed) -->
	{#if drawerOpen}
		<div class="fixed inset-0 z-40 flex">
			<button
				type="button"
				class="absolute inset-0 bg-black/25"
				aria-label="Close chat history"
				onclick={() => (drawerOpen = false)}
				transition:fade={{ duration: 120 }}
			></button>
			<div class="relative h-full shadow-xl" transition:fly={{ x: -260, duration: 180 }}>
				<Sidebar
					{chats}
					{activeId}
					onselect={openChat}
					onnew={newChat}
					oncollapse={() => {
						drawerOpen = false;
					}}
				/>
			</div>
			{#if !sidebarPinned && !expanded}
				<button
					type="button"
					onclick={() => {
						sidebarPinned = true;
						drawerOpen = false;
					}}
					class="relative ml-2 mt-3 h-fit rounded-lg bg-surface px-3 py-1.5 text-xs text-ink-2 shadow"
				>
					Keep open
				</button>
			{/if}
		</div>
	{/if}
</div>
