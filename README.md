# BlackWatch

Centralized, modular, event-first security telemetry platform. Any source
becomes a *module* that normalizes its telemetry into a single canonical event;
the core handles storage, search, (soon) rules, alerting, and notification
routing — one console instead of many disconnected AWS dashboards.

- Architecture & philosophy: see [`docs/`](docs/) — start with
  [`docs/EVENT_SCHEMA.md`](docs/EVENT_SCHEMA.md), the frozen event contract.

## Status

**Phase 0 — spine:** POST a payload → normalized event stored → searchable.
**Phase 1 — rules + routing:** events are scored against declarative rules on
ingest (assigning `severity`/`tags`/`rule_matches`), then routed to notification
channels (Slack / generic webhook) based on severity/category/module/tag.

- `POST /ingest` — token-authenticated; normalizes → scores → routes.
- `GET /events` — filter by module/category/action/outcome/severity/actor/time + free-text `q`.
- `GET /events/{id}`, `GET /rules`, `GET /channels`, `GET /routes`, `GET /modules`, `GET /healthz`.
- `POST /notifications/test?channel=<name>` — send a test message to a channel.
- `GET /vpn/status` — live view: per OpenVPN server, is it up and who is connected now.

### Web console

A built-in server-rendered UI (no SPA, no build step) lives at **`http://localhost:8000/ui`**
(`/` redirects there). Pages:
- **Dashboard** — severity counts, VPN server status, notable + recent events (auto-refreshes).
- **Events** — filterable feed (severity/category/module/action/free-text) → event detail (envelope + raw).
- **VPN** — live who's-connected per server, with stale/down flags (auto-refreshes).
- **Rules** — all loaded detection/suppression rules.
- **Settings → Connectors** — configure SQS-pull sources (CloudTrail / EC2 host
  agent / OpenVPN agent) from the UI: Test, Run-now, and an interval scheduler.
- **Notifications** — fully UI-managed: **Rules** (Condition matcher, channel
  fan-out, throttle, silence, test-fire), **Channels** (`slack`/`webhook`/`email`/
  `pagerduty`/`teams`/`discord`, Jinja2 templates, retries, rate limit, digest),
  **Log** (every send attempt — sent / failed / rate-limited / digested), **Acks**
  (silence a specific event fingerprint while investigating). Secrets reference env
  vars (`password_env`, `routing_key_env`) — never stored. Dispatch is async via a
  send-queue worker, so slow channels can't block ingest.

### Connectors

A connector is a source BlackWatch actively **pulls** from on a schedule (vs. push
sources that POST to `/ingest`). Configured in the UI, persisted in the DB, run by
an in-process scheduler. The sole connector type today is the generic
**`aws_cloudtrail_sqs`** SQS poller, used by all three push agents (CloudTrail
forwarder, EC2 host agent, OpenVPN agent) — `target_module` selects which adapter
normalizes the drained payloads. **Secrets:** AWS creds come from a mounted
`~/.aws` profile (never stored). Run-now/scheduling unlock only after a successful
**Test** (the `verified` flag).

The interactive API explorer remains at `/docs`.

### Modules

- **generic** — universal passthrough/webhook intake.
- **vpn.openvpn** — OpenVPN Community Edition. An on-host agent
  ([scripts/vpn_agent.py](scripts/vpn_agent.py)) runs on the VPN box and pushes
  service state, the OpenVPN status file, and journal auth lines to SQS via the
  instance role (no inbound SSH, no key management, immune to fail2ban). The
  agent also runs a `journalctl -fu` follower thread that ships matched auth
  events in sub-second batches. BlackWatch drains via the SQS connector
  (`target_module=vpn.openvpn`), maintains a live read-model (`GET /vpn/status`),
  and derives session start/end/concurrent events by diffing snapshots. Setup:
  [deploy/vpn/](deploy/vpn/).
- **aws.cloudtrail** — AWS IAM/CloudTrail security telemetry. CloudTrail →
  EventBridge (high-value filter) → Lambda forwarder → SQS; BlackWatch pulls the
  queue via the SQS connector (`target_module=aws.cloudtrail`) and normalizes records into
  `iam.*` / `auth.*` events (admin-policy attach, root usage, MFA removal, trust
  tampering, CloudTrail tampering, no-MFA login, …). Setup: [deploy/iam/](deploy/iam/).
- **ec2.host** — per-EC2 host telemetry. A Python reporter
  ([scripts/ec2_agent.py](scripts/ec2_agent.py)) on each instance pushes SSH/sudo
  access + a heartbeat to SQS via the instance role (no SSH, no inbound);
  BlackWatch polls via the SQS connector (`target_module=ec2.host`), normalizes to
  `host.*` events, maintains a per-host read-model (`/ui/hosts`), and alerts on
  agent **staleness** (absence detection). Setup: [deploy/ec2/](deploy/ec2/).

