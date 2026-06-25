# BlackWatch UI — Design & Architecture Plan

**Status**: Planning. No code written yet.
**Stack target**: Next.js 15 (App Router) + TypeScript + Tailwind v4 replacing the current FastAPI Jinja templates.
**Last updated**: 2026-06-08

---

## Scope

**This project is a 1-for-1 port from Jinja templates to Next.js pages.** No new features, no auth rework, no behavior change. Visual layer only.

If something in the existing tool is broken, it stays broken in the port — fix it in a separate sprint.

## Locked decisions

| Decision | Locked at |
|---|---|
| **Auth** | **Keep current model unchanged** — no in-app login, no `next-auth`. Whatever protects the UI today (network exposure, nginx, etc.) continues to protect it. Next.js attaches the existing machine token from env when proxying to FastAPI. |
| **Real-time** | **Deferred.** Current Jinja UI doesn't have it; the port doesn't need it for parity. Pages refresh on navigation / manual refresh, same as today. Revisit after the port is complete. |
| **Primitives** | **Radix raw, styled from zero.** No shadcn. |
| **First page order** | **`/events` → `/aws-posture` → `/hosts/[id]`** after foundation. |

---

## 1. Aesthetic direction — "Forensic minimalism"

The reference is: Linear's density × Vercel's typography discipline × the deliberate quiet of a SOC console at 3am × the tabular precision of a hex editor.

The *opposite* of: rounded-2xl cards, purple gradients, hero animations, illustration-heavy empty states.

### Why this aesthetic for BlackWatch

- Solo operator who lives in the tool — every visual flourish is friction.
- Severity is the only thing that should shout. Everything else gets out of the way.
- High information density. Tables, timestamps, IPs need to line up perfectly.
- The seriousness of the domain (security findings, PHI-adjacent data) calls for *quiet and exact*, not "delightful."

### Differentiation in one sentence

> Every screenshot is recognizably BlackWatch from the teal signal-color accent, the IBM Plex type, the hairline borders, and the tabular numerals — without any of those being loud about it.

---

## 2. Visual system

### Typography (self-hosted, no Google Fonts CDN)

| Use | Font |
|---|---|
| UI + body | **IBM Plex Sans** |
| Monospace (IPs, timestamps, IDs, JSON) | **JetBrains Mono** |
| Section labels (small caps style) | IBM Plex Sans, `font-size: 11px`, `text-transform: uppercase`, `letter-spacing: 0.08em`, tertiary text color |

Global rule: `font-variant-numeric: tabular-nums` on everything so counts/latency/byte-totals align vertically across rows.

**Banned**: Inter, Roboto, Arial, system stacks, Space Grotesk, Geist.

### Color tokens

Dark theme is canonical. Light theme is a toggle but secondary.

```css
:root {
  /* surfaces */
  --bg:               #0A0B0F;   /* not pure black — slight cool cast */
  --surface-1:        #101218;
  --surface-2:        #181B22;   /* hover, raised */

  /* lines */
  --border-subtle:    rgba(255, 255, 255, 0.06);
  --border:           rgba(255, 255, 255, 0.12);

  /* text */
  --text-primary:     #E4E4E7;
  --text-secondary:   #9CA3AF;
  --text-tertiary:    #6B7280;
  --text-disabled:    #4B5563;

  /* brand — the ONE saturated color outside severity */
  --signal:           oklch(0.72 0.14 195);  /* teal-cyan */
  --signal-glow:      oklch(0.72 0.14 195 / 0.15);

  /* severity — never used as fill, only as accent (border, dot, sparkline stroke) */
  --sev-critical:     #F43F5E;
  --sev-high:         #FB923C;
  --sev-medium:       #FACC15;
  --sev-low:          #60A5FA;
  --sev-resolved:     #34D399;
}
```

**Rules**:
- Severity colors are accent-only — 2px left borders, 8px dot indicators, sparkline strokes, single-character punctuation ("● 3 critical"). **Never** as a background fill.
- `--signal` (teal) is the brand. Used for: logo mark, active sidebar item left border, focused input outline, selected row left edge, default chart series.
- All borders are hairline (1px, or 0.5px on retina via transform tricks).

