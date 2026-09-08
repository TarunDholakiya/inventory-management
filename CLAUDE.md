# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Factory Inventory Management System Demo with GitHub integration - Full-stack application with Vue 3 frontend, Python FastAPI backend, and in-memory mock data (no database).

> ⚠️ **This repository and any fork you create are PUBLIC.** Do not commit credentials, internal hostnames, or private registry URLs. `client/.npmrc` pins the public npm registry and `client/package-lock.json` is gitignored to prevent locally-configured registries from leaking into commits — leave both in place.

## Critical Tool Usage Rules

### Subagents
Use the Task tool with these specialized subagents for appropriate tasks:

- **vue-expert**: Use for Vue 3 frontend features, UI components, styling, and client-side functionality
  - Examples: Creating components, fixing reactivity issues, performance optimization, complex state management
  - **MANDATORY RULE: ANY time you need to create or significantly modify a .vue file, you MUST delegate to vue-expert**
  - Scoped to `client/` only — it does not touch `server/` or API contracts
- **code-reviewer**: Use after writing significant code to review quality and best practices
- **security-auditor**: Fast review of changed files only for hardcoded secrets, XSS (`v-html`/`innerHTML`), and missing input validation
- **Explore**: Use for understanding codebase structure, searching for patterns, or answering questions about how components work
- **general-purpose**: Use for complex multi-step tasks or when other agents don't fit

### Skills
- **backend-api-test** skill: Use when writing or modifying tests in `tests/backend` directory with pytest and FastAPI TestClient
- **vue-component-audit** skill: Use when asked to audit, review, or optimize Vue components/views for performance or code duplication — produces a prioritized report, doesn't edit files itself

### MCP Tools
- **ALWAYS use GitHub MCP tools** (`mcp__github__*`) for ALL GitHub operations
  - Exception: Local branches only - use `git checkout -b` instead of `mcp__github__create_branch`
- **ALWAYS use Playwright MCP tools** (`mcp__playwright__*`) for browser testing
  - Test against: `http://localhost:3000` (frontend), `http://localhost:8001` (API)

### Custom Slash Commands
Defined in `.claude/commands/`:
- `/start` - Kill anything on ports 3000/8001, start both dev servers in background
- `/stop` - Kill processes on ports 3000/8001
- `/test` - Run the full test suite (backend pytest + any frontend/lint checks) with a report
- `/demo-branch` - Create `demo-branch` (auto-incrementing name if it already exists)
- `/reset-branch` - Discard the current feature branch and its PRs, return to `main`
- `/optimize` - Scan for and remove dead code/unused deps across client + server

### Hooks
`.claude/hooks/post-tool-use.sh` logs every tool call to `.claude/logs/tool-usage-YYYY-MM-DD.log` (see `.claude/hooks/README.md`). Non-blocking; useful for debugging agent behavior.