Notification channels + routes are configured in [`notifications.yaml`](notifications.yaml).

Not built yet (by design): dashboards UI, dedicated AWS CloudTrail module,
stateful/correlation rules, hot config reload. Those are the rest of Phase 1–3.

### Rules

Rules live as YAML in [`rules/`](rules/) — data, not code. Each is a leaf or an
`all`/`any`/`not` tree of `{field, op, value}` conditions over normalized event
fields. Operators: `equals`, `not_equals`, `in`, `contains`, `icontains`,
`regex`, `cidr`, `exists`, `startswith`, `endswith`. `action: alert` rules set
severity; `action: suppress` rules (allowlists) force `informational` and win
over alerts. Edit the YAML and restart to reload.

## Run it

```bash
docker compose up --build
```

This starts Postgres and the app on `http://localhost:8000`.

### Data safety — read before rebuilding

`docker compose up --build` preserves the Postgres database in the named
`bw_pgdata` volume. Never use `docker compose down -v`: the `-v` flag deletes
that persistent database volume and all BlackWatch data. Do not rename the
volume or change its Compose project without first verifying the existing
volume and taking a backup.

BlackWatch migrations are required to be data-preserving. The application
refuses to run a migration containing automatic table, column, row, schema,
or database deletion. If a future change appears to require destructive
handling, stop and perform it only as a separately reviewed, backed-up
operator action.

### Send a test event (PowerShell)

```powershell
$body = @{
  action   = "iam.policy.attach"
  category = "iam"
  outcome  = "success"
  actor    = @{ principal = "arn:aws:iam::123:user/dave"; source_ip = "203.0.113.5" }
  target   = @{ id = "arn:aws:iam::aws:policy/AdministratorAccess"; type = "iam.policy" }
} | ConvertTo-Json

Invoke-RestMethod -Uri http://localhost:8000/ingest -Method Post `
  -Headers @{ "X-BlackWatch-Token" = "devtoken" } `
  -ContentType "application/json" -Body $body

Invoke-RestMethod -Uri "http://localhost:8000/events?category=iam"
```

### Send a test event (curl)

```bash
curl -X POST http://localhost:8000/ingest \
  -H "X-BlackWatch-Token: devtoken" -H "Content-Type: application/json" \
  -d '{"action":"iam.policy.attach","category":"iam","outcome":"success",
       "actor":{"principal":"arn:aws:iam::123:user/dave"},
       "target":{"id":"arn:aws:iam::aws:policy/AdministratorAccess"}}'

curl "http://localhost:8000/events?category=iam"
```

## Local dev (without containerizing the app)

```bash
python -m venv .venv && . .venv/Scripts/activate   # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
docker compose up -d db                            # Postgres only
$env:DATABASE_URL = "postgresql://blackwatch:blackwatch@localhost:5432/blackwatch"
$env:BLACKWATCH_TOKENS = "devtoken:generic"
uvicorn blackwatch.main:app --reload
```

## Tests

```bash
pip install pytest
pytest -q   # unit tests for the event model + generic adapter (no DB needed)
```

## Project layout

```
blackwatch/
  event.py          # the normalized event envelope (frozen contract)
  api.py            # ingest + search HTTP surface (transport layer)
  storage.py        # the only module that touches SQL
  db.py             # Postgres pool + migrations
  config.py         # env-driven settings
  modules/
    base.py         # Adapter contract (pure raw -> events transform)
    generic.py      # passthrough adapter / universal webhook intake
    vpn_openvpn.py  # OpenVPN adapter + status-file parser (v1/v2/v3)
    registry.py     # module id -> adapter, with generic fallback
  vpn/
    projection.py   # stateful read-model + snapshot-diff derived events
  rules/
    model.py        # Rule + recursive Condition models
    operators.py    # the fixed operator vocabulary
    engine.py       # load + evaluate rules; assigns severity/tags
  notify/
    model.py        # Channel + Route models
    channels.py     # slack/webhook delivery (best-effort, stdlib only)
    router.py       # match events -> channels, throttle, dispatch
  sql/              # 001_init (events), 002_vpn (vpn_status read-model)
rules/              # rule content as YAML (operator-editable)
notifications.yaml  # channels + routes (operator-editable)
scripts/webhook_listener.py    # local receiver for testing notifications
scripts/vpn_agent.py           # on-host agent for the OpenVPN box (push to SQS)
scripts/ec2_agent.py           # on-host agent for any EC2 (push to SQS)
docs/EVENT_SCHEMA.md
tests/
```