### Motion (restrained)

| Trigger | Behavior |
|---|---|
| Route transition | 80ms opacity fade only |
| New row via SSE | 600ms tint-to-clear (severity color → surface) |
| Status pill change | Cross-fade, no swap |
| Sidebar collapse | 180ms ease-out |
| Long async op | 1px progress bar at top of viewport |

**Forbidden**: bounces, spring physics, scroll-triggered hero reveals, decorative animations, parallax.

### Signature details

- **Live indicator in navbar**: 6px pulsing dot (`--signal`) + monospace events-per-second counter. The visual signature.
- **8px dot grid background** on empty states only (`rgba(255,255,255,0.04)`). The only place backgrounds get texture.
- **Severity row indicator** = 2px left border on the row, never a colored row background.
- **Timestamps** render as relative on default, absolute on hover, via native `<time>` element formatting.

---

## 3. Tech stack — locked picks

| Decision | Pick | Why |
|---|---|---|
| Framework | Next.js 15, App Router | RSC streaming for tables; user requested Next.js |
| Language | TypeScript, strict | Mandatory for state this complex |
| Styling | Tailwind v4 + CSS variables | v4's CSS-first config matches the token system |
| Component primitives | Radix UI direct | Headless, accessible, no default styling baggage |
| Icons | Lucide | Clean consistent stroke |
| Data fetching | TanStack Query | Cache invalidation, retries, optimistic updates |
| Tables | TanStack Table (headless) | Virtualization for 10k+ event rows |
| Charts | Recharts | Sparklines + simple time-series |
| Forms | React Hook Form + Zod | Connector configs are 13+ fields with conditional validation |
| Date/time | `date-fns` | Tree-shakable, ISO-first |
| Real-time | Deferred | Not in current Jinja UI; not required for parity |
| Auth | None added | Out of scope — keep current model |

**Deliberately NOT in the stack**:
- No global state library (Redux/Zustand) — Query is the cache, URL is the rest of state
- No animation library (Framer Motion) — CSS transitions cover restrained motion
- No design system package (MUI, Mantine, Chakra) — the point of the aesthetic is that it's not one of those

---

## 4. Information architecture

Routes (App Router):

```
/                        Overview — severity counts, recent criticals, host health summary (NEW)
/services                Service inventory
/services/[id]           Service detail
/hosts/[id]              Host detail — the EC2 dashboard; densest page
/events                  Event firehose — virtualized; most-used page
/events/[id]             Event drill-down
/rules                   Rule index
/rules/[id]              Rule edit + preview matches
/aws-posture             Posture findings — counter grid + per-resource-type tables
/aws-posture/[finding]   Finding detail + evidence JSON
/buckets                 S3 inventory
/iam                     IAM findings
/connectors              Connector list (was buried in /settings — promoted)
/connectors/new          Wizard
/connectors/[id]         Per-connector edit
/settings                System settings (tokens, schema version, build info)
```

Opinion: split today's `/settings` page into `/connectors` (daily driver) and `/settings` (rarely touched). Connector edit was the highest-touch surface in recent work.

---

## 5. Component inventory

### Primitives — `components/ui/`

Owned by us, styled from scratch on Radix headless primitives:

```
Button         variants: primary, secondary, ghost, danger; sizes: sm, md
IconButton     square; single icon; tooltip integrated
Input          text + numeric variants, monospace numeric option
Select         Radix Select, fully restyled
Switch         connector enable/disable
Checkbox       posture check toggles
Tabs           horizontal underline tabs
Tooltip        instant-hover, no fade delay (operator tool — show fast)
Dialog         modal, no backdrop animation
Sheet          side-drawer (event detail, connector edit)
Toast          bottom-right, 3s auto-dismiss
Skeleton       table-row loading
Spinner        1px-stroke circular, used sparingly
ProgressBar    1px top-of-viewport loader
```

### Domain — `components/domain/`

