# Notifications — setup guide

How to wire up each notification channel BlackWatch supports, end-to-end.
Every channel type follows the same flow inside the dashboard; the only thing
that differs is **how you get the URL or key from the provider**.

---

## How the system fits together

```
event lands  →  rule matches (severity / category / module)  →  channel sends
   /events       /notifications "Notify me when…"                /notifications "Channels"
```

You configure **two things**, in order:

1. **Channels** — *where* messages go (Slack room, email inbox, PagerDuty
   service, etc.). One channel can be referenced by many rules.
2. **Rules** — *which* events trigger a send, and to which channels.

Both live at `/notifications` in the dashboard. Recent firings show up in the
**recent activity** tail on that page; the full filterable history is at
`/notifications/log`.

### Secrets — where they live

BlackWatch **never stores secrets in the database**. Anywhere a field asks for
a "password" or "routing key", you supply the **name of an environment
variable** that holds the actual secret. The variable is set on the `app`
container in `docker-compose.yml`:

```yaml
services:
  app:
    environment:
      SMTP_PASS: ${SMTP_PASS}            # email password
      PD_ROUTING_KEY: ${PD_ROUTING_KEY}  # pagerduty key
```

…and the actual values come from a host-local `.env` file (not committed)
or from your shell. Channel forms reference these by name (`password_env:
SMTP_PASS`), so the secret never touches the DB.

---

## Universal channel options (advanced section)

Every channel type has the same advanced section, collapsed by default in the
form. Adjust only when you have a reason — the defaults are sane:

| Field | Default | What it does |
|---|---|---|
| **Message template** | (per-type default) | Jinja2 template. Available: `{{ event.severity }}`, `{{ event.action }}`, `{{ event.actor.principal }}`, `{{ event.target.id }}`, `{{ channel_name }}`. Blank = sensible per-type default. |
| **Retries** | 3 | Times to retry on transient failure (5xx, timeout). 0 = no retry. |
| **Backoff (s)** | 5 | Seconds between retries, exponential. |
| **Rate limit (per min)** | 0 = unlimited | Hard cap on messages-per-minute for this channel. Anything beyond is dropped with status `rate_limited` in the log. Useful for noisy webhooks. |
| **Dedup window (s)** | 300 | Drop a follow-up message if the same `(rule, channel, event fingerprint)` has fired in the last N seconds. 0 = no dedup. |
| **Digest window (s)** | 0 = off | If set, collect messages for N seconds and send one summary. Turns a 50-message burst into one digest message. |

---

# Channel types

## 1. Slack

### Prerequisites
- A Slack workspace where you can install apps
- A channel to receive alerts (create `#blackwatch-alerts` or similar)

### Get a webhook URL

1. Open <https://api.slack.com/apps> → **Create New App** → **From scratch**
2. Name it `BlackWatch`, pick your workspace → **Create App**
3. In the left sidebar: **Incoming Webhooks** → toggle **Activate** ON
4. Scroll down → **Add New Webhook to Workspace**
5. Pick the channel → **Allow**
6. Copy the **Webhook URL** — it looks like
   `https://hooks.slack.com/services/T012ABC/B345DEF/xyz123abc456`

### Configure in BlackWatch

