---
name: vue-component-audit
description: Analyze Vue 3 component structure for performance issues and code-reuse opportunities, and produce a prioritized, file:line report of concrete refactors. Use when asked to audit, review, or optimize Vue components/views for performance or duplication.
---

# Vue Component Audit

Guidelines for auditing this app's Vue 3 Composition API code (`client/src/`) and producing a prioritized, actionable report — not for making the edits yourself. If the user then asks you to apply fixes, delegate any `.vue` file changes to the **vue-expert** subagent per the project's `CLAUDE.md` (mandatory for creating/modifying `.vue` files).

## Before you start

Read `client/CLAUDE.md` and `.claude/agents/vue-expert.md` first. Don't re-flag patterns they already establish as intentional (e.g. inventory has no month filter by design, `v-show` vs `v-if` tradeoffs, the loading/error/data template shape). This skill exists to find *deviations* from those patterns and *cross-file* duplication, not to restate the style guide.

## Scope

- Target: `client/src/views/*.vue`, `client/src/components/*.vue`, `client/src/composables/*.js`
- Read each file **in full** before judging it — don't infer behavior from filename or a partial grep match
- Out of scope: `server/` (that's vue-expert's boundary too — state backend requirements instead of touching them)
- If the user names specific files/views, audit only those; otherwise enumerate all of the above

## Performance checklist

For each item, note the detection signal and what a fix looks like.

1. **Method calls in templates** — `{{ someFn() }}` or `:prop="someFn()"` where the value doesn't depend on an event. Runs every re-render; should be a `computed`.
2. **Index-as-key in `v-for`** — `:key="index"` instead of a stable id (`sku`, `id`, `month`). Breaks reordering/removal.
3. **Un-debounced reactive search/filter inputs** — a `watch`/`watchEffect` on a text `ref` that fires an API call or heavy filter on every keystroke, with no `watchDebounced` or manual debounce.
4. **Recomputed-in-place derived data** — filtering/mapping/reducing a `ref` inside `onMounted`, a method, or a `watch` callback and storing the result in another `ref`, instead of a `computed`. Doubles the state to keep in sync and won't auto-update.
5. **`v-if` on frequently toggled elements** that would read better as `v-show` (repeated mount/unmount cost), and the inverse: `v-show` on rarely-shown, expensive-to-render content that would read better as `v-if`.
6. **New object/array/function literals passed as props** — `:style="{ color: x }"`, `:options="[...]"`, `@click="() => fn(x)"` written inline in the template. New reference every render; hoist to a `computed` or method reference.
7. **`ref()` around data that's never reassigned** — static lookup tables, constant option lists — adds reactivity overhead for nothing.
8. **Whole-array/object replacement via deeply reactive state** — an API response assigned wholesale into a `ref`/`reactive` that's never mutated in place is a candidate for `shallowRef` (avoids deep-proxying large JSON payloads like `orders` or `inventory_items`).
9. **Chart/SVG geometry recomputed inline in the template** rather than in a `computed` — check every `views/*.vue` with an inline `<svg>` (this app hand-rolls charts, no library).
10. **Duplicate API calls for the same data** from sibling components/views in the same navigation, instead of sharing state through a composable.
11. **Missing date validation before `.getMonth()`/`.getTime()`** — a known project pitfall (see `client/CLAUDE.md`); check every `new Date(...)` call site.

## Code-reuse checklist

1. **Repeated data-loading boilerplate** — `loading`/`error`/`data` refs plus a try/catch/finally `loadData()`, copy-pasted across `views/*.vue` instead of a shared composable (e.g. a hypothetical `useAsyncData(fetcher)`).
2. **Filter logic duplicated outside `useFilters`** — a view re-implementing warehouse/category/status/month filtering client-side instead of relying on the composable + API query params.
3. **Formatting logic not routed through `utils/currency.js`** — inline `toLocaleString(...)`/manual `$` string-building instead of the shared helper.
4. **Near-identical modal components** — `BacklogDetailModal.vue`, `CostDetailModal.vue`, `InventoryDetailModal.vue`, `ProductDetailModal.vue`, `ProfileDetailsModal.vue` are prime suspects for a shared modal shell (backdrop, close button, transition) with just the body content swapped in via a slot.
5. **Copy-pasted SVG chart scaffolding** across views — shared `viewBox` setup, axis-drawing, or color-scale logic that could become one small chart composable/component.
6. **Repeated inline `axios` calls outside `api.js`** — every HTTP call should go through the single client; flag any component that imports `axios` directly.
7. **Copy-pasted validation snippets** (date checks, empty-state checks) that appear 3+ times — that's the threshold for "extract it," not 1–2 (don't over-abstract a one-off).

## Workflow

1. Enumerate target files (or use the user's named subset).
2. Read each file fully; walk both checklists per file, noting `file:line` and a short snippet for anything real.
3. Cluster reuse findings *across* files — a pattern repeated in 3+ places is a strong finding; 1–2 occurrences is a passing note, not a recommendation.
4. Rank everything: **Critical** (measurable perf/UX impact, e.g. unbounded re-render loop, broken date handling) → **Moderate** (duplication across 3+ files, avoidable re-computation) → **Minor** (style/consistency, low-traffic view).
5. Write the report (format below). Don't edit files unless asked; if asked, hand `.vue` edits to **vue-expert**.

## Report format

```markdown
# Vue Component Audit

**Files analyzed:** [list or count]

## Performance

### Critical
1. **[Issue]** — `path/File.vue:line`
   - Problem: ...
   - Impact: ...
   - Fix: [short code example]

### Moderate
...

### Minor
...

## Code Reuse

1. **[Pattern]** — appears in `A.vue:12`, `B.vue:30`, `C.vue:8`
   - Suggested extraction: [composable/component name + shape]

## Suggested Extractions
- `composables/useX.js` — replaces duplicated logic in [files]
- `components/Y.vue` — replaces near-identical modals [files]

## Summary
[2-3 sentences: overall health, top 1-2 things worth doing first]
```

## Constraints

- This is a demo app with small, fixed mock datasets — don't recommend virtualization, pagination, or heavy memoization infra for lists that are currently a few dozen rows. Note it as "worth revisiting if data volume grows," not an actionable fix.
- No emojis in the report's *code suggestions* or in any UI-facing text you propose — that's a hard project rule for the app itself. (Emoji in your own report formatting, if any, is fine.)
- Don't flag `client/CLAUDE.md`-documented tradeoffs (e.g. Options vs Composition API choice, scoped CSS over a CSS framework) as issues — those are settled decisions, not audit findings.