```
StatusPill           ● + label, no background, severity-colored dot
SeverityBadge        same shape, for finding severity
EventRow             timestamp · action · resource · severity; virtualized
EventDetail          right-sheet with full JSON + adapter trace
FindingRow           posture finding with resolve action
HostStatusCard       memory % · CPU load · sessions · rpm-db · stalled collectors
LiveCounter          navbar events/sec pill with pulsing dot
TimestampCell        relative + absolute-on-hover, monospace
ResourceBadge        icon + ID truncated middle (e.g. "i-09a…b3f")
KeyValueGrid         evidence JSON rendered, not raw <pre>
RuleMatchPreview     last N matching events in rule editor
ConnectorCard        /connectors index — name, status, last_run, run-now
ConnectorForm        dynamic from server schema (renders 13-checkbox posture form etc.)
SparklineCell        micro chart for recent activity in table cells (60s buckets)
EmptyState           dot-grid background, terse copy, optional action
ErrorBoundary        inline; doesn't crash the page
```

### Layout — `components/layout/`

```
TopNav              logo · breadcrumb · live counter · command-palette · account
SideNav             collapsible to icon-only; active item has signal-color left border
PageHeader          h1 + subtitle + action slot
ContentContainer    max-width with consistent gutters
DataPanel           hairline-bordered container for tables/cards
```

---

## 6. Layout system

```
┌─────────────────────────────────────────────────────────────┐
│ ▣ BLACKWATCH    /events             ● 14/s   ⌘K   ◌ TA      │  TopNav: 48px tall, hairline bottom border
├──────────┬──────────────────────────────────────────────────┤
│ overview │                                                  │
│ services │  EVENTS                          + new rule      │  PageHeader
│ hosts    │  Showing last 1000 events. 14 events/sec.        │  subtitle
│ events ● │                                                  │
│ rules    │  ┌─────────────────────────────────────────────┐ │
│ posture  │  │  timestamp ▼   action      resource   sev   │ │  Table header, mono, tabular nums
│ buckets  │  │  17:42:31      iam.policy  arn:…:foo   ●H   │ │
│ iam      │  │  17:42:29      sg.ingress  sg-09a…    ●C   │ │  Rows, 32px tall, hairline dividers
│  ─────   │  │  …                                           │ │
│ connect. │  │                                              │ │
│ settings │  └─────────────────────────────────────────────┘ │
└──────────┴──────────────────────────────────────────────────┘
```

- **SideNav**: 224px expanded, 48px collapsed (icon-only). State persisted in localStorage. Active item: 2px `--signal` left border. Divider between primary nav and secondary nav.
- **TopNav**: 48px. Logo+wordmark left. Breadcrumb after 16px gap. Live counter + ⌘K + account menu right.
- **Content area**: 1280px max-width on wide pages, 920px on detail pages. 32px page-side gutters.

---

## 7. Backend integration

Keep FastAPI. It becomes JSON-API-only. Next.js is the UI.

- Every existing `/ui/*` Jinja route gets a `/api/*` JSON counterpart.
- Jinja routes deleted page-by-page as Next.js takes over.
- Pattern:

```python
@router.get("/api/events")
async def list_events(...) -> JSONResponse:
    rows = await storage.list_events(...)
    return JSONResponse(content=[r.model_dump(mode="json") for r in rows])
```

**Real-time**: not in this phase. Pages refresh on navigation, same as current Jinja behavior. SSE / WebSocket / polling can be revisited as a follow-up sprint once the port is complete.

---

## 8. Auth — explicitly out of scope

Current model stays exactly as it is. The Next.js app:
- Has no login page.
- Reads the machine token from the same env var the Jinja app uses.
- Attaches it server-side when proxying to FastAPI.
- The browser never sees the token (same posture as before).

If a human-auth requirement appears later, it gets its own sprint and its own design doc.

---

## 9. Deployment shape

Lightsail box already runs FastAPI + Postgres in compose, nginx in front.

Add: a second container for Next.js in the same compose file.