1. `/notifications` → **+ add channel** → **Slack** card
2. **Name**: `slack-security` (or whatever you'll reference in rules)
3. **Webhook URL**: paste the URL from step 6 above
4. **Enabled**: ticked (default)
5. Click **Add channel**
6. From the channel list, click **Test** — you should see a test message
   land in the Slack channel within a second
7. Click **Enable** if it wasn't already

### Notes
- The URL contains the credential. It's stored in the DB as plain text — that's
  fine because Slack webhook URLs are scoped to one channel and have no other
  privileges, and the DB is internal-only. Treat the URL itself as a secret
  in the sense of "don't paste it in chat."
- To rotate: regenerate the webhook in the Slack app config, paste the new URL
  in the BlackWatch edit form.
- Default message template renders like:
  `[critical] iam.policy.put by ops-alice@example.com`

---

## 2. Webhook (generic HTTP)

For local testing, n8n, an internal Lambda, or anything that accepts a JSON
POST.

### Prerequisites
- An HTTP(S) endpoint that accepts POST with `Content-Type: application/json`
- It must be reachable from the BlackWatch container (so localhost only works
  via `host.docker.internal:<port>`)

### Configure in BlackWatch

1. `/notifications` → **+ add channel** → **Webhook** card
2. **Name**: `local-webhook` (or describe the receiver)
3. **URL**: e.g.
   `http://host.docker.internal:9000/hook` for a local listener, or
   `https://internal-relay.example.com/incidents` for prod
4. **Add channel**, **Test**, **Enable**

### Payload shape (so the receiver knows what to expect)

```json
{
  "channel_name": "local-webhook",
  "event": {
    "event_id": "…",
    "event_time": "2026-06-09T12:34:56.789Z",
    "severity": "high",
    "category": "iam",
    "action": "iam.policy.put",
    "actor": { "principal": "ops-alice@example.com", "source_ip": "1.2.3.4" },
    "target": { "id": "arn:aws:iam::…:policy/AdminAccess", "type": "policy" },
    "extra": { … }
  },
  "rule_name": "critical-to-webhook"
}
```

The full event envelope is included. If you set a custom **Message template**
in advanced options, that templated string replaces the body and the wrapper
shape doesn't apply — you control everything.

### Local testing
There's a tiny listener script in the repo:

```bash
python scripts/webhook_listener.py
```

It binds to `:9000` and prints every POSTed body. Useful for verifying the
shape before pointing a real channel at it.

---

## 3. Email (SMTP)

### Prerequisites
- An SMTP relay you can authenticate against. Common choices:
  - **Gmail** with an App Password
  - **AWS SES** (recommended for AWS-shop)
  - Your own MX (Postfix, etc.)
- A `From` address the relay will let you send as
- One or more `To` addresses

### Configure in BlackWatch

1. **+ add channel** → **Email**
2. **Name**: `ops-email`
3. **SMTP host**: e.g. `smtp.gmail.com`, `email-smtp.us-west-1.amazonaws.com`
4. **SMTP port**: `587` (STARTTLS) is the common pick; `465` if your relay
   uses implicit TLS; `25` only on internal/trusted networks
5. **Use TLS**: leave ticked (STARTTLS)
6. **SMTP user**: usually the full email address for Gmail; for SES it's the
   IAM-SMTP user (NOT your normal IAM user — see SES below)
7. **Password env var**: just the **name** of the env var holding the password
   — e.g. `SMTP_PASS`. The actual value goes in `docker-compose.yml`.
8. **From**: `alerts@example.com`
9. **To**: comma-separated list: `you@example.com, oncall@example.com`
10. **Add channel**, **Test**, **Enable**

### Setting the env var

In `docker-compose.yml`, on the `app` service:

```yaml
environment:
  SMTP_PASS: ${SMTP_PASS}
```

Then in a host-local `.env` file (gitignored):

```
SMTP_PASS=your-actual-app-password-here
```

Run `docker compose up -d app` to apply.

### Provider-specific notes

**Gmail** — won't accept your real account password. Steps:
1. Enable 2FA on the account
2. Go to <https://myaccount.google.com/apppasswords>
3. Generate an App Password named "BlackWatch"
4. Copy the 16-char password → that's what goes in `SMTP_PASS`
5. **SMTP host**: `smtp.gmail.com`, **port**: `587`, **TLS**: on

**AWS SES** — recommended for production:
1. Verify your `From` domain or address in SES
2. Move out of sandbox if needed (request prod access)
3. **SMTP credentials** are NOT your IAM access keys — go to
   SES console → **SMTP settings** → **Create SMTP credentials**
4. **SMTP user**: the generated `AKIA…` looking string from SES
5. **Password env var name**: e.g. `SES_SMTP_PASS`, value = the long
   string SES gave you
6. **Host**: `email-smtp.<region>.amazonaws.com`, **port**: `587`

**Office 365** — usually needs an OAuth-capable client, harder to set up
with plain SMTP. Use a relay or switch to a different channel.

---

## 4. PagerDuty

For real on-call paging.

### Prerequisites
- A PagerDuty account
- A service representing what you're paging on (create `BlackWatch Alerts`)

### Create the integration

1. PagerDuty → **Services** → pick or create the service
2. **Integrations** tab → **Add an integration**
3. Choose **Events API V2** (NOT v1)
4. Name it `BlackWatch` → **Add**
5. Copy the **Integration Key** — a 32-char string like
   `7b9c1e3f5d7a9c0e1f2a3b4c5d6e7f80`

### Configure in BlackWatch

1. **+ add channel** → **PagerDuty**
2. **Name**: `ops-pagerduty`
3. **Routing key env**: the **name** of an env var, e.g. `PD_ROUTING_KEY`
4. **Add channel**

### Set the env var

`docker-compose.yml`:
```yaml
environment:
  PD_ROUTING_KEY: ${PD_ROUTING_KEY}
```

`.env`:
```
PD_ROUTING_KEY=7b9c1e3f5d7a9c0e1f2a3b4c5d6e7f80
```

`docker compose up -d app`, then **Test** in the BlackWatch UI. A test
incident should appear in PagerDuty within seconds.

### Severity mapping

BlackWatch event severity maps to PagerDuty severity automatically:

| BlackWatch | PagerDuty |
|---|---|
| critical | critical |
| high | error |
| medium | warning |
| low / informational | info |

Use **rules** with `severity_at_least: critical` to gate which events actually
page someone — never wire PagerDuty up to every event.

### Notes
- Routing keys are per-service. If you want different services to handle
  different event categories (e.g. infra vs application), create separate
  channels with separate keys.
- To stop paging temporarily during maintenance: use the **Silence** dropdown
  on the rule (1h / 4h / 24h), or disable the rule entirely.

---

## 5. Microsoft Teams

### Prerequisites
- A Teams channel where you can add connectors

### Get a webhook URL

1. In Teams, go to the channel → **⋯** menu → **Connectors**
2. Find **Incoming Webhook** → **Configure**
3. Name it `BlackWatch`, optionally upload an icon → **Create**
4. Copy the URL — looks like
   `https://outlook.office.com/webhook/abc-def-…/IncomingWebhook/…`

### Configure in BlackWatch

1. **+ add channel** → **Teams**
2. **Name**: `teams-security`
3. **Webhook URL**: paste
4. **Add channel**, **Test**, **Enable**

### Notes
- Teams webhooks accept "MessageCard" JSON, which BlackWatch sends by default
- The URL is the credential, same caveat as Slack — don't paste it in chat

---

## 6. Discord

For dev teams or hobby use.

### Prerequisites
- A Discord server you admin
- A channel for alerts

### Get a webhook URL

1. In Discord, right-click the target channel → **Edit Channel**
2. **Integrations** → **Webhooks** → **New Webhook**
3. Name it `BlackWatch`, pick the channel → **Save**
4. Click **Copy Webhook URL**

### Configure in BlackWatch

1. **+ add channel** → **Discord**
2. **Name**: `discord-alerts`
3. **Webhook URL**: paste
4. **Add channel**, **Test**, **Enable**

---

# Rules — "Notify me when…"

After a channel is verified + enabled, set up a rule that decides which
events go to which channels.

1. `/notifications` → **+ add rule**
2. **Name**: short, describes the intent — `critical-to-slack`, `iam-to-pagerduty`
3. **Enabled**: ticked
4. **Severity**: pick "any" / "critical only" / "high or above" / etc. *(at least)*
5. **Categories** (optional, multi-select chips): iam · posture · host · vpn · finding · network · ecs · s3 · service
6. **Modules** (optional, multi-select chips): aws.cloudtrail · ec2.host · vpn.openvpn · aws.s3 · aws.posture · aws.ecs
7. **Action contains** (optional): case-insensitive substring on the event action — e.g. `iam.policy` matches `iam.policy.put` and `iam.policy.delete`
8. **Send to**: pick one or more channels from the chip list
9. **Throttle (s)**: 0 = use channel default. Override here if a rule should be quieter than the channel allows.
10. **Add rule**

### Recipes for common cases

| Intent | Severity | Categories | Channel(s) |
|---|---|---|---|
| Critical anything → page | critical only | — | `ops-pagerduty` |
| High or above → Slack | high or above | — | `slack-security` |
| Posture findings → Slack (daily-driver) | any | posture | `slack-security` |
| IAM events → PagerDuty AND Slack | high or above | iam | `slack-security`, `ops-pagerduty` |
| VPN auth failures → Slack (informational stream) | any | vpn | `slack-security` |

### Advanced criteria (for power users)

The wizard covers ~95% of cases. For complex matches — regex on principals,
nested conditions, IP CIDR matches — open the **advanced** disclosure at the
bottom of the rule form and paste a JSON Condition tree:

```json
{
  "all": [
    {"field": "severity", "in": ["critical", "high"]},
    {"field": "actor.principal", "regex": "(?i)^ops-"},
    {"any": [
      {"field": "category", "equals": "iam"},
      {"field": "action", "icontains": "kms"}
    ]}
  ]
}
```

Operators available: `equals`, `not_equals`, `in`, `contains`, `icontains`,
`regex`, `cidr`, `exists`, `startswith`, `endswith`. Nest with `all` / `any` /
`not`.

When the advanced field is non-empty, it **overrides** the simple criteria
above it.

---

# Testing + troubleshooting

## Flow

1. Add channel → **Test** → check the receiving end
2. Add rule referencing the channel
3. Trigger an event that matches (or just wait for one)
4. `/notifications` recent activity tail shows the firing in <5s
5. `/notifications/log` for the full history with filters

## Channel Test fails

| Symptom | Likely cause |
|---|---|
| HTTP 401 / 403 | Wrong webhook URL or auth-env value |
| HTTP 404 | URL typo or webhook was deleted at the provider |
| Timeout | Wrong port (e.g. 25 instead of 587 for SMTP), or firewall blocking egress from the BlackWatch host |
| "SMTP auth failed" | Wrong `password_env` name, env var not set on the container, or provider requires an app password (Gmail) |
| "missing routing key" | PagerDuty `routing_key_env` set to a name but the env var isn't on the container |

After fixing the env var, run `docker compose up -d app` (NOT `restart` — env
var changes need a recreate, not a restart) and **Test** again.

## Rule doesn't fire

| Symptom | Likely cause |
|---|---|
| Event happened, rule looks right, no log entry | Rule criteria too narrow — try widening categories/modules and re-test |
| Log entry has status `throttled` | Throttle / dedup window is still active for the same fingerprint — wait it out or set throttle = 0 |
| Log entry has status `rate_limited` | Channel's rate limit was hit — bump rate_limit_per_min on the channel |
| Log entry has status `acked` | The event's fingerprint has an active ack — clear it on `/notifications` if you want messages to flow again |

## Silencing without disabling

Use the **Silence** dropdown on the rule row (`1h / 4h / 24h / clear`).
Silencing pauses sending but keeps the rule definition. Useful during
maintenance windows.

---

# Where things live (reference)

| Thing | Where |
|---|---|
| Channel definitions | DB table `notification_channels` |
| Rule definitions | DB table `notification_rules` |
| Sent / failed log | DB table `notification_log` |
| Active acks | DB table `notification_acks` |
| Channel implementation code | `blackwatch/notify/channels.py` |
| Routing + dispatch | `blackwatch/notify/router.py` |
| Worker loop (retries / digest) | `blackwatch/notify/worker.py` |
| Secrets | env vars on the `app` container; **never** in DB |
