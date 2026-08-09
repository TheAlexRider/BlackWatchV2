# RBAC and self-audit

## Role model

Two roles, hierarchical:

- `admin` — full mutation power. Can call every `POST`/`PUT`/`PATCH`/`DELETE`
  route and read `/api/audit`.
- `viewer` — reads only. Can hit every `GET` route. Any mutation returns 403.

New accounts default to `viewer`. The first-run seed (`admin`/`password`) is
created as `admin`. On the RBAC migration, the oldest existing user is
promoted to `admin` so no operator is locked into viewer-only.

### Promote a user to admin

```sql
UPDATE auth_users SET role = 'admin' WHERE username = 'alice';
```

### Demote

```sql
UPDATE auth_users SET role = 'viewer' WHERE username = 'bob';
```

## Enforcement

- `blackwatch/auth.py` exports `require_role(role)`. Every mutating route in
  `blackwatch/api.py` carries `dependencies=[Depends(require_role("admin"))]`.
- The auth middleware in `blackwatch/main.py` stashes `request.state.user`
  and `request.state.role`; unknown role → `viewer` (fail closed).
- The UI wraps admin-only controls with `<RequireAdmin>`
  (`blackwatch-ui/components/auth/RequireAdmin.tsx`), sourced from
  `<AuthProvider>` which calls `/api/whoami`. The backend is authoritative;
  the UI only hides what a viewer can't use.

## Audit table

Append-only. No `UPDATE`, no `DELETE` route touches it.

```
audit(
  id           BIGSERIAL PRIMARY KEY,
  ts           TIMESTAMPTZ  DEFAULT now(),
  actor        TEXT,
  actor_role   TEXT,
  ip           TEXT,
  method       TEXT NOT NULL,
  path         TEXT NOT NULL,
  status       INTEGER NOT NULL,
  body_summary TEXT
)
```

Indexes: `(ts DESC)` and `(actor, ts DESC)`.

Written by the `_audit_middleware` in `blackwatch/main.py` for every
non-GET request. Audit-log failures are swallowed so audit breakage cannot
break the actual request.

## Scrubbing rules

Before the request body is persisted (first 500 chars), the following are
replaced with `***REDACTED***`:

- JSON keys (case-insensitive): `password`, `passwd`, `token`, `secret`,
  `api_key` / `apikey`, `authorization`, `slack_webhook`,
  `access_key` / `secret_key`.
- AWS access key IDs matching `AKIA[0-9A-Z]{16}`.
- JWT-shaped tokens matching `eyJ...\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+`.

## Compliance mapping

- **HITRUST 0910.09aa** (audit logging of security events) — every
  mutation is recorded with actor, timestamp, source IP, and outcome.
- **HITRUST 0912.09ab** (monitoring of use of information assets) — the
  `/api/audit` endpoint gives an admin an on-demand review surface.
- **SOC 2 CC7.2** (system operations — anomaly detection) — the
  append-only log with an immutable-by-design surface supports
  detection and investigation.
- **SOC 2 CC6.1** (logical access controls) — role-based gating with
  fail-closed default and least-privilege viewer role.