```
nginx (Lightsail host)
   ├── /api/*       → fastapi:8000
   ├── /            → nextjs:3000
   └── /static/*    → nextjs:3000
```

Next.js builds in `output: 'standalone'` mode → ~80MB image instead of ~600MB.

Postgres unchanged. Container deploys independent.

---

## 10. Migration plan

Build the new app alongside the old. Cut over a page at a time so the tool is never offline.

| Phase | Scope |
|---|---|
| **0 — Foundation** | Next.js scaffold · Tailwind tokens · primitive components · layout (TopNav + SideNav) · Lightsail compose changes · placeholder `/`. No real pages yet, no auth work. |
| **1 — Validate the design** | `/events` (validates virtualized table, SSE, severity) → `/aws-posture` (validates design language on finding-heavy page) → `/hosts/[id]` (densest detail page) |
| **2 — Form-heavy pages** | `/services`, `/services/[id]`, `/connectors` + `/connectors/new` + `/connectors/[id]`, `/rules`, `/rules/[id]` |
| **3 — Remainder** | `/iam`, `/buckets`, `/settings`, and the `/` overview (now that we know what to put on it) |
| **4 — Cleanup** | Remove Jinja templates from FastAPI repo; nginx 301s legacy `/ui/*` paths to new routes |

---

## 11. Project structure

```
blackwatch-ui/
├── app/
│   ├── layout.tsx                     TopNav + SideNav shell
│   ├── page.tsx                       /
│   ├── events/page.tsx
│   ├── events/[id]/page.tsx
│   ├── hosts/[id]/page.tsx
│   ├── aws-posture/page.tsx
│   ├── connectors/page.tsx
│   ├── connectors/new/page.tsx
│   ├── connectors/[id]/page.tsx
│   ├── api/                           proxy routes to FastAPI (attach machine token server-side)
│   └── globals.css                    tokens + base styles only
├── components/
│   ├── ui/                            Button, Input, Select, …
│   ├── domain/                        StatusPill, EventRow, …
│   └── layout/                        TopNav, SideNav, …
├── lib/
│   ├── api.ts                         typed fetch wrapper
│   ├── auth.ts                        session helpers
│   ├── format.ts                      timestamp, byte, relative-time formatters
│   └── types.ts                       shared with FastAPI via codegen later
├── styles/
│   └── tokens.css                     CSS custom properties — single source of truth
├── public/
│   └── fonts/                         IBM Plex Sans + JetBrains Mono (self-hosted)
├── next.config.mjs
├── tailwind.config.ts
├── tsconfig.json
├── package.json
└── Dockerfile                         multi-stage, standalone output
```

---

---

## 12. Pending — notifications redesign (planned, not yet built)

The existing Jinja UI has 4 separate pages (Rules / Channels / Log / Acks) with YAML textareas. "Setting up a notification is real bad" per the user. The redesign:

### Single page `/notifications` with three stacked sections

- **CHANNELS** (top) — flat list, each row: name · type · enabled-pill · last-sent · [Test] [Edit]. "+ Add" button at top opens a modal.
- **NOTIFY ME WHEN** (middle) — the renamed Rules list. Each row reads as a sentence: `● critical → slack-security`. Actions: [Edit] [Silence ▾] [Disable] [Delete].
- **RECENT ACTIVITY** (bottom) — last 50 notification log entries inline. Link to `/notifications/log` for the full filterable view.

Acks are eliminated as a page. They appear instead as: an "Ack this fingerprint" button on `/events/[id]`; a "Silence" button on each rule row; and an active-acks banner at the top of `/notifications` ("3 active acks — clear").

### Add-channel modal

1. Pick channel **type** with cards: Slack · Webhook · Email · PagerDuty · Teams · Discord
2. Form fields render per type — **no YAML textarea**:
   - Slack: one field (webhook URL)
   - Email: SMTP host, port, from, to, `password_env`
   - PagerDuty: `routing_key_env`
   - Webhook: URL + optional auth header env var
3. "Advanced" disclosure for retry / rate-limit / digest / dedup. Hidden by default.

