# UEBA-lite (baseline / first-seen anomalies)

For each event that has an identifiable actor (an IAM user, VPN user, DB user,
Keycloak user, SSH user, etc.), BlackWatch maintains rolling per-principal
baselines of a small fixed set of dimensions. When a **never-before-seen
value** shows up for a principal that's past its warm-up window, we emit a
synthetic event:

```
<category>.anomaly.first_seen_<dimension>
```

Example: `iam.anomaly.first_seen_source_ip`, `vpn.anomaly.first_seen_source_country`.

## Dimensions tracked

- `source_ip` — raw IP from `actor.source_ip`
- `source_country` — from `event.extra.intel.country` (if the intel enrichment ran)
- `source_asn` — from `event.extra.intel.asn`
- `hour_of_day` — UTC hour of the event
- `action` — event action string (e.g. `iam.role.assume`)
- `user_agent_family` — first token of any UA string

A missing dimension on an event is skipped (never stored as empty).

## Warm-up

The default warm-up window is **7 days from a principal's first-seen row**.
During warm-up we silently populate baselines but do NOT emit anomaly events.
This is why fresh accounts don't get spammed with "first-seen from London" on
day one — we need enough history to have a real baseline.

Override the default in `rules/ueba.yaml`:

```yaml
default_warm_up_days: 14
dimensions:
  hour_of_day:
    warm_up_days: 30   # noisier; give it more time
```

## Disabling a dimension

Set `enabled: false` in `rules/ueba.yaml`:

```yaml
dimensions:
  hour_of_day:
    enabled: false
```

The config is reloaded automatically when the file's mtime changes.

## Idempotency

- Baseline upserts use `INSERT ... ON CONFLICT ... DO UPDATE`; a replayed
  event just bumps `count` and `last_seen`.
- An anomaly only fires when the resulting `count == 1` (i.e. this insert
  is genuinely the first sighting of that value).
- The anomaly event's dedup fingerprint is deterministic on action +
  principal + target, so the events table dedups duplicates too.

## Storage

State lives in a separate SQLite file at `$BW_UEBA_DB` (default `baseline.db`
in the process cwd). The main events store is untouched.

Schema:

- `principal_baseline(principal_type, principal_id, dimension, value,
  first_seen, last_seen, count)` — PK on the first four columns.
- `principal_first_seen(principal_type, principal_id, first_ever)` — used
  for the warm-up check.

## Clearing a stuck baseline

If a false-positive dimension is polluting a principal's baseline (e.g. an
office IP was recorded as `source_ip=?` because of an adapter bug), delete
the offending rows:

```sql
-- one specific bad value
DELETE FROM principal_baseline
 WHERE principal_type='user'
   AND principal_id='alice'
   AND dimension='source_ip'
   AND value='?';

-- full reset of one principal (also restarts warm-up)
DELETE FROM principal_baseline
 WHERE principal_type='user' AND principal_id='alice';
DELETE FROM principal_first_seen
 WHERE principal_type='user' AND principal_id='alice';
```

Or from Python:

```python
from blackwatch.ueba import db
db.clear_principal("user", "alice")                   # everything
db.clear_principal("user", "alice", ["source_ip"])    # one dimension
```

## API

- `GET /api/ueba/baselines?principal_type=&principal_id=&dimension=`
- `GET /api/ueba/anomalies?principal=&limit=`

The UI at `/ui/ueba` renders both — "Recent anomalies" tab (default) and
"Baseline explorer" with filters.
