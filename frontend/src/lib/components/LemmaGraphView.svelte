<script lang="ts">
	import { onDestroy } from 'svelte';
	import { expandLemmaGraph, getLemmaGraph } from '#lib/api.js';
	import {
		graphStats,
		layoutGraph,
		mergeExpansion,
		neighbourhood,
		nodeTone,
		type GraphLayout,
		type NodeTone
	} from '#lib/graph.js';
	import type { AssistantMessage, LemmaGraph, LemmaNode } from '#lib/types.js';
	import LeanCode from './LeanCode.svelte';

	let { message, onclose }: { message: AssistantMessage; onclose: () => void } = $props();

	const uid = $props.id();
	const DEPTHS = [1, 2, 3, 4, 5];
	/** How far one "expand" follows a node. */
	const EXPAND_DEPTH = 2;
	/** "Expand all" is offered up to this many truncated nodes. */
	const EXPAND_ALL_MAX = 30;
	/** The smallest zoom the automatic fit uses: below it, node names can't be read. */
	const MIN_READABLE = 0.6;

	let depth = $state(3);
	let showAxioms = $state(true);
	let graph = $state<LemmaGraph | null>(null);
	let loading = $state(false);
	let error = $state<string | null>(null);
	let expanding = $state(new Set<string>());
	let selectedId = $state<string | null>(null);

	let controller: AbortController | null = null;
	onDestroy(() => controller?.abort());

	async function load() {
		const lean = message.lean;
		if (!lean) return;
		controller?.abort();
		const c = (controller = new AbortController());
		loading = true;
		error = null;
		try {
			const g = await getLemmaGraph(lean, { depth }, c.signal);
			if (c.signal.aborted) return;
			graph = g;
			selectedId = null;
			needsFit = true;
		} catch (e) {
			if (c.signal.aborted) return;
			error = e instanceof Error ? e.message : String(e);
		} finally {
			if (controller === c) loading = false;
		}
	}

	// (Re)load when the proof or the depth changes.
	$effect(() => {
		void message.lean;
		void depth;
		load();
	});

	async function expand(ids: string[]) {
		if (!graph || !ids.length) return;
		const todo = ids.filter((id) => !expanding.has(id));
		if (!todo.length) return;
		expanding = new Set([...expanding, ...todo]);
		try {
			const sub = await expandLemmaGraph(todo, { depth: EXPAND_DEPTH });
			if (graph) {
				graph = mergeExpansion(graph, sub);
				needsFit = true; // the whole graph is laid out again
			}
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			expanding = new Set([...expanding].filter((id) => !todo.includes(id)));
		}
	}

	const stats = $derived(graph ? graphStats(graph) : null);
	const truncatedIds = $derived(graph ? graph.nodes.filter((n) => n.truncated).map((n) => n.id) : []);
	const laid: GraphLayout | null = $derived(graph ? layoutGraph(graph, { showAxioms }) : null);
	const byId = $derived(new Map((graph?.nodes ?? []).map((n) => [n.id, n])));
	const selected = $derived(selectedId ? (byId.get(selectedId) ?? null) : null);
	const near = $derived(graph && selectedId ? neighbourhood(graph, selectedId) : null);
	const usesOfSelected = $derived(
		graph && selectedId ? graph.edges.filter((e) => e.src === selectedId).map((e) => byId.get(e.dst)!).filter(Boolean) : []
	);
	const usedBySelected = $derived(
		graph && selectedId ? graph.edges.filter((e) => e.dst === selectedId).map((e) => byId.get(e.src)!).filter(Boolean) : []
	);

	// ---- pan & zoom ----------------------------------------------------------
	let viewport: HTMLDivElement | undefined = $state();
	let view = $state({ x: 0, y: 0, k: 1 });
	let needsFit = false;
	let drag = $state<{ x: number; y: number; vx: number; vy: number; id: number } | null>(null);

	/**
	 * Fit the whole graph in view. With `readable`, don't shrink names past legibility (narrow
	 * screens, big graphs): keep a minimum zoom and start at the top, centred on the proof's own
	 * theorems; the rest is a pan away.
	 */
	function fit(readable = false) {
		if (!viewport || !laid) return;
		const w = viewport.clientWidth;
		const h = viewport.clientHeight;
		if (!w || !h || !laid.width) return;
		const whole = Math.min(1.1, Math.max(0.12, Math.min(w / laid.width, h / laid.height) * 0.95));
		const k = readable ? Math.max(whole, MIN_READABLE) : whole;
		if (k === whole) {
			view = { k, x: (w - laid.width * k) / 2, y: Math.max(8, (h - laid.height * k) / 2) };
			return;
		}
		const roots = laid.nodes.filter((p) => p.node.depth === 0);
		const cx = roots.length ? roots.reduce((s, p) => s + p.x, 0) / roots.length : laid.width / 2;
		view = { k, x: w / 2 - cx * k, y: 12 };
	}

	$effect(() => {
		if (laid && viewport && needsFit) {
			needsFit = false;
			fit(true);
		}
	});

	function zoomBy(factor: number, px?: number, py?: number) {
		if (!viewport) return;
		const cx = px ?? viewport.clientWidth / 2;
		const cy = py ?? viewport.clientHeight / 2;
		const k = Math.min(2.5, Math.max(0.12, view.k * factor));
		const r = k / view.k;
		view = { k, x: cx - (cx - view.x) * r, y: cy - (cy - view.y) * r };
	}

	function onwheel(e: WheelEvent) {
		e.preventDefault();
		const box = viewport!.getBoundingClientRect();
		zoomBy(Math.exp(-e.deltaY * 0.0015), e.clientX - box.left, e.clientY - box.top);
	}

	function onpointerdown(e: PointerEvent) {
		if ((e.target as Element).closest('[data-node]')) return;
		drag = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, id: e.pointerId };
		(e.currentTarget as Element).setPointerCapture(e.pointerId);
	}

	function onpointermove(e: PointerEvent) {
		if (!drag || drag.id !== e.pointerId) return;
		view = { ...view, x: drag.vx + e.clientX - drag.x, y: drag.vy + e.clientY - drag.y };
	}

	function onpointerup(e: PointerEvent) {
		if (drag?.id === e.pointerId) drag = null;
	}

	/** Select a node and bring it into view. */
	function focus(id: string) {
		selectedId = id;
		const p = laid?.nodes.find((n) => n.node.id === id);
		if (!p || !viewport) return;
		const w = viewport.clientWidth;
		const h = viewport.clientHeight;
		const sx = view.x + p.x * view.k;
		const sy = view.y + p.y * view.k;
		if (sx < 40 || sx > w - 40 || sy < 40 || sy > h - 40) {
			view = { ...view, x: w / 2 - p.x * view.k, y: h / 3 - p.y * view.k };
		}
	}

	function onnodekey(e: KeyboardEvent, id: string) {
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			selectedId = id;
		}
	}

	// ---- styling -------------------------------------------------------------
	const TONE: Record<NodeTone, { fill: string; stroke: string; text: string }> = {
		local: { fill: 'var(--c-accent)', stroke: 'var(--c-accent)', text: '#fff' },
		'local-error': { fill: 'var(--c-warn-soft)', stroke: 'var(--c-warn)', text: 'var(--c-warn)' },
		mathlib: { fill: 'var(--c-surface)', stroke: 'var(--c-line-strong)', text: 'var(--c-ink)' },
		core: { fill: 'var(--c-sunken)', stroke: 'var(--c-line-strong)', text: 'var(--c-ink-2)' },
		axiom: { fill: 'var(--c-ok-soft)', stroke: 'var(--c-ok)', text: 'var(--c-ok)' },
		sorry: { fill: 'var(--c-warn-soft)', stroke: 'var(--c-warn)', text: 'var(--c-warn)' }
	};

	const ORIGIN_LABEL: Record<LemmaNode['origin'], string> = {
		local: 'Your proof',
		mathlib: 'Mathlib',
		core: 'Lean core',
		batteries: 'Batteries',
		other: 'Library'
	};

	function kindLabel(n: LemmaNode): string {
		if (n.kind === 'axiom') return n.id === 'sorryAx' ? 'Unproven (sorry)' : 'Axiom';
		if (n.kind === 'example') return 'Example';
		if (n.class_field) return 'Class axiom';
		return 'Theorem';
	}
