# blackwatch-ui

Next.js 15 frontend for BlackWatch. Replaces the Jinja templates page-by-page.

Source of truth for design: `../docs/ui-design.md`.

## Quick start (local)

Prereqs: Node 20+.

```bash
cd blackwatch-ui
npm install
npm run dev
```

Opens at http://localhost:3000. Calls to `/api/*` are proxied to `http://localhost:8000` by default (or `BW_API_URL` if set).

## Run alongside FastAPI via compose

From repo root:

```bash
docker compose up -d
```

This brings up `db`, `app` (FastAPI), and `ui` (Next.js) together. UI is on `:3000`, FastAPI on `:8000`.

## Build the production image manually

```bash
docker build -t blackwatch-ui:dev ./blackwatch-ui
```

Outputs a ~80MB image because of `output: "standalone"` in `next.config.mjs`.

## What's here right now (Phase 0)

- Tokens + Tailwind v4 + IBM Plex / JetBrains Mono fonts
- App shell: TopNav + SideNav (collapsible) + content area
- 3 primitives: Button, Input, StatusDot
- Placeholder `/` page

No real pages yet. Phase 1 starts with `/events`.