## Stack
- **Frontend**: Vue 3 + Composition API + Vite (port 3000)
- **Backend**: Python FastAPI (port 8001), managed with `uv`
- **Data**: JSON files in `server/data/` loaded once at startup via `server/mock_data.py` (no database — changes don't persist, restart reloads from disk)

## Quick Start

```bash
# One command (installs deps on first run)
./scripts/start.sh   # backend :8001, frontend :3000, stop with ./scripts/stop.sh

# Or manually:
cd server && uv venv && uv sync && uv run python main.py
cd client && npm install && npm run dev
```

## Tests

Backend has 51 pytest tests in `tests/backend/` (no frontend test suite exists yet).

```bash
cd tests
uv run pytest -v                                                        # all tests
uv run pytest backend/test_inventory.py -v                              # one file
uv run pytest backend/test_inventory.py::TestInventoryEndpoints -v      # one class
uv run pytest backend/test_inventory.py::TestInventoryEndpoints::test_get_all_inventory -v  # one test
uv run pytest --cov=../server --cov-report=html                         # with coverage
```

`tests/backend/conftest.py` provides the `client` fixture (FastAPI `TestClient` against `server/main.py`) plus `sample_inventory_item`/`sample_order` fixtures. See `.claude/skills/backend-api-test/SKILL.md` for the full test-writing conventions before adding new backend tests.

## Architecture

This is a two-directory monorepo (`client/`, `server/`) with **no shared code or types** between them — Pydantic models in `server/main.py` and the shapes consumed in `client/src` must be kept in sync by hand. Nested `CLAUDE.md` files exist per side and go deeper than this file:
- `client/CLAUDE.md` — Vue 3 Composition API patterns, composables, chart/styling conventions
- `server/CLAUDE.md` — FastAPI endpoint/model patterns, filtering conventions, mock data rules

**Data flow**: Vue filter state (`useFilters` composable) → `client/src/api.js` (axios, base URL hardcoded to `http://localhost:8001/api`) → FastAPI query params → in-memory list filtering in `server/main.py` → Pydantic response validation → Vue computed properties render it.

**Filter system**: Four filters — Time Period (month or quarter, e.g. `2025-01` / `Q1-2025`), Warehouse, Category, Order Status — are passed as query params and applied server-side via `apply_filters()`/`filter_by_month()` in `server/main.py`. Not every endpoint supports every filter (e.g. inventory has no time dimension — see Common Issues below).

**Backend structure** (`server/main.py`, single file): Pydantic models for each resource → `apply_filters`/`filter_by_month` helpers → route handlers. Data is loaded once at import time by `server/mock_data.py` from `server/data/*.json`; nothing writes back to those files at runtime.

**Frontend structure** (`client/src/`):
- `views/*.vue` — one per route, registered in `main.js` (Dashboard, Inventory, Orders, Demand, Spending, Reports — note `Backlog.vue` exists but currently has no route)
- `components/*.vue` — modals and shared UI (detail modals, `FilterBar`, `ProfileMenu`, etc.)
- `composables/` — `useFilters.js` (shared filter state), `useAuth.js`, `useI18n.js`
- `api.js` — single axios client; all HTTP calls go through here
- `locales/` — `en.js`/`ja.js` for `useI18n`

**Known gap**: `client/src/api.js` calls `/api/tasks` and `/api/purchase-orders` endpoints (create/read/update/delete) that are not implemented in `server/main.py` (only `PurchaseOrder`/`CreatePurchaseOrderRequest` Pydantic models exist, unused by any route). Treat these as unfinished features, not bugs to silently "fix" by guessing — confirm intent before implementing.

## Key Patterns
- Use unique keys in `v-for` (not `index`) - use `sku`, `month`, etc.
- Validate dates before `.getMonth()` calls
- Update Pydantic models in `server/main.py` when changing JSON data structure in `server/data/*.json`
- Inventory filters don't support month (no time dimension)
- Revenue goals baked into mock data: $800K/month single, $9.6M YTD all months

## API Endpoints
- `GET /api/inventory` - Filters: warehouse, category
- `GET /api/inventory/{id}` - Single item, 404 if missing
- `GET /api/orders` - Filters: warehouse, category, status, month
- `GET /api/orders/{id}` - Single order, 404 if missing
- `GET /api/dashboard/summary` - All filters
- `GET /api/demand`, `/api/backlog` - No filters
- `GET /api/spending/*` - summary, monthly, categories, transactions
- `GET /api/reports/quarterly`, `/api/reports/monthly-trends` - Computed from `orders`, no filters

## File Locations
- Views: `client/src/views/*.vue`
- API Client: `client/src/api.js`
- Backend: `server/main.py`, `server/mock_data.py`
- Data: `server/data/*.json`
- Styles: `client/src/App.vue`

## Design System
- Colors: Slate/gray (#0f172a, #64748b, #e2e8f0)
- Status: green/blue/yellow/red
- Charts: Custom SVG, CSS Grid for layouts
- No emojis in UI
