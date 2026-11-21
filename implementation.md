# Draggable proof-graph nodes and canvas: implementation plan

## Goal
The dependency graph (`@xyflow/svelte` + dagre, on the `draggable` branch) should support:
- dragging a single node;
- dragging empty space to pan the whole graph;
- shift-dragging a box to select several nodes, then dragging them together.

Moved positions are kept **per proof, in the browser** (localStorage). They survive
expand/collapse, selection changes and page reloads. A **Reset layout** button puts the
automatic layout back.

## What the code does today
- [ProofGraph.svelte](frontend/src/lib/components/ProofGraph.svelte):
  - Passes `nodesDraggable={false}` and passes `{nodes}` one way (not `bind:nodes`), so a drag
    would never be written back.
  - An `$effect` rebuilds `nodes` from `layoutGraph(graph)` whenever `selectedId` changes, so
    any moved position would be reset on the next click.
  - `onselectionchange` calls `onselect(selected[0].id)`, so a box selection would jump the
    detail panel to whichever node happens to be first.
- [ProofGraphPanel.svelte](frontend/src/lib/components/ProofGraphPanel.svelte) wraps the
  canvas in `{#key JSON.stringify([graph.query_id, technical, ...expanded])}`. Expanding or
  collapsing a branch remounts the canvas, so positions must live outside it.
- [graph.ts](frontend/src/lib/graph.ts): `layoutGraph` gives the dagre positions
  (`NODE_WIDTH`/`NODE_HEIGHT`). It stays the source of default positions and isn't changed.
- Panning is already on (xyflow's `panOnDrag` default). Once nodes are draggable, xyflow
  handles shift-drag box selection (`selectionKey` default `Shift`) and moves all selected
  nodes together.

## Changes

### 1. New `frontend/src/lib/graph-positions.ts`
Pure helpers, testable in vitest's node environment:
- `type Positions = Record<string, { x: number; y: number }>`.
- `positionsKey(queryId, technical)` returns `ezlogic:graph-layout:v1:<queryId>:<proof|technical>`.
- `loadPositions(key, storage = globalThis.localStorage)`:
  - wraps the read in try/catch;
  - drops entries that aren't finite numbers;
  - returns `{}` on any failure (private mode, blocked storage, SSR).
- `savePositions(key, positions, storage)` saves, or removes the key when `positions` is
  empty. It wraps the write in try/catch.
- `applyPositions(layoutNodes, saved)` overrides `position` only for ids present in both.
  The rest keep their dagre spot.
- `movedPositions(nodes, layoutNodes)` keeps only nodes whose position differs from the auto
  layout, so storage stays small and "reset" is meaningful.

### 2. `ProofGraph.svelte` (canvas)
- New props: `positions: Positions` and `onmove: (p: Positions) => void`.
- Build the initial nodes once per mount:
  `applyPositions(layoutGraph(graph).nodes, positions)`.
- Change the selection `$effect` so it only patches `selected` and `data.related` on the
  current nodes. It maps over the existing `nodes`, read with `untrack`, and never resets
  `position`.
- Switch to `bind:nodes`, and set:
  - `nodesDraggable`;
  - `panOnDrag`;
  - `selectionKey="Shift"`;
  - `multiSelectionKey` left at the default (Ctrl/Meta click adds to the selection).
  Keep `nodesConnectable={false}` and `deleteKey={null}`, so a drag can't create or delete
  anything.
- Persist moves:
  - On `onnodedragstop`, call `onmove(movedPositions(nodes, layout.nodes))`.
  - Arrow-key moves of a selected node also change `nodes`, so a debounced (300 ms)
    `$effect` on node positions calls the same `onmove`.
- `onselectionchange`: call `onselect` only when exactly one node is selected, so a box
  selection doesn't change the detail panel. `onnodeclick` is unchanged. xyflow doesn't fire
  a click after a drag past its 1 px `nodeDragThreshold`.

### 3. `ProofGraphPanel.svelte`
- State: `positions = $state.raw<Positions>({})` and `layoutVersion = $state(0)`.
- Load `positions` from storage when the graph becomes ready and when **Technical details** is
  toggled. The proof and technical views get separate keys, because they show different
  nodes.
- Pass `{positions}` and `onmove={(p) => { positions = p; savePositions(key, p); }}` to
  `GraphCanvas`.
- Add a **Reset layout** button to the toolbar, shown when any node has been moved. It clears
  storage, sets `positions = {}`, and bumps `layoutVersion`.
- Add `layoutVersion` to the `{#key …}` expression so the canvas remounts with dagre
  positions.
- Add a hint under the header: "Drag to move · Shift-drag to select several".

### 4. `ProofGraphNode.svelte`
Add `cursor-grab active:cursor-grabbing` to the card. Nothing else changes; the handles stay
non-connectable.

## Known behaviour
- A newly revealed node (from expanding a branch) appears at its dagre spot, so it can overlap
  a node that was moved by hand. Reset layout fixes it.
- Box selection needs a keyboard (Shift). On touch you can still drag single nodes and pan.
- Saved positions for nodes that no longer exist are ignored. After the proof changes, the
  remaining moved nodes keep their spot.

## Tests
New `frontend/src/lib/graph-positions.test.ts` with an in-memory `Storage` stub. It checks:
- save → load round-trips;
- an empty save removes the key;
- a storage that throws gives `{}`;
- non-finite and garbage values are dropped;
- `applyPositions` only overrides known ids;
- `movedPositions` ignores unmoved nodes.

`graph.test.ts` is unchanged, since `layoutGraph` isn't touched.

## Verification
1. `cd frontend && npm install`. `@xyflow/svelte` isn't in `node_modules` on this checkout yet.
2. Run `npm run test` and `npm run check`.
3. Run the frontend with `VITE_MOCK=1` (mock graph from `mock.ts`). `.claude/launch.json`
   sources `~/.nvm/nvm.sh`, which may not exist on Windows; if so, add a plain
   `npm run dev` config. Then check, in order:
   - drag a node;
   - click another node (the dragged one stays put);
   - expand and collapse a branch (the position is kept);
   - reload (the position is kept);
   - shift-drag a box over two nodes and drag them together;
   - drag empty space to pan;
   - use Reset layout (back to dagre);
   - toggle Technical details (separate layout).

## Files
- New: `frontend/src/lib/graph-positions.ts`, `frontend/src/lib/graph-positions.test.ts`.
- Edit: `frontend/src/lib/components/ProofGraph.svelte`, `ProofGraphPanel.svelte`,
  `ProofGraphNode.svelte`.