</script>

<article
	class="flex h-full min-h-0 flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-[0_1px_2px_rgba(0,0,0,0.04),0_16px_40px_-24px_rgba(0,0,0,0.25)]"
	aria-labelledby="{uid}-title"
>
	<header class="flex flex-wrap items-start gap-x-3 gap-y-2 border-b border-line px-5 pb-3 pt-4">
		<div class="min-w-0 flex-1">
			<p class="text-xs font-medium uppercase tracking-wider text-accent">Lemma dependencies</p>
			<h2 id="{uid}-title" class="mt-0.5 text-lg font-semibold tracking-tight text-ink">
				What this proof relies on
			</h2>
			{#if stats}
				<p class="mt-0.5 text-xs text-muted">
					{stats.theorems} theorem{stats.theorems === 1 ? '' : 's'} ({stats.library} from libraries) ·
					{stats.axioms} axiom{stats.axioms === 1 ? '' : 's'} · {stats.depth} level{stats.depth === 1 ? '' : 's'} deep
					{#if stats.truncated}· {stats.truncated} not yet expanded{/if}
				</p>
			{/if}
		</div>
		<div class="flex items-center gap-2 text-xs">
			<label class="flex items-center gap-1.5 text-ink-2">
				Depth
				<select
					bind:value={depth}
					disabled={loading}
					class="rounded-md border border-line-strong bg-surface px-1.5 py-1 text-ink"
				>
					{#each DEPTHS as d (d)}<option value={d}>{d}</option>{/each}
				</select>
			</label>
			<label class="flex items-center gap-1.5 text-ink-2">
				<input type="checkbox" bind:checked={showAxioms} class="accent-[var(--c-accent)]" />
				Axioms
			</label>
			<button
				type="button"
				onclick={onclose}
				aria-label="Close dependency graph"
				class="grid size-8 place-items-center rounded-full text-muted transition hover:bg-sunken hover:text-ink"
			>
				<svg viewBox="0 0 20 20" class="size-4" fill="none" stroke="currentColor" stroke-width="1.8">
					<path d="M5 5l10 10M15 5L5 15" stroke-linecap="round" />
				</svg>
			</button>
		</div>
	</header>

	<!-- Canvas -->
	<div class="relative min-h-0 flex-1 bg-paper">
		{#if loading && !graph}
			<div class="absolute inset-0 grid place-items-center p-6 text-center">
				<div>
					<p class="text-sm text-ink-2">Asking Lean for the dependency chain…</p>
					<p class="mt-1 text-xs text-muted">The first graph after a server start loads Mathlib, which can take a minute.</p>
				</div>
			</div>
		{:else if error && !graph}
			<div class="absolute inset-0 grid place-items-center p-6 text-center" role="alert">
				<div>
					<p class="text-sm text-warn">Couldn't build the graph: {error}</p>
					<button type="button" onclick={load} class="mt-2 text-sm font-medium text-accent underline underline-offset-2">
						Retry
					</button>
				</div>
			</div>
		{:else if graph && laid}
			{#if graph.nodes.length === 0}
				<p class="absolute inset-0 grid place-items-center p-6 text-center text-sm text-ink-2">
					Lean found no theorems in this proof to start from.
				</p>
			{/if}
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div
				bind:this={viewport}
				class="absolute inset-0 touch-none overflow-hidden {drag ? 'cursor-grabbing' : 'cursor-grab'}"
				{onwheel}
				{onpointerdown}
				{onpointermove}
				{onpointerup}
				onpointercancel={onpointerup}
			>
				<svg class="block h-full w-full select-none" role="img" aria-label="Directed graph of lemma dependencies">
					<defs>
						{#each [['uses', 'var(--c-line-strong)'], ['axiom', 'var(--c-ok)'], ['out', 'var(--c-accent)'], ['in', 'var(--c-ink-2)']] as [name, color] (name)}
							<marker
								id="{uid}-arrow-{name}"
								viewBox="0 0 10 10"
								refX="9"
								refY="5"
								markerWidth="7"
								markerHeight="7"
								orient="auto-start-reverse"
							>
								<path d="M0,1 L9,5 L0,9 z" style:fill={color} />
							</marker>
						{/each}
					</defs>
					<g transform="translate({view.x},{view.y}) scale({view.k})">
						{#each laid.edges as { edge, path } (`${edge.src}>${edge.dst}>${edge.kind}`)}
							{@const out = selectedId === edge.src}
							{@const inn = selectedId === edge.dst}
							{@const dim = !!selectedId && !out && !inn}
							<path
								d={path}
								fill="none"
								stroke-width={out || inn ? 1.8 : 1.1}
								stroke-dasharray={edge.kind === 'axiom' ? '4 3' : undefined}
								style:stroke={out ? 'var(--c-accent)' : inn ? 'var(--c-ink-2)' : edge.kind === 'axiom' ? 'var(--c-ok)' : 'var(--c-line-strong)'}
								opacity={dim ? 0.18 : edge.kind === 'axiom' && !out && !inn ? 0.55 : 1}
								marker-end="url(#{uid}-arrow-{out ? 'out' : inn ? 'in' : edge.kind})"
							/>
						{/each}

						{#each laid.nodes as p (p.node.id)}
							{@const n = p.node}
							{@const tone = TONE[nodeTone(n)]}
							{@const isSel = n.id === selectedId}
							{@const dim = !!near && !near.has(n.id)}
							<g
								data-node={n.id}
								role="button"
								tabindex="0"
								aria-label="{kindLabel(n)} {n.label}{n.truncated ? ', not expanded' : ''}"
								aria-pressed={isSel}
								transform="translate({p.x - p.width / 2},{p.y - p.height / 2})"
								opacity={dim ? 0.3 : 1}
								class="cursor-pointer outline-none"
								onclick={() => (selectedId = isSel ? null : n.id)}
								ondblclick={() => n.truncated && expand([n.id])}
								onkeydown={(e) => onnodekey(e, n.id)}
							>
								<title>{n.label}{n.statement ? `\n${n.statement}` : ''}</title>
								{#if isSel}
									<rect
										x="-4"
										y="-4"
										width={p.width + 8}
										height={p.height + 8}
										rx={n.kind === 'axiom' ? (p.height + 8) / 2 : 11}
										fill="none"
										stroke-width="3"
										style:stroke="var(--c-accent-soft)"
									/>
								{/if}
								<rect
									width={p.width}
									height={p.height}
									rx={n.kind === 'axiom' ? p.height / 2 : 8}
									stroke-width={isSel ? 2 : 1.2}
									stroke-dasharray={n.class_field ? '3 2' : undefined}
									style:fill={tone.fill}
									style:stroke={isSel ? 'var(--c-accent)' : tone.stroke}
								/>
								<text
									x={n.truncated ? (p.width - 16) / 2 : p.width / 2}
									y={p.height / 2}
									dominant-baseline="central"
									text-anchor="middle"
									class="font-mono {n.kind === 'axiom' ? 'text-[11px]' : 'text-[12px]'}"
									style:fill={tone.text}
								>
									{p.text}
								</text>
								{#if n.truncated}
									<!-- svelte-ignore a11y_click_events_have_key_events -->
									<g
										role="button"
										tabindex="-1"
										aria-label="Expand {n.label}"
										transform="translate({p.width - 19},{p.height / 2 - 8})"
										onclick={(e) => {
											e.stopPropagation();
											expand([n.id]);
										}}
									>
										<rect width="16" height="16" rx="8" style:fill="var(--c-accent-soft)" />
										<text
											x="8"
											y="8"
											dominant-baseline="central"
											text-anchor="middle"
											class="text-[12px] font-semibold"
											style:fill="var(--c-accent)">{expanding.has(n.id) ? '…' : '+'}</text
										>
									</g>
								{/if}
							</g>
						{/each}
					</g>
				</svg>
			</div>

			<!-- Controls -->
			<div class="absolute right-3 top-3 flex flex-col overflow-hidden rounded-lg border border-line bg-surface shadow-sm">
				<button type="button" class="size-8 text-ink-2 hover:bg-sunken" aria-label="Zoom in" onclick={() => zoomBy(1.25)}>+</button>
				<button type="button" class="size-8 border-t border-line text-ink-2 hover:bg-sunken" aria-label="Zoom out" onclick={() => zoomBy(0.8)}>−</button>
				<button type="button" class="size-8 border-t border-line text-[11px] text-ink-2 hover:bg-sunken" aria-label="Fit graph to view" onclick={() => fit()}>fit</button>
			</div>

			<!-- Legend -->
			<div class="pointer-events-none absolute bottom-2 left-3 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-ink-2">
				{#each [['local', 'Your proof'], ['mathlib', 'Mathlib'], ['core', 'Lean core'], ['axiom', 'Axiom'], ['sorry', 'Unproven / error']] as [tone, label] (tone)}
					{@const t = TONE[tone as NodeTone]}
					<span class="flex items-center gap-1">
						<span
							class="inline-block h-2.5 w-3.5 border {tone === 'axiom' || tone === 'sorry' ? 'rounded-full' : 'rounded-[3px]'}"
							style:background={t.fill}
							style:border-color={t.stroke}
						></span>
						{label}
					</span>
				{/each}
				<span class="flex items-center gap-1">
					<span class="inline-block h-2.5 w-3.5 rounded-[3px] border border-dashed border-line-strong"></span>
					Class axiom
				</span>
			</div>

			{#if truncatedIds.length && truncatedIds.length <= EXPAND_ALL_MAX}
				<button
					type="button"
					onclick={() => expand(truncatedIds)}
					disabled={expanding.size > 0}
					class="absolute left-3 top-3 rounded-full border border-line-strong bg-surface px-3 py-1 text-xs text-ink-2 shadow-sm transition hover:border-accent hover:text-accent disabled:opacity-50"
				>
					{expanding.size ? 'Expanding…' : `Expand all ${truncatedIds.length} +`}
				</button>
			{/if}
			{#if loading}
				<p class="absolute left-1/2 top-3 -translate-x-1/2 rounded-full bg-ink px-3 py-1 text-xs text-paper">Updating…</p>
			{/if}
		{/if}
	</div>

	{#if graph && (graph.notes.length || !graph.ok || error)}
		<div class="space-y-0.5 border-t border-warn/30 bg-warn-soft px-5 py-2 text-xs text-warn" role="status">
			{#if !graph.ok}
				<p>Lean reported problems with this proof: nodes in amber have errors or rely on <code>sorry</code>.</p>
			{/if}
			{#each graph.notes as note (note)}<p>{note}</p>{/each}
			{#if error}<p>{error}</p>{/if}
		</div>
	{/if}

	<!-- Details of the selected node -->
	{#if selected}
		<section class="max-h-[45%] shrink-0 overflow-y-auto border-t border-line px-5 py-4" aria-label="Selected lemma">
			<div class="flex flex-wrap items-baseline gap-x-2 gap-y-1">
				<h3 class="break-all font-mono text-[15px] font-semibold text-ink">{selected.label}</h3>
				<span class="rounded-full bg-sunken px-2 py-0.5 text-[11px] text-ink-2">{kindLabel(selected)}</span>
				<span class="rounded-full bg-sunken px-2 py-0.5 text-[11px] text-ink-2">{ORIGIN_LABEL[selected.origin]}</span>
				{#if selected.kind !== 'axiom' && selected.depth !== null}
					<span class="text-[11px] text-muted">
						{selected.depth === 0 ? 'in your proof' : `${selected.depth} step${selected.depth === 1 ? '' : 's'} from your proof`}
					</span>
				{/if}
			</div>
			{#if selected.module}
				<p class="mt-1 break-all font-mono text-[11px] text-muted">{selected.module}</p>
			{/if}
			{#if selected.statement}
				<pre class="mt-2 whitespace-pre-wrap break-words rounded-lg bg-sunken px-3 py-2 font-mono text-[12.5px] leading-5 text-ink">{selected.statement}</pre>
			{/if}
			{#if selected.class_field}
				<p class="mt-2 text-xs text-ink-2">
					A field of a class: an axiom of that algebraic structure, which every instance (ℕ, ℤ, ℝ, …) proves for itself.
				</p>
			{/if}

			{#if selected.truncated}
				<button
					type="button"
					onclick={() => expand([selected.id])}
					disabled={expanding.has(selected.id)}
					class="mt-3 rounded-full bg-accent px-3.5 py-1.5 text-xs font-medium text-white transition hover:opacity-90 disabled:opacity-50"
				>
					{expanding.has(selected.id) ? 'Expanding…' : 'Show what this relies on'}
				</button>
			{/if}

			{#if usesOfSelected.length || usedBySelected.length}
				<div class="mt-3 grid gap-3 sm:grid-cols-2">
					{#each [['Relies on', usesOfSelected], ['Used by', usedBySelected]] as [title, list] (title)}
						{@const items = list as LemmaNode[]}
						{#if items.length}
							<div>
								<p class="text-[11px] font-medium uppercase tracking-wider text-muted">{title} ({items.length})</p>
								<ul class="mt-1 space-y-0.5">
									{#each items as n (n.id)}
										<li>
											<button
												type="button"
												onclick={() => focus(n.id)}
												class="max-w-full truncate text-left font-mono text-[12px] text-accent hover:underline"
											>
												{n.label}
											</button>
										</li>
									{/each}
								</ul>
							</div>
						{/if}
					{/each}
				</div>
			{/if}

			{#if selected.axioms?.length && selected.kind !== 'axiom'}
				<p class="mt-3 text-xs text-ink-2">
					Axioms (<code>#print axioms</code>):
					{#each selected.axioms as a, i (a)}<code class={a === 'sorryAx' ? 'text-warn' : ''}>{a}</code>{i < selected.axioms.length - 1 ? ', ' : ''}{/each}
				</p>
			{:else if selected.axioms && selected.kind !== 'axiom'}
				<p class="mt-3 text-xs text-ink-2">Relies on no axioms at all.</p>
			{/if}

			{#if selected.origin === 'local' && selected.start_line && message.lean}
				<div class="mt-3">
					<LeanCode
						source={message.lean}
						file={message.leanFile}
						highlight={[selected.start_line, selected.end_line ?? selected.start_line]}
						verified={message.status === 'verified'}
					/>
				</div>
			{/if}
		</section>
	{/if}
</article>