### Add-rule modal (Notify-me-when wizard)

1. **Criteria** — plain dropdowns and chips, no YAML:
   - Severity dropdown (default "high or above")
   - Category chips (IAM / posture / host / VPN / finding / network / …)
   - Module chips (optional)
   - Action contains: text input (optional)
2. **Send to** — channel chip-picker (multi-select)
3. **Advanced** — throttle override, priority, raw Condition YAML for power users

Translates to a flat `Route` matcher when saved with simple criteria; falls back to a `Condition` tree if advanced YAML is used. **No DB schema changes** — complexity hidden at the UI layer only.

### Log page

`/notifications/log` stays its own page. Already simple enough — just filters + table. Straight port.

---

## 13. Pending — live updates via SSE (planned, not yet built)

Real-time push for surfaces where stale data costs the operator something. Everything else stays request-response.

### Surfaces

| Page | Live? | Topic |
|---|---|---|
| `/events` (top of list) | ✅ | `events` |
| `/aws-posture` counters | ✅ | `posture` (finding.new + finding.resolved) |
| `/hosts` | ✅ | `hosts` (heartbeats; recompute `stale` client-side) |
| `/services` | ✅ | `services` (status transitions) |
| `/notifications` activity tail | ✅ | `notify` (log entries) |
| Everything else | ❌ | Request-response only |

### Backend

One SSE endpoint:

```python
@router.get("/stream")
async def stream(request: Request, topics: str = "events,posture,hosts,services,notify"):
    return StreamingResponse(_event_generator(request, topics.split(",")),
                             media_type="text/event-stream")
```

- An in-process **fan-out hub** with one `asyncio.Queue` per connection. The pipeline + projections push into the hub; the hub copies the message into every subscribed queue.
- Heartbeat ping every 15 s so nginx doesn't kill idle connections.
- On disconnect, the queue is dropped.

### Frontend

A single `useLiveStream(topics)` hook in `lib/live.ts`:

```ts
useEffect(() => {
  const es = new EventSource(`/api/stream?topics=${topics.join(",")}`);
  es.addEventListener("message", (e) => {
    const { topic } = JSON.parse(e.data);
    router.refresh();          // full server-component re-render
    // (or: queryClient.invalidateQueries({ queryKey: [topic] }))
  });
  return () => es.close();
}, [topics.join(",")]);
```

TanStack Query is added at this point as the cache invalidation layer (deferred from the original stack picks until now). Server components stay; we wrap them in a tiny client component that subscribes to the live stream and triggers `router.refresh()` when something arrives.

### nginx (Lightsail) — required tweaks

```
location /api/stream {
    proxy_pass http://app:8000;
    proxy_buffering off;
    proxy_read_timeout 1h;
    proxy_set_header Connection "";
    chunked_transfer_encoding off;
    add_header X-Accel-Buffering no;
}
```

### Fallback

If SSE drops or fails repeatedly, each live page falls back to TanStack Query's `refetchInterval: 5000`. The pulsing teal dot in the navbar (the `LiveCounter`) becomes a real connection-state indicator: green = SSE connected, amber = polling fallback, red = stale > 30 s.

### Build order

1. Backend `/api/stream` for one topic (`events`) — prove architecture
2. Backend fan-out hub; pipeline emits on `ingest_payload` success
3. Frontend `useLiveStream` hook + connection-state indicator in TopNav
4. Wire `/events` to subscribe + `router.refresh()` on matching push
5. Replicate to the other 4 surfaces
6. nginx config on Lightsail
7. Light-touch fallback logic

About half a day of work end-to-end. Most of it is the backend hub.

---

## Cross-references

- Aesthetic guidelines from the `frontend-design` skill apply throughout.
- User-stated constraints recorded here:
  - "simple but sober"
  - "navbar, sidebar, and other components" → reusable layout primitives
  - Next.js explicit choice
  - Will deploy on Lightsail behind reverse proxy
- Project-level design preferences (see `memory/feedback_design_preferences.md`): design before code, stable foundation, no over-engineering.
