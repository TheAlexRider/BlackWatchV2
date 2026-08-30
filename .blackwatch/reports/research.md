# BlackWatch R&D Report — product, capability, and reliability roadmap

Cycle focus: identify the next ten highest-value tasks after the notification
route consolidation work.

Date: 2026-08-30

## Assessment

BlackWatch has a broad ingestion and notification foundation, but the next
value comes from making coverage truthful and dependable before adding many
more integrations. The repository shows three high-leverage gaps: notification
event ownership is still broader than the verified contracts, several planned
capabilities remain deferred, and deployment/test environments can hide
regressions. Route 53/DNS query logs are a good additive module because the
existing CloudWatch/SQS and DNS tool foundations can be reused.

## Evidence-backed priorities

1. Notification rollout truth and producer/catalog parity remain incomplete
   (`blackwatch/notify/catalog.py`, `blackwatch/notify/profiles.py`,
   `blackwatch/ueba/check.py`, `blackwatch/posture/projection.py`).
2. The UI has canonical notification redirects now, but create flows still
   span `/notifications/create`, `/notifications/create/event`, and
   `/notifications/rules/new`; the route inventory should govern future cleanup.
3. Threat Hunter explicitly defers cross-account observability and Live Tail
   (`docs/threat-hunter.md:246-265`).
4. Route 53 query-log ingestion is not represented as a BlackWatch module,
   while CloudWatch Logs → SQS forwarding and DNS parsing already exist
   (`docs/rds.md`, `blackwatch/connectors/aws_sqs.py`,
   `blackwatch-ui/app/api/tools/dns-lookup/route.ts`).
5. Existing build evidence has dependency blockers (`psycopg`, `jinja2`, and
   broken local Node package links), so CI/environment reproducibility is a
   product reliability issue, not just developer convenience.

## Recommended order

BW-036 and BW-037 should precede broad new feature work. BW-038 through BW-040
stabilize analyst navigation and live visibility. BW-041 through BW-045 add
carefully bounded capability, including Route 53, without changing storage
destructively.
